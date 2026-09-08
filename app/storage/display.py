"""
display.py - 照合キーと表示名の橋渡し

記録されたアプリ名は揺れる（PCは `chrome.exe`、スマホは `Chrome` など）。
**同一性は照合キー（app_key）で決め、表示名は見せる直前に決める**という規則を
ここへ集約している。store.py は命名の知識を持たない。

対応表（AppNameRegistry）を渡さずに使うこともできる。その場合は
app/naming.py の規則だけで照合し、観測された表記から表示名を選ぶ。
"""

from __future__ import annotations

from app.naming import normalize_key, prefer_display_name


class DisplayNames:
    """記録された名前と、画面に出す名前の対応を解決する"""

    def __init__(self, registry=None):
        """
        Args:
            registry: アプリ名の対応表（AppNameRegistry）。省略時は規則だけで照合する
        """
        self._registry = registry

    # ── 書き込み時（記録された名前 → キー）──

    def key_for(self, app_name: str, device: str | None = None) -> str:
        """記録された名前から照合キーを求める

        device を渡した場合は「この端末でこの名前が観測された」ことを
        対応表へ控える（data/app_names.json に残る）。
        """
        if self._registry is None:
            return normalize_key(app_name)

        if device is not None:
            self._registry.register(app_name, device)
        return self._registry.key_for(app_name)

    def register(self, app_name: str, device: str) -> None:
        """観測された表記を対応表へ控える"""
        if self._registry is not None:
            self._registry.register(app_name, device)

    def save(self) -> None:
        """対応表に変更があれば書き出す"""
        if self._registry is not None:
            self._registry.save()

    @property
    def has_registry(self) -> bool:
        """対応表を持っているか"""
        return self._registry is not None

    # ── 読み取り時（キー → 表示名）──

    def resolve(self, key: str, observed: list[str]) -> str:
        """キーに対応する表示名を決める

        対応表があればそれに従い、無ければ観測された表記から選ぶ。
        """
        if self._registry is not None:
            return self._registry.display_for(key, observed)
        return prefer_display_name(observed) or key

    @staticmethod
    def observed_names(rows: list) -> dict[str, list[str]]:
        """行の集まりから「照合キー → 観測された表記」を組み立てる

        表示名を決めるには、そのキーで観測された表記を全て渡す必要がある。
        """
        observed: dict[str, list[str]] = {}
        for row in rows:
            observed.setdefault(row["app_key"], []).append(row["app_name"])
        return observed

    def map_for(self, rows: list) -> dict[str, str]:
        """行の集まりから「照合キー → 表示名」を求める"""
        return {
            key: self.resolve(key, names)
            for key, names in self.observed_names(rows).items()
        }

    def rename_rows(self, rows: list) -> list[dict]:
        """行の app_name を、照合キーに対応する表示名へ差し替える"""
        display = self.map_for(rows)

        result = []
        for row in rows:
            item = dict(row)
            item["app_name"] = display[row["app_key"]]
            result.append(item)
        return result

    def fold(self, rows: list) -> dict[str, int]:
        """(app_key, app_name, seconds) の行を「表示名 → 秒数」へ束ねる"""
        display = self.map_for(rows)

        result: dict[str, int] = {}
        for row in rows:
            name = display[row["app_key"]]
            result[name] = result.get(name, 0) + row["seconds"]
        return result
