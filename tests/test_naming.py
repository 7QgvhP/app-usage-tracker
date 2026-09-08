"""
test_naming.py - アプリ名の照合と対応表のテスト

PCとスマホで名前が違う同じアプリを束ねられるか、
束ね方を変えたときに過去の記録へ反映されるかを確認する。
"""

from __future__ import annotations

import json

import pytest

from app.naming import AppNameRegistry, normalize_key, prefer_display_name
from app.storage import UsageStore


class TestNormalizeKey:
    """照合キーの計算"""

    def test_拡張子を落とす(self):
        assert normalize_key("chrome.exe") == normalize_key("Chrome")
        assert normalize_key("Notion.exe") == normalize_key("Notion")

    def test_大文字小文字を区別しない(self):
        # 同じアプリが表記違いで別々に数えられていた実例
        assert normalize_key("minecraft.exe") == normalize_key("Minecraft.exe")

    def test_末尾の括弧書きを落とす(self):
        # PC側は "X (Twitter)"、スマホ側は "X" と記録される
        assert normalize_key("X (Twitter)") == normalize_key("X")
        assert normalize_key("メモ帳（旧）") == normalize_key("メモ帳")

    def test_記号と空白を無視する(self):
        assert normalize_key("Visual Studio Code") == normalize_key("VisualStudioCode")

    def test_日本語のアプリ名も扱える(self):
        assert normalize_key("鳴潮") == "鳴潮"
        assert normalize_key("クラクラ") == "クラクラ"

    def test_別のアプリは束ねない(self):
        # 名前が似ていても実体が違うものは分けたままにする
        assert normalize_key("YouTube Music") != normalize_key("YouTube")
        assert normalize_key("Notion Setup 7.30.0.exe") != normalize_key("Notion")

    def test_記号だけの名前でも空にならない(self):
        assert normalize_key("+++") != ""


class TestPreferDisplayName:
    """表示名の選択"""

    def test_実行ファイル名より読みやすい名前を選ぶ(self):
        assert prefer_display_name({"chrome.exe", "Chrome"}) == "Chrome"
        assert prefer_display_name({"claude.exe", "Claude"}) == "Claude"

    def test_情報量の多い名前を選ぶ(self):
        assert prefer_display_name({"X", "X (Twitter)"}) == "X (Twitter)"

    def test_実行ファイル名しかなければそれを使う(self):
        assert prefer_display_name({"minecraft.exe", "Minecraft.exe"}) == "Minecraft.exe"

    def test_空なら空文字(self):
        assert prefer_display_name([]) == ""
        assert prefer_display_name(["", "  "]) == ""


@pytest.fixture
def registry(tmp_path):
    return AppNameRegistry(str(tmp_path / "data" / "app_names.json"))


class TestRegistry:
    """対応表の記録と保存"""

    def test_端末ごとに観測した名前を控える(self, registry):
        registry.register("chrome.exe", "pc")
        display = registry.register("Chrome", "android")

        assert display == "Chrome"
        assert registry.key_for("chrome.exe") == registry.key_for("Chrome")

    def test_読みやすい名前が後から来ても採用する(self, registry):
        assert registry.register("claude.exe", "pc") == "claude.exe"
        # 実行ファイルの情報から解決した名前が届いた時点で置き換わる
        assert registry.register("Claude", "pc") == "Claude"

    def test_利用者が決めた表示名は上書きしない(self, registry, tmp_path):
        registry.register("chrome.exe", "pc")
        registry.save()

        # 表示名を書き換え、manual として保存する
        path = tmp_path / "data" / "app_names.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        key = registry.key_for("chrome.exe")
        data["apps"][key]["display"] = "グーグルクローム"
        data["apps"][key]["source"] = "manual"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        reloaded = AppNameRegistry(str(path))
        reloaded.load()
        assert reloaded.register("Chrome", "android") == "グーグルクローム"

    def test_aliasesで手動の統合ができる(self, registry, tmp_path):
        registry.register("LINE", "android")
        registry.save()

        path = tmp_path / "data" / "app_names.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["aliases"] = {"LineLauncher.exe": "line"}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        reloaded = AppNameRegistry(str(path))
        reloaded.load()
        assert reloaded.key_for("LineLauncher.exe") == "line"

    def test_aliasesで分離できる(self, registry, tmp_path):
        # 自動で束ねられたものを、別のキーへ移して分ける（README記載の手順）
        registry.register("chrome.exe", "pc")
        registry.register("Chrome", "android")
        registry.save()

        path = tmp_path / "data" / "app_names.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data["apps"]) == 1

        data["aliases"] = {"Chrome": "chrome-mobile"}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        reloaded = AppNameRegistry(str(path))
        reloaded.load()
        reloaded.register("chrome.exe", "pc")
        reloaded.register("Chrome", "android")
        reloaded.save(force=True)

        data = json.loads(path.read_text(encoding="utf-8"))
        assert set(data["apps"]) == {"chrome", "chrome-mobile"}
        # 移った名前は元の項目に残らない
        assert data["apps"]["chrome"]["names"] == {"pc": ["chrome.exe"]}
        assert data["apps"]["chrome-mobile"]["judgement"] == "manual"

    def test_判定が書き出される(self, registry, tmp_path):
        registry.register("chrome.exe", "pc")
        registry.register("Chrome", "android")
        registry.register("クラクラ", "android")
        registry.save()

        data = json.loads((tmp_path / "data" / "app_names.json").read_text(encoding="utf-8"))
        assert data["apps"][registry.key_for("chrome.exe")]["judgement"] == "auto"
        assert data["apps"][registry.key_for("クラクラ")]["judgement"] == "single"

    def test_変更が無ければ書き込まない(self, registry, tmp_path):
        path = tmp_path / "data" / "app_names.json"
        registry.register("chrome.exe", "pc")
        registry.save()
        before = path.stat().st_mtime_ns

        registry.save()
        assert path.stat().st_mtime_ns == before

    def test_壊れたファイルでも起動できる(self, tmp_path):
        path = tmp_path / "app_names.json"
        path.write_text("{ 壊れています", encoding="utf-8")

        broken = AppNameRegistry(str(path))
        broken.load()
        assert broken.register("chrome.exe", "pc") == "chrome.exe"


class TestStoreIntegration:
    """データストアとの組み合わせ"""

    @pytest.fixture
    def store(self, tmp_path, registry):
        # 対応表は registry フィクスチャと同じものを共有する
        # （テストから直接編集できるようにするため）
        usage_store = UsageStore(str(tmp_path / "data" / "test.db"), registry)
        yield usage_store
        usage_store.close()

    def test_端末をまたいで同じアプリが合算される(self, store):
        store.add_usage("chrome.exe", 600, "2026-08-24", device="pc")
        store.add_usage("Chrome", 300, "2026-08-24", device="android")

        # 実行ファイル名でないほうが表示名として選ばれる
        assert store.get_usage_by_range("2026-08-24", "2026-08-24", device=None) == {
            "Chrome": 900
        }

    def test_PC内の表記ゆれもまとまる(self, store):
        # 実行ファイルの情報を使う前後で名前が変わった場合
        store.add_usage("Notion.exe", 600, "2026-08-24")
        store.add_usage("Notion", 300, "2026-08-24")

        assert store.get_usage_by_range("2026-08-24", "2026-08-24") == {"Notion": 900}

    def test_別のアプリは合算されない(self, store):
        store.add_usage("YouTube", 600, "2026-08-24")
        store.add_usage("YouTube Music", 300, "2026-08-24")

        result = store.get_usage_by_range("2026-08-24", "2026-08-24")
        assert result == {"YouTube": 600, "YouTube Music": 300}

    def test_端末別の内訳も表示名でまとまる(self, store):
        store.add_usage("chrome.exe", 600, "2026-08-24", device="pc")
        store.add_usage("Chrome", 300, "2026-08-24", device="android")

        rows = store.get_usage_by_device("2026-08-24", "2026-08-24")
        assert {(r["app_name"], r["device"]): r["seconds"] for r in rows} == {
            ("Chrome", "pc"): 600,
            ("Chrome", "android"): 300,
        }

    def test_区間も表示名で返る(self, store):
        store.add_session("chrome.exe", "2026-08-24 09:00:00", "2026-08-24 09:10:00", 600)
        store.add_usage("Chrome", 1, "2026-08-24", device="android")

        sessions = store.get_sessions("2026-08-24")
        assert sessions[0]["app_name"] == "Chrome"

    def test_束ね方を変えると過去の記録へ反映される(self, store, registry, tmp_path):
        store.add_usage("LINE", 600, "2026-08-24")
        store.add_usage("LineLauncher.exe", 300, "2026-08-24")
        # 規則だけでは別扱いのまま
        assert len(store.get_usage_by_range("2026-08-24", "2026-08-24")) == 2

        # 対応表へ手動の統合を足して読み直す
        path = tmp_path / "data" / "app_names.json"
        registry.save(force=True)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["aliases"] = {"LineLauncher.exe": "line"}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        registry.load()

        assert store.renormalize() > 0
        assert store.get_usage_by_range("2026-08-24", "2026-08-24") == {"LINE": 900}

    def test_対応表に無いキーでもキーを画面に出さない(self, store, registry):
        # 移行直後は対応表が空になる。このとき "chrome" のような
        # 照合用の値をそのまま表示してしまわないことを確かめる
        store.add_usage("chrome.exe", 600, "2026-08-24")
        registry._apps.clear()

        assert store.get_usage_by_range("2026-08-24", "2026-08-24") == {"chrome.exe": 600}

    def test_記録済みの名前を対応表へ取り込める(self, store, registry):
        store.add_usage("chrome.exe", 600, "2026-08-24", device="pc")
        store.add_usage("Chrome", 300, "2026-08-24", device="android")
        registry._apps.clear()

        assert store.register_existing() > 0
        # 取り込み後は読みやすい名前が選ばれる
        assert store.get_usage_by_range("2026-08-24", "2026-08-24", device=None) == {
            "Chrome": 900
        }

    def test_変更が無ければ再計算しない(self, store):
        store.add_usage("chrome.exe", 600, "2026-08-24")
        assert store.renormalize() == 0

    def test_対応表なしでも束ねられる(self, tmp_path):
        # 対応表を渡さない場合も、規則による照合だけは働く
        plain = UsageStore(str(tmp_path / "data" / "plain.db"))
        plain.add_usage("chrome.exe", 600, "2026-08-24")
        plain.add_usage("Chrome", 300, "2026-08-24")

        # 合算はされる。ただし表示名は最初に記録された表記のまま
        # （どの表記を観測したかを覚える場所が無いため）
        assert plain.get_usage_by_range("2026-08-24", "2026-08-24") == {"chrome.exe": 900}
        plain.close()
