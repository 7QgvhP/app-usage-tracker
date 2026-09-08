"""
display.py - モニターの構成と画面上の座標計算

接続されているモニターの列挙と、ウィンドウを配置する座標の算出を担当する。
Windows API への依存をこのモジュールに閉じ込め、座標計算の部分は
OSに依存せずテストできるようにしている（window.py と同じ方針）。

領域はいずれも (left, top, right, bottom) の組で表す。マルチモニター環境では
負の座標を取り得るため、0を下限として丸めてはいけない。
"""

from __future__ import annotations

import ctypes
import logging
from typing import NamedTuple

logger = logging.getLogger(__name__)

# 四隅の識別子と表示名
CORNERS = (
    ("top-left", "左上"),
    ("top-right", "右上"),
    ("bottom-left", "左下"),
    ("bottom-right", "右下"),
)


class _Rect(ctypes.Structure):
    """Windows API の RECT 構造体"""

    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _MonitorInfoEx(ctypes.Structure):
    """GetMonitorInfoW に渡す MONITORINFOEXW 構造体"""

    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", _Rect),
        ("rcWork", _Rect),
        ("dwFlags", ctypes.c_ulong),
        ("szDevice", ctypes.c_wchar * 32),
    ]


_MONITOR_ENUM_PROC = ctypes.WINFUNCTYPE(
    ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_Rect), ctypes.c_void_p
)


class Monitor(NamedTuple):
    """接続されているモニター1台分の情報

    bounds はモニター全体、work_area はタスクバーを除いた領域。
    """

    name: str
    primary: bool
    bounds: tuple[int, int, int, int]
    work_area: tuple[int, int, int, int]

    @property
    def width(self) -> int:
        return self.bounds[2] - self.bounds[0]

    @property
    def height(self) -> int:
        return self.bounds[3] - self.bounds[1]


# ── モニターの取得 ──


def get_primary_work_area(screen_width: int, screen_height: int) -> tuple[int, int, int, int]:
    """プライマリモニターの作業領域を返す（取得できない場合は画面全体）"""
    try:
        rect = _Rect()
        # SPI_GETWORKAREA = 0x0030
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right, rect.bottom
    except Exception as e:
        logger.debug(f"作業領域を取得できませんでした: {e}")
    return 0, 0, screen_width, screen_height


def get_monitors(screen_width: int = 0, screen_height: int = 0) -> list[Monitor]:
    """接続されている全モニターを返す（プライマリが先頭、以降は左からの順）

    SPI_GETWORKAREA はプライマリの作業領域しか返さないため、
    サブモニターへ配置するには列挙が必要になる。
    列挙に失敗した場合はプライマリ1台のみのリストを返す。
    """
    monitors: list[Monitor] = []

    def collect(handle, _hdc, _rect, _param):
        info = _MonitorInfoEx()
        info.cbSize = ctypes.sizeof(_MonitorInfoEx)
        if ctypes.windll.user32.GetMonitorInfoW(ctypes.c_void_p(handle), ctypes.byref(info)):
            monitors.append(
                Monitor(
                    name=info.szDevice,
                    # MONITORINFOF_PRIMARY = 0x1
                    primary=bool(info.dwFlags & 0x1),
                    bounds=(
                        info.rcMonitor.left,
                        info.rcMonitor.top,
                        info.rcMonitor.right,
                        info.rcMonitor.bottom,
                    ),
                    work_area=(
                        info.rcWork.left,
                        info.rcWork.top,
                        info.rcWork.right,
                        info.rcWork.bottom,
                    ),
                )
            )
        return True

    try:
        ctypes.windll.user32.EnumDisplayMonitors(None, None, _MONITOR_ENUM_PROC(collect), 0)
    except Exception as e:
        logger.debug(f"モニターを列挙できませんでした: {e}")

    if not monitors:
        area = get_primary_work_area(screen_width, screen_height)
        return [
            Monitor(
                name="",
                primary=True,
                bounds=(0, 0, screen_width, screen_height),
                work_area=area,
            )
        ]

    # プライマリを先頭にし、以降は左端の座標順に並べる
    monitors.sort(key=lambda m: (not m.primary, m.bounds[0]))
    return monitors


def virtual_bounds(monitors: list[Monitor]) -> tuple[int, int, int, int]:
    """全モニターを覆う仮想画面の範囲を返す"""
    return (
        min(m.bounds[0] for m in monitors),
        min(m.bounds[1] for m in monitors),
        max(m.bounds[2] for m in monitors),
        max(m.bounds[3] for m in monitors),
    )


def find_monitor(x: int, y: int, width: int, height: int, monitors: list[Monitor]) -> Monitor:
    """ウィンドウの中心が乗っているモニターを返す（該当なしはプライマリ）"""
    center_x = x + width // 2
    center_y = y + height // 2

    for monitor in monitors:
        left, top, right, bottom = monitor.bounds
        if left <= center_x < right and top <= center_y < bottom:
            return monitor

    return monitors[0]


def monitor_label(monitor: Monitor, index: int) -> str:
    """メニューに表示するモニター名"""
    position = "メイン" if monitor.primary else f"サブ{index}"
    return f"{position}（{monitor.width}×{monitor.height}）"


# ── 座標の計算 ──


def corner_position(
    corner: str, width: int, height: int, area: tuple[int, int, int, int], margin: int
) -> tuple[int, int]:
    """指定した隅に余白を空けて配置する場合の座標を返す

    Args:
        corner: top-left / top-right / bottom-left / bottom-right
        area: 配置対象の領域 (left, top, right, bottom)
        margin: 画面の縁から空ける余白（画素）
    """
    left, top, right, bottom = area

    if corner.endswith("left"):
        x = left + margin
    else:
        x = right - width - margin

    if corner.startswith("top"):
        y = top + margin
    else:
        y = bottom - height - margin

    return int(x), int(y)


def clamp_to_area(
    x: int, y: int, width: int, height: int, area: tuple[int, int, int, int]
) -> tuple[int, int]:
    """ウィンドウが指定領域からはみ出さないよう表示位置を補正する

    マルチモニター環境では領域の原点が負になり得るため、0で丸めてはいけない。
    モニタ構成が変わった後でもウィンドウを見失わないようにする。
    """
    left, top, right, bottom = area
    max_x = max(left, right - width)
    max_y = max(top, bottom - height)
    return min(max(left, x), max_x), min(max(top, y), max_y)
