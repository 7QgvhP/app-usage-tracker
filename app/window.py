"""
window.py - アクティブウィンドウと無操作時間の取得

Windows API への依存をこのモジュールに閉じ込め、
トラッカー本体のロジックをOSに依存せずテストできるようにする。
"""

from __future__ import annotations

import ctypes
import logging
from typing import Any, Optional

import psutil
import win32api
import win32gui
import win32process

logger = logging.getLogger(__name__)

# 実行ファイルの情報は変わらないため、一度読んだら保持する
# （値が None の場合は「読めなかった」ことを表す）
_embedded_name_cache: dict[str, Optional[str]] = {}


class _LastInputInfo(ctypes.Structure):
    """GetLastInputInfo に渡す LASTINPUTINFO 構造体"""

    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def detect_browser_site(window_title: str, rules: list[dict[str, Any]], fallback: str) -> str:
    """ブラウザのウィンドウタイトルから閲覧中のサイト名を判定する

    完全一致を優先するのは、PWAとして起動したウィンドウのタイトルが
    "YouTube" や "X" のようにサイト名のみになるため。
    どの規則にも一致しない場合は fallback（プロセス名）を返す。
    """
    title_stripped = window_title.strip()

    for rule in rules:
        for pattern in rule.get("patterns", []):
            if title_stripped == pattern:
                return rule["name"]

    # ブラウザのタブは "動画名 - YouTube" のような形式になるため部分一致で判定する
    for rule in rules:
        for pattern in rule.get("patterns", []):
            if len(pattern) > 1 and pattern in window_title:
                return rule["name"]

    return fallback


def shorten_embedded_name(name: str) -> str:
    """説明的な後半を落として簡潔にする

    例: "Antigravity - Agentic Desktop Application" → "Antigravity"
    """
    return name.split(" - ", 1)[0].strip()


def read_embedded_name(path: str) -> Optional[str]:
    """実行ファイルに埋め込まれた表示名を返す

    FileDescription を優先する。ProductName は Microsoft 製アプリで
    どれも "Microsoft® Windows® Operating System" になり、
    メモ帳とエクスプローラーが同一視されてしまうため。
    （例: r5apex_dx12.exe → "Apex Legends" / notepad.exe → "メモ帳"）
    どちらも取得できない場合は None。結果はパス単位で保持する。
    """
    if path in _embedded_name_cache:
        return _embedded_name_cache[path]

    name = None
    try:
        # 埋め込まれている言語・文字コードの組を取得する
        translations = win32api.GetFileVersionInfo(path, r"\VarFileInfo\Translation")
        for language, codepage in translations:
            for field in ("FileDescription", "ProductName"):
                key = rf"\StringFileInfo\{language:04x}{codepage:04x}\{field}"
                try:
                    value = win32api.GetFileVersionInfo(path, key)
                except Exception:
                    continue
                if value and value.strip():
                    name = shorten_embedded_name(value)
                    break
            if name:
                break
    except Exception as e:
        logger.debug(f"実行ファイルの名前を取得できませんでした ({path}): {e}")

    _embedded_name_cache[path] = name
    return name


def choose_display_name(process_name: str, embedded: Optional[str]) -> str:
    """表示に使う名前を決める

    実行ファイルの埋め込み名があればそれを使い、無ければプロセス名をそのまま使う。
    ここで決めた名前を任意の表示名へ読み替えるのは対応表（data/app_names.json）の役目。
    """
    if embedded and embedded.strip():
        return embedded.strip()
    return process_name


def get_active_app_name(
    ignore_processes: set[str],
    browser_processes: set[str],
    browser_site_rules: list[dict[str, Any]],
    use_executable_name: bool = True,
) -> Optional[str]:
    """現在フォアグラウンドにあるアプリの表示名を取得する

    Returns:
        アプリの表示名。取得できない場合や除外対象の場合は None。
    """
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None

        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid <= 0:
            return None

        process = psutil.Process(pid)
        process_name = process.name()

        if process_name in ignore_processes:
            return None

        if process_name.lower() in browser_processes:
            title = win32gui.GetWindowText(hwnd)
            if title:
                return detect_browser_site(title, browser_site_rules, process_name)

        embedded = None
        if use_executable_name:
            embedded = read_embedded_name(process.exe())

        return choose_display_name(process_name, embedded)

    except (psutil.NoSuchProcess, psutil.AccessDenied):
        # ウィンドウを取得した直後にプロセスが終了した場合などに発生する
        return None
    except Exception as e:
        logger.debug(f"アクティブウィンドウを取得できませんでした: {e}")
        return None


def get_idle_seconds() -> float:
    """最後のキーボード・マウス操作からの経過秒数を返す

    取得に失敗した場合は 0.0 を返し、無操作と誤判定しないようにする。
    """
    try:
        info = _LastInputInfo()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0

        get_tick_count = ctypes.windll.kernel32.GetTickCount
        get_tick_count.restype = ctypes.c_uint32
        # dwTime も GetTickCount も32bitで約49.7日で一周するため、
        # マスクを掛けて桁あふれ後も正しい差分を得る
        elapsed_ms = (get_tick_count() - info.dwTime) & 0xFFFFFFFF
        return elapsed_ms / 1000.0
    except Exception as e:
        logger.debug(f"無操作時間を取得できませんでした: {e}")
        return 0.0
