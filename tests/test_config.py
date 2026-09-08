"""
test_config.py - 設定の読み込みとアプリ名判定のテスト
"""

from __future__ import annotations

import json
import os

from app.config import DEFAULTS, load_config, save_config
from app.window import (
    choose_display_name,
    detect_browser_site,
    read_embedded_name,
    shorten_embedded_name,
)

SITE_RULES = DEFAULTS["apps"]["browser_site_rules"]


class TestLoadConfig:
    """設定の読み込み"""

    def test_missing_file_is_created_with_defaults(self, tmp_path):
        path = tmp_path / "config.json"

        config = load_config(str(path))

        assert path.exists()
        assert config.port == DEFAULTS["web"]["port"]
        assert config.load_errors == []

    def test_missing_file_can_skip_creation(self, tmp_path):
        path = tmp_path / "config.json"

        config = load_config(str(path), create_if_missing=False)

        assert not path.exists()
        assert config.poll_interval == DEFAULTS["tracker"]["poll_interval_seconds"]

    def test_user_values_override_defaults(self, tmp_path):
        path = tmp_path / "config.json"
        save_config({"web": {"port": 8080}}, str(path))

        config = load_config(str(path))

        # 指定した値は反映され、指定していない値は既定値のまま
        assert config.port == 8080
        assert config.host == DEFAULTS["web"]["host"]

    def test_nested_values_are_merged(self, tmp_path):
        path = tmp_path / "config.json"
        save_config({"tracker": {"idle_detection": {"enabled": True}}}, str(path))

        config = load_config(str(path))

        assert config.idle_detection_enabled is True
        assert config.idle_threshold_seconds == 300

    def test_utf8_bom_file_is_readable(self, tmp_path):
        # メモ帳やPowerShellはBOM付きUTF-8で保存することがある
        path = tmp_path / "config.json"
        path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"web": {"port": 8080}}).encode("utf-8"))

        config = load_config(str(path))

        assert config.port == 8080
        assert config.load_errors == []

    def test_broken_json_falls_back_to_defaults(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("{ broken", encoding="utf-8")

        config = load_config(str(path))

        assert config.port == DEFAULTS["web"]["port"]
        assert len(config.load_errors) == 1

    def test_invalid_value_type_falls_back_to_defaults(self, tmp_path):
        path = tmp_path / "config.json"
        save_config({"web": {"port": "ポート番号ではない"}}, str(path))

        config = load_config(str(path))

        assert config.port == DEFAULTS["web"]["port"]
        assert len(config.load_errors) == 1

    def test_poll_interval_has_lower_bound(self, tmp_path):
        path = tmp_path / "config.json"
        save_config({"tracker": {"poll_interval_seconds": 0}}, str(path))

        config = load_config(str(path))

        assert config.poll_interval == 1.0

    def test_flush_interval_is_never_shorter_than_poll(self, tmp_path):
        path = tmp_path / "config.json"
        save_config(
            {"tracker": {"poll_interval_seconds": 30, "flush_interval_seconds": 5}},
            str(path),
        )

        config = load_config(str(path))

        assert config.flush_interval == 30

    def test_saved_config_is_readable_utf8_json(self, tmp_path):
        path = tmp_path / "config.json"
        save_config(DEFAULTS, str(path))

        loaded = json.loads(path.read_text(encoding="utf-8"))

        assert loaded["apps"]["use_executable_name"] is True
        # 表示名の読み替えは app_names.json が担うため、config.json には対応表を置かない
        assert "name_map" not in loaded["apps"]


class TestDetectBrowserSite:
    """ブラウザのウィンドウタイトルからのサイト判定"""

    def test_exact_match_for_pwa_window(self):
        assert detect_browser_site("YouTube", SITE_RULES, "chrome.exe") == "YouTube"

    def test_exact_match_ignores_surrounding_spaces(self):
        assert detect_browser_site("  YouTube  ", SITE_RULES, "chrome.exe") == "YouTube"

    def test_partial_match_for_browser_tab(self):
        title = "サンプル動画 - YouTube - Google Chrome"

        assert detect_browser_site(title, SITE_RULES, "chrome.exe") == "YouTube"

    def test_x_is_detected_from_tab_title(self):
        assert detect_browser_site("ホーム / X", SITE_RULES, "chrome.exe") == "X (Twitter)"

    def test_single_character_pattern_does_not_partial_match(self):
        # "X" のような1文字の規則が無関係なタイトルへ誤って一致しないこと
        title = "Excel - 家計簿.xlsx - Google Chrome"

        assert detect_browser_site(title, SITE_RULES, "chrome.exe") == "chrome.exe"

    def test_unknown_site_falls_back_to_process_name(self):
        assert detect_browser_site("Google", SITE_RULES, "chrome.exe") == "chrome.exe"

    def test_empty_rules_return_fallback(self):
        assert detect_browser_site("YouTube", [], "chrome.exe") == "chrome.exe"


class TestChooseDisplayName:
    """表示名の決定（実行ファイルの埋め込み名 → プロセス名）"""

    def test_embedded_name_is_used(self):
        assert choose_display_name("r5apex_dx12.exe", "Apex Legends") == "Apex Legends"

    def test_falls_back_to_process_name(self):
        assert choose_display_name("unknown.exe", None) == "unknown.exe"

    def test_empty_embedded_name_is_ignored(self):
        assert choose_display_name("a.exe", "") == "a.exe"
        assert choose_display_name("a.exe", "   ") == "a.exe"

    def test_embedded_name_is_trimmed(self):
        assert choose_display_name("a.exe", "  Notion  ") == "Notion"


class TestShortenEmbeddedName:
    """冗長な名前の短縮"""

    def test_description_after_hyphen_is_dropped(self):
        assert shorten_embedded_name("Antigravity - Agentic Desktop Application") == "Antigravity"

    def test_plain_name_is_unchanged(self):
        assert shorten_embedded_name("Visual Studio Code") == "Visual Studio Code"

    def test_hyphen_without_spaces_is_kept(self):
        # 名前の一部としてのハイフンは残す
        assert shorten_embedded_name("Adobe Photoshop-CC") == "Adobe Photoshop-CC"

    def test_surrounding_spaces_are_trimmed(self):
        assert shorten_embedded_name("  Notion  ") == "Notion"


class TestReadEmbeddedName:
    """実行ファイルからの名前の取得"""

    def notepad_path(self):
        return os.path.join(os.environ["WINDIR"], "system32", "notepad.exe")

    def test_known_windows_executable(self):
        # Windows 標準の実行ファイルは必ず名前を持つ
        assert read_embedded_name(self.notepad_path())

    def test_microsoft_apps_do_not_collapse_into_one_name(self):
        """Microsoft製アプリが同じ名前にまとまらないこと

        ProductName はどれも "Microsoft(R) Windows(R) Operating System" になるため、
        FileDescription を優先していないと、メモ帳とエクスプローラーが同一視される。
        """
        notepad = read_embedded_name(self.notepad_path())
        explorer = read_embedded_name(os.path.join(os.environ["WINDIR"], "explorer.exe"))

        assert notepad and explorer
        assert notepad != explorer
        assert "Operating System" not in notepad

    def test_missing_file_returns_none(self):
        assert read_embedded_name(os.path.join("C:", "does", "not", "exist.exe")) is None

    def test_result_is_cached(self):
        path = self.notepad_path()
        first = read_embedded_name(path)

        # 2回目はキャッシュから返る（同じ値になる）
        assert read_embedded_name(path) == first
