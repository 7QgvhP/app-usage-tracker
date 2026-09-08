"""
test_mini_window.py - 小型ウィンドウの表示ロジックのテスト

tkinter の描画自体は対象とせず、表示値の計算・整形と表示制御を検証する。
モニターと座標計算は test_display.py が担当する。
"""

from __future__ import annotations

import json

import pytest

from app.mini_window import (
    MiniWindow,
    MiniWindowController,
    display_name,
    format_duration,
    format_minutes,
    load_window_position,
    save_window_position,
    usage_ratio,
)
from tests.duration_cases import DURATION_CASES, MINUTES_CASES


class TestFormatDuration:
    """秒数の表記（画面・スマホと同じ規則）"""

    @pytest.mark.parametrize("seconds,expected", DURATION_CASES)
    def test_共通の仕様どおりに整形する(self, seconds, expected):
        assert format_duration(seconds) == expected

    def test_負の値は0として扱う(self):
        assert format_duration(-10) == "0分"


class TestFormatMinutes:
    """分の表記（制限時間やグラフの目盛り）"""

    @pytest.mark.parametrize("minutes,expected", MINUTES_CASES)
    def test_共通の仕様どおりに整形する(self, minutes, expected):
        assert format_minutes(minutes) == expected

    def test_負の値は0として扱う(self):
        assert format_minutes(-10) == "0分"


class TestDisplayName:
    """表示名の整形"""

    def test_exe_extension_is_removed(self):
        assert display_name("chrome.exe") == "chrome"

    def test_uppercase_extension_is_removed(self):
        assert display_name("Chrome.EXE") == "Chrome"

    def test_name_without_extension_is_kept(self):
        assert display_name("YouTube") == "YouTube"

    def test_japanese_name_is_kept(self):
        assert display_name("鳴潮") == "鳴潮"

    def test_long_name_is_truncated(self):
        result = display_name("VeryLongApplicationName.exe")

        assert result.endswith("…")
        assert len(result) == 19

    def test_none_shows_placeholder(self):
        assert display_name(None) == "計測対象外"


class TestUsageRatio:
    """制限時間に対する使用率"""

    def test_no_limit_returns_zero(self):
        assert usage_ratio(3600, None) == 0.0

    def test_zero_limit_returns_zero(self):
        assert usage_ratio(3600, 0) == 0.0

    def test_half_way(self):
        assert usage_ratio(1800, 60) == 0.5

    def test_exactly_at_limit(self):
        assert usage_ratio(3600, 60) == 1.0

    def test_over_limit_is_capped(self):
        # 超過してもバーがはみ出さないよう1.0で頭打ちにする
        assert usage_ratio(7200, 60) == 1.0

    def test_negative_seconds_is_zero(self):
        assert usage_ratio(-10, 60) == 0.0


def usage(app="chrome.exe", seconds=0, paused=False, idle=False, total=0, limit=None):
    """トラッカーが返す状態を模したデータ"""
    return {
        "app": app,
        "seconds": seconds,
        "total_seconds": total,
        "limit_minutes": limit,
        "paused": paused,
        "idle": idle,
    }


class TestResolveSeconds:
    """表示秒数の算出（走査間隔より細かく進める補間処理）"""

    @pytest.fixture
    def window(self, config, monkeypatch):
        """時刻を固定した状態のウィンドウ"""
        clock = {"now": 1000.0}
        monkeypatch.setattr("app.mini_window.time.monotonic", lambda: clock["now"])
        mini = MiniWindow(tracker=None, config=config)
        mini.clock = clock
        return mini

    def test_first_value_is_used_as_is(self, window):
        assert window._resolve_seconds(usage(seconds=100)) == 100

    def test_seconds_advance_between_updates(self, window):
        window._resolve_seconds(usage(seconds=100))

        window.clock["now"] += 3.0

        # トラッカーの値が変わらなくても表示は進む
        assert window._resolve_seconds(usage(seconds=100)) == pytest.approx(103.0)

    def test_snaps_forward_when_tracker_is_ahead(self, window):
        window._resolve_seconds(usage(seconds=100))
        window.clock["now"] += 1.0

        assert window._resolve_seconds(usage(seconds=110)) == 110

    def test_display_never_goes_backwards(self, window):
        window._resolve_seconds(usage(seconds=100))
        window.clock["now"] += 4.0

        # 取得値が補間値より小さくても巻き戻さない
        assert window._resolve_seconds(usage(seconds=100)) == pytest.approx(104.0)

    def test_app_switch_resets_to_tracker_value(self, window):
        window._resolve_seconds(usage(app="chrome.exe", seconds=100))
        window.clock["now"] += 5.0

        assert window._resolve_seconds(usage(app="code.exe", seconds=20)) == 20

    def test_paused_does_not_advance(self, window):
        window._resolve_seconds(usage(seconds=100, paused=True))
        window.clock["now"] += 10.0

        assert window._resolve_seconds(usage(seconds=100, paused=True)) == 100

    def test_idle_does_not_advance(self, window):
        window._resolve_seconds(usage(seconds=100, idle=True))
        window.clock["now"] += 10.0

        assert window._resolve_seconds(usage(seconds=100, idle=True)) == 100

    def test_no_active_app_shows_zero(self, window):
        assert window._resolve_seconds(usage(app=None, seconds=0)) == 0

    def test_advances_again_after_resume(self, window):
        window._resolve_seconds(usage(seconds=100, paused=True))
        window.clock["now"] += 5.0
        window._resolve_seconds(usage(seconds=100))

        window.clock["now"] += 2.0

        assert window._resolve_seconds(usage(seconds=100)) == pytest.approx(102.0)

    def test_resume_does_not_jump_by_paused_duration(self, window):
        # 停止中の経過時間が復帰時にまとめて加算されないこと
        window._resolve_seconds(usage(seconds=100))
        window.clock["now"] += 1.0
        window._resolve_seconds(usage(seconds=100, paused=True))

        window.clock["now"] += 3600.0

        assert window._resolve_seconds(usage(seconds=100)) == 100

    def test_return_from_idle_does_not_jump(self, window):
        # 離席は長時間になりやすく、影響が大きい
        window._resolve_seconds(usage(seconds=100))
        window.clock["now"] += 1.0
        window._resolve_seconds(usage(seconds=100, idle=True))

        window.clock["now"] += 7200.0

        assert window._resolve_seconds(usage(seconds=100)) == 100


class FakeRoot:
    """mainloop の呼び出しを記録するだけのウィンドウ"""

    def __init__(self):
        self.mainloop_called = False

    def mainloop(self):
        self.mainloop_called = True


class TestRun:
    """表示開始の処理"""

    def test_enters_mainloop_normally(self, config, monkeypatch):
        window = MiniWindow(tracker=None, config=config)
        root = FakeRoot()
        monkeypatch.setattr(MiniWindow, "_build", lambda self: setattr(self, "_root", root))
        monkeypatch.setattr(MiniWindow, "_update", lambda self: None)

        window.run()

        assert root.mainloop_called is True

    def test_returns_without_mainloop_when_already_shutdown(self, config, monkeypatch):
        # 起動直後に終了が要求されると、初回更新でウィンドウが破棄される
        window = MiniWindow(tracker=None, config=config)
        root = FakeRoot()
        monkeypatch.setattr(MiniWindow, "_build", lambda self: setattr(self, "_root", root))
        monkeypatch.setattr(MiniWindow, "_update", lambda self: setattr(self, "_root", None))

        window.run()

        assert root.mainloop_called is False


class TestMiniWindowController:
    """再表示要求の仲介"""

    def test_no_request_initially(self):
        assert MiniWindowController().wait_for_request(0.01) is False

    def test_request_is_received(self):
        controller = MiniWindowController()

        controller.request_show()

        assert controller.wait_for_request(0.01) is True

    def test_consumed_request_is_cleared(self):
        controller = MiniWindowController()
        controller.request_show()

        controller.consume_request()

        assert controller.wait_for_request(0.01) is False

    def test_visibility_is_tracked(self):
        controller = MiniWindowController()
        assert controller.visible is False

        controller.set_visible(True)
        assert controller.visible is True

        controller.set_visible(False)
        assert controller.visible is False

    def test_request_during_display_is_discarded(self):
        # 表示中に届いた要求で、閉じた直後に再表示されてしまわないこと
        controller = MiniWindowController()
        controller.set_visible(True)
        controller.request_show()

        controller.set_visible(False)
        controller.consume_request()

        assert controller.wait_for_request(0.01) is False


class TestWindowPosition:
    """表示位置の保存と復元"""

    def test_save_and_load(self, tmp_path):
        path = str(tmp_path / "state" / "window_state.json")

        save_window_position(path, 300, 150)

        assert load_window_position(path) == (300, 150)

    def test_missing_file_returns_none(self, tmp_path):
        assert load_window_position(str(tmp_path / "missing.json")) is None

    def test_broken_file_returns_none(self, tmp_path):
        path = tmp_path / "window_state.json"
        path.write_text("{ broken", encoding="utf-8")

        assert load_window_position(str(path)) is None

    def test_incomplete_file_returns_none(self, tmp_path):
        path = tmp_path / "window_state.json"
        path.write_text(json.dumps({"x": 10}), encoding="utf-8")

        assert load_window_position(str(path)) is None
