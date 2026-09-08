"""
naming.py - アプリ名の照合と対応表

PCとスマホでは同じアプリでも記録される名前が違う（chrome.exe と Chrome など）。
表示名をそのまま同一性の判断に使うと別のアプリとして数えてしまうため、
照合専用のキーを計算して束ねる。

対応表は data/app_names.json に保存し、利用者が閲覧・編集できるようにする。
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# 照合時に落とす実行ファイルの拡張子
_EXTENSION = re.compile(r"\.(exe|app)$", re.IGNORECASE)
# 末尾の括弧書き（"X (Twitter)" の "(Twitter)" など）
_TRAILING_PARENS = re.compile(r"\s*[（(][^）)]*[）)]\s*$")
# キーに残す文字（英数字・ひらがな・カタカナ・漢字）
_KEEP = re.compile(r"[^0-9a-z぀-ヿ一-鿿]")

README = (
    "アプリ名の対応表です。同じアプリがPCとスマホで別の名前で記録されるため、"
    "照合用のキーで束ねています。編集方法は README.md の"
    "「アプリ名の対応表」を参照してください。"
)


def normalize_key(name: str) -> str:
    """照合用のキーを作る

    表記の揺れ（大文字小文字・拡張子・括弧書き・記号）を落として比較できる形にする。
    例: "chrome.exe" と "Chrome" はどちらも "chrome" になる。
    """
    text = unicodedata.normalize("NFKC", name).strip()
    text = _EXTENSION.sub("", text)
    text = _TRAILING_PARENS.sub("", text)
    key = _KEEP.sub("", text.lower())
    # 記号だけの名前でキーが空になる場合は、元の名前で区別する
    return key or text.lower()


def prefer_display_name(names: Iterable[str]) -> str:
    """観測された表記のうち、画面に出すものを選ぶ

    実行ファイル名は避け、情報量の多いものを優先する。
    例: {"chrome.exe", "Chrome"} → "Chrome"
        {"X", "X (Twitter)"}     → "X (Twitter)"
    """
    candidates = sorted({n for n in names if n and n.strip()})
    if not candidates:
        return ""

    # 実行ファイル名でないもの → 文字数の多いもの → 辞書順、の順で選ぶ
    return min(
        candidates,
        key=lambda n: (1 if _EXTENSION.search(n) else 0, -len(n), n),
    )


class AppNameRegistry:
    """アプリ名の対応表

    記録のたびに観測した名前を控え、同じキーのものを1つの表示名へまとめる。
    利用者が編集した項目（source が manual）は上書きしない。
    """

    def __init__(self, path: str):
        self.path = path
        # キー → {"display": str, "source": str, "names": {端末: [名前, ...]}}
        self._apps: dict[str, dict[str, Any]] = {}
        # 記録された名前 → キー（自動では結び付かないものを手動で結ぶ）
        self._aliases: dict[str, str] = {}
        self._dirty = False

    # ── 読み書き ──

    def load(self) -> None:
        """対応表を読み込む（無ければ空のまま始める）"""
        if not os.path.exists(self.path):
            return

        try:
            with open(self.path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"アプリ名の対応表を読み込めませんでした（空から始めます）: {e}")
            return

        if not isinstance(data, dict):
            logger.warning(f"アプリ名の対応表の形式が不正です: {self.path}")
            return

        apps = data.get("apps")
        if isinstance(apps, dict):
            for key, entry in apps.items():
                if isinstance(entry, dict):
                    self._apps[key] = {
                        "display": str(entry.get("display", "")),
                        "source": str(entry.get("source", "auto")),
                        "names": {
                            device: sorted(set(names))
                            for device, names in (entry.get("names") or {}).items()
                            if isinstance(names, list)
                        },
                    }

        aliases = data.get("aliases")
        if isinstance(aliases, dict):
            self._aliases = {str(k): str(v) for k, v in aliases.items()}

        self._prune()
        logger.info(f"アプリ名の対応表を読み込みました: {len(self._apps)}件")

    def _prune(self) -> None:
        """別のキーへ移った名前を、古い項目から取り除く

        aliases を編集して束ね方を変えたとき、元の項目に名前が残ったままだと
        対応表を読み違えるため。
        """
        for key, entry in list(self._apps.items()):
            for device, names in list(entry["names"].items()):
                kept = [n for n in names if self.key_for(n) == key]
                if kept != names:
                    entry["names"][device] = kept
                    self._dirty = True
                if not kept:
                    del entry["names"][device]

            # 名前が1つも残らなかった項目は不要
            if not entry["names"]:
                del self._apps[key]
                self._dirty = True

    def save(self, force: bool = False) -> None:
        """変更があれば書き出す"""
        if not self._dirty and not force:
            return

        payload = {
            "_readme": README,
            "aliases": dict(sorted(self._aliases.items())),
            "apps": {
                key: {**self._apps[key], "judgement": self._judgement(key)}
                for key in sorted(self._apps, key=lambda k: self._apps[k]["display"].lower())
            },
        }

        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.write("\n")
            self._dirty = False
        except OSError as e:
            logger.error(f"アプリ名の対応表を書き出せませんでした: {e}")

    def _judgement(self, key: str) -> str:
        """どうやって束ねたかを表す

        auto   規則で複数の表記が一致した
        manual 利用者が指定した（display を変えた／aliases で結んだ）
        single 表記が1つだけで、照合していない
        """
        entry = self._apps[key]
        names = {n for device_names in entry["names"].values() for n in device_names}

        if entry.get("source") == "manual" or key in self._aliases.values():
            return "manual"
        return "auto" if len(names) > 1 else "single"

    # ── 照合 ──

    def key_for(self, name: str) -> str:
        """記録された名前から照合キーを求める

        手動の対応（aliases）を最優先し、無ければ規則で計算する。
        """
        if name in self._aliases:
            return self._aliases[name]
        return normalize_key(name)

    def register(self, name: str, device: str) -> str:
        """観測した名前を控え、画面に出す表示名を返す"""
        key = self.key_for(name)
        entry = self._apps.get(key)

        if entry is None:
            entry = {"display": name, "source": "auto", "names": {}}
            self._apps[key] = entry
            self._dirty = True

        names = entry["names"].setdefault(device, [])
        if name not in names:
            names.append(name)
            names.sort()
            self._dirty = True

        # 利用者が決めた表示名は尊重する
        if entry["source"] != "manual":
            preferred = prefer_display_name(
                [n for device_names in entry["names"].values() for n in device_names]
            )
            if preferred and preferred != entry["display"]:
                entry["display"] = preferred
                self._dirty = True

        return entry["display"]

    def display_for(self, key: str, observed: Iterable[str] | None = None) -> str:
        """キーに対応する表示名を返す

        対応表に無いキー（移行直後など）は、記録されている表記から選ぶ。
        キーは照合用の値なので、そのまま画面に出さない。
        """
        entry = self._apps.get(key)
        if entry:
            return entry["display"]
        return prefer_display_name(observed or []) or key
