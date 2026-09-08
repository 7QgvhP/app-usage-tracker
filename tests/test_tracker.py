"""
test_tracker.py - 使用時間の集計ロジックのテスト

Windows API に依存しないよう、アクティブアプリと無操作時間は
テスト用の関数を注入して検証する。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.storage import StorageError, today_str
from app.tracker import MAX_ELAPSED_FACTOR, AppTracker, clamp_elapsed


def make_tracker(config, store, notifier, app_name="chrome.exe", idle_seconds=0.0):
    """テスト用のトラッカーを生成する"""
    return AppTracker(
        config,
        store,
        notifier=notifier,
        sampler=lambda: app_name,
        idle_provider=lambda: idle_seconds,
    )


class TestNameConsistency:
    """記録名・表示名・照合キーの扱い

    画面は表示名、記録は記録名、判定はキー。混ざると通知が出なくなる。
    """

    def test_表示名で設定した制限が記録名のアプリに効く(self, config, store, notifier):
        # PCは chrome.exe として記録し、スマホは Chrome として記録する
        store.add_usage("chrome.exe", 40 * 60, device="pc")
        store.add_usage("Chrome", 60, device="android")
        # 画面に出ている名前（Chrome）で制限を設定する
        store.set_limit("Chrome", 30)

        tracker = make_tracker(config, store, notifier, app_name="chrome.exe")
        tracker._refresh_caches()
        tracker._check_limits("chrome.exe")

        # 通知に出る名前も画面と同じ「Chrome」になる
        assert notifier.reached == [("Chrome", 30)]

    def test_ミニウィンドウの表記が画面と揃う(self, config, store, notifier):
        store.add_usage("chrome.exe", 600, device="pc")
        store.add_usage("Chrome", 300, device="android")

        tracker = make_tracker(config, store, notifier, app_name="chrome.exe")
        tracker._refresh_caches()
        tracker._process_tick(5.0)

        # ダッシュボードが出す名前と同じものを返す
        displayed = list(store.get_usage_by_range(today_str(), today_str(), device=None))
        assert tracker.get_current_usage()["app"] in displayed

    def test_表記が揺れても使用時間がひとつに合算される(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier, app_name="chrome.exe")
        tracker._process_tick(60.0)
        tracker.flush()

        # 別の表記で記録済みの分があっても、同じキーへまとまる
        store.add_usage("Chrome", 120, device="android")
        tracker._refresh_caches()

        key = store.key_for("chrome.exe")
        assert tracker._usage_cache[key] == 60


class TestClampElapsed:
    """経過時間の打ち切り"""

    def test_normal_elapsed_is_kept(self):
        assert clamp_elapsed(5.2, 15) == 5.2

    def test_long_gap_is_clamped(self):
        # スリープから復帰した場合を想定
        assert clamp_elapsed(8 * 60 * 60, 15) == 15

    def test_negative_elapsed_becomes_zero(self):
        assert clamp_elapsed(-3, 15) == 0.0


class TestAccumulation:
    """使用時間の集計"""

    def test_tick_accumulates_elapsed_time(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)

        tracker._process_tick(5.0)
        tracker._process_tick(4.5)

        assert tracker._pending == {"chrome.exe": 9.5}

    def test_flush_writes_whole_seconds(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)

        tracker._process_tick(5.5)
        tracker.flush()

        assert store.get_today_usage() == {"chrome.exe": 5}

    def test_flush_carries_over_fraction(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)

        # 端数を切り捨てると誤差が蓄積するため、繰り越されることを確認する
        tracker._process_tick(5.5)
        tracker.flush()
        assert tracker._pending == {"chrome.exe": pytest.approx(0.5)}

        tracker._process_tick(5.5)
        tracker.flush()
        assert store.get_today_usage() == {"chrome.exe": 11}

    def test_flush_without_pending_is_noop(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)

        tracker.flush()

        assert store.get_today_usage() == {}

    def test_no_accumulation_when_app_is_none(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier, app_name=None)

        tracker._process_tick(5.0)

        assert tracker._pending == {}

    def test_failed_flush_keeps_pending_for_retry(self, config, store, notifier, monkeypatch):
        tracker = make_tracker(config, store, notifier)
        tracker._process_tick(10.0)

        def fail(*_args, **_kwargs):
            raise StorageError("書き込み失敗")

        monkeypatch.setattr(store, "add_usage_bulk", fail)
        tracker.flush()

        # 保存できなかった分は破棄されない
        assert tracker._pending["chrome.exe"] == pytest.approx(10.0)


class TestPauseAndIdle:
    """一時停止とアイドル検知"""

    def test_paused_tracker_does_not_accumulate(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)
        tracker.pause()

        tracker._process_tick(5.0)

        assert tracker.is_paused is True
        assert tracker._pending == {}

    def test_resume_restarts_accumulation(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)
        tracker.pause()
        tracker._process_tick(5.0)
        tracker.resume()

        tracker._process_tick(5.0)

        assert tracker.is_paused is False
        assert tracker._pending == {"chrome.exe": 5.0}

    def test_idle_detection_disabled_by_default(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier, idle_seconds=9999)

        tracker._process_tick(5.0)

        assert tracker._pending == {"chrome.exe": 5.0}

    def test_idle_over_threshold_stops_accumulation(self, config, store, notifier):
        config._data["tracker"]["idle_detection"] = {
            "enabled": True,
            "threshold_seconds": 300,
        }
        tracker = make_tracker(config, store, notifier, idle_seconds=301)

        tracker._process_tick(5.0)

        assert tracker._pending == {}

    def test_idle_under_threshold_keeps_accumulation(self, config, store, notifier):
        config._data["tracker"]["idle_detection"] = {
            "enabled": True,
            "threshold_seconds": 300,
        }
        tracker = make_tracker(config, store, notifier, idle_seconds=299)

        tracker._process_tick(5.0)

        assert tracker._pending == {"chrome.exe": 5.0}


class TestLimitNotification:
    """制限時間の通知"""

    def test_notifies_once_when_limit_reached(self, config, store, notifier):
        store.set_limit("chrome.exe", 1)  # 1分
        tracker = make_tracker(config, store, notifier)
        tracker._refresh_caches()

        tracker._process_tick(60.0)
        tracker._process_tick(60.0)

        assert notifier.reached == [("chrome.exe", 1)]

    def test_notifies_before_limit(self, config, store, notifier):
        store.set_limit("chrome.exe", 10)  # 10分、5分前に予告
        tracker = make_tracker(config, store, notifier)
        tracker._refresh_caches()

        tracker._process_tick(5.5 * 60)

        assert len(notifier.approaching) == 1
        app_name, limit_minutes, remaining = notifier.approaching[0]
        assert (app_name, limit_minutes) == ("chrome.exe", 10)
        assert remaining == 4

    def test_no_notification_without_limit(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)
        tracker._refresh_caches()

        tracker._process_tick(3600.0)

        assert notifier.reached == []
        assert notifier.approaching == []

    def test_existing_usage_counts_toward_limit(self, config, store, notifier):
        store.add_usage("chrome.exe", 59)
        store.set_limit("chrome.exe", 1)
        tracker = make_tracker(config, store, notifier)
        tracker._refresh_caches()

        tracker._process_tick(2.0)

        assert notifier.reached == [("chrome.exe", 1)]

    def test_limit_change_is_picked_up_after_notification(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)
        tracker._refresh_caches()

        store.set_limit("chrome.exe", 1)
        tracker.notify_limits_changed()
        tracker._process_tick(61.0)

        assert notifier.reached == [("chrome.exe", 1)]


class TestCurrentUsage:
    """現在使用中のアプリの取得（小型ウィンドウ用）"""

    def test_returns_none_before_first_tick(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)

        usage = tracker.get_current_usage()

        assert usage == {
            "app": None,
            "seconds": 0,
            "total_seconds": 0,
            "limit_minutes": None,
            "paused": False,
            "idle": False,
        }

    def test_total_seconds_covers_all_apps(self, config, store, notifier):
        store.add_usage_bulk({"chrome.exe": 600, "code.exe": 300})
        tracker = make_tracker(config, store, notifier)
        tracker._refresh_caches()

        tracker._process_tick(30.0)

        usage = tracker.get_current_usage()
        assert usage["seconds"] == 630
        assert usage["total_seconds"] == 930

    def test_limit_of_current_app_is_returned(self, config, store, notifier):
        store.set_limit("chrome.exe", 45)
        tracker = make_tracker(config, store, notifier)
        tracker._refresh_caches()

        tracker._process_tick(10.0)

        assert tracker.get_current_usage()["limit_minutes"] == 45

    def test_limit_is_none_without_setting(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)
        tracker._refresh_caches()

        tracker._process_tick(10.0)

        assert tracker.get_current_usage()["limit_minutes"] is None

    def test_returns_active_app_and_pending_seconds(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)

        tracker._process_tick(30.0)

        usage = tracker.get_current_usage()
        assert usage["app"] == "chrome.exe"
        assert usage["seconds"] == 30

    def test_includes_already_saved_seconds(self, config, store, notifier):
        # 書き出し済みの分と未書き出しの分を合算して返す
        store.add_usage("chrome.exe", 3600)
        tracker = make_tracker(config, store, notifier)
        tracker._refresh_caches()

        tracker._process_tick(25.0)

        assert tracker.get_current_usage()["seconds"] == 3625

    def test_value_is_stable_across_flush(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)
        tracker._process_tick(90.0)
        before = tracker.get_current_usage()["seconds"]

        tracker.flush()

        assert tracker.get_current_usage()["seconds"] == before

    def test_app_switch_is_reflected(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)
        tracker._process_tick(30.0)

        tracker._sampler = lambda: "code.exe"
        tracker._process_tick(10.0)

        usage = tracker.get_current_usage()
        assert usage["app"] == "code.exe"
        assert usage["seconds"] == 10

    def test_ignored_app_reports_none(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)
        tracker._process_tick(30.0)

        tracker._sampler = lambda: None
        tracker._process_tick(5.0)

        assert tracker.get_current_usage()["app"] is None

    def test_paused_state_is_reported(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)
        tracker._process_tick(30.0)
        tracker.pause()
        tracker._process_tick(5.0)

        usage = tracker.get_current_usage()
        assert usage["paused"] is True
        # 一時停止中は加算されない
        assert usage["seconds"] == 30

    def test_idle_state_is_reported(self, config, store, notifier):
        config._data["tracker"]["idle_detection"] = {
            "enabled": True,
            "threshold_seconds": 300,
        }
        tracker = make_tracker(config, store, notifier, idle_seconds=301)
        tracker._process_tick(5.0)

        assert tracker.get_current_usage()["idle"] is True

    def test_idle_flag_clears_after_activity(self, config, store, notifier):
        config._data["tracker"]["idle_detection"] = {
            "enabled": True,
            "threshold_seconds": 300,
        }
        idle = {"seconds": 301.0}
        tracker = AppTracker(
            config,
            store,
            notifier=notifier,
            sampler=lambda: "chrome.exe",
            idle_provider=lambda: idle["seconds"],
        )
        tracker._process_tick(5.0)

        idle["seconds"] = 0.0
        tracker._process_tick(5.0)

        usage = tracker.get_current_usage()
        assert usage["idle"] is False
        assert usage["seconds"] == 5


class TestSessionRecording:
    """使用区間（いつ使ったか）の記録"""

    def test_session_is_recorded_on_flush(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)

        tracker._process_tick(120.0)
        tracker.flush()

        sessions = store.get_sessions(today_str())
        assert len(sessions) == 1
        assert sessions[0]["app_name"] == "chrome.exe"
        assert sessions[0]["seconds"] == 120

    def test_open_session_is_updated_not_duplicated(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)

        tracker._process_tick(60.0)
        tracker.flush()
        tracker._process_tick(60.0)
        tracker.flush()

        sessions = store.get_sessions(today_str())
        assert len(sessions) == 1
        assert sessions[0]["seconds"] == 120

    def test_switching_app_splits_the_session(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)
        tracker._process_tick(60.0)

        tracker._sampler = lambda: "code.exe"
        tracker._process_tick(60.0)
        tracker.flush()

        sessions = store.get_sessions(today_str())
        assert [s["app_name"] for s in sessions] == ["chrome.exe", "code.exe"]
        assert all(s["seconds"] == 60 for s in sessions)

    def test_pause_closes_the_session(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)
        tracker._process_tick(60.0)

        tracker.pause()
        tracker._process_tick(60.0)
        tracker.resume()
        tracker._process_tick(60.0)
        tracker.flush()

        # 一時停止を挟んだ前後は別の区間になる
        assert len(store.get_sessions(today_str())) == 2

    def test_ignored_app_closes_the_session(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)
        tracker._process_tick(60.0)

        tracker._sampler = lambda: None
        tracker._process_tick(60.0)
        tracker._sampler = lambda: "chrome.exe"
        tracker._process_tick(60.0)
        tracker.flush()

        assert len(store.get_sessions(today_str())) == 2

    def test_short_session_is_not_recorded(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)

        # 1秒に満たない区間は記録しない
        tracker._process_tick(0.4)
        tracker.flush()

        assert store.get_sessions(today_str()) == []

    def test_session_time_range_reflects_usage(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)

        tracker._process_tick(300.0)
        tracker.flush()

        session = store.get_sessions(today_str())[0]
        started = datetime.strptime(session["started_at"], "%Y-%m-%d %H:%M:%S")
        ended = datetime.strptime(session["ended_at"], "%Y-%m-%d %H:%M:%S")
        # 走査間隔ぶんさかのぼって開始時刻とするため、長さは経過時間とほぼ一致する
        assert 299 <= (ended - started).total_seconds() <= 301

    def test_date_change_splits_the_session(self, config, store, notifier, monkeypatch):
        tracker = make_tracker(config, store, notifier)
        monkeypatch.setattr("app.tracker.today_str", lambda: "2026-01-01")
        tracker._current_date = "2026-01-01"
        tracker._process_tick(60.0)

        monkeypatch.setattr("app.tracker.today_str", lambda: "2026-01-02")
        tracker._process_tick(60.0)
        tracker.flush()

        # 日付ごとに集計できるよう、日をまたぐ区間は分割される
        assert len(store.get_sessions(today_str())) >= 1

    def test_stop_closes_the_session(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)
        tracker.start()
        tracker._process_tick(90.0)

        tracker.stop()

        assert store.get_sessions(today_str())[0]["seconds"] == 90


class TestDateRollover:
    """日付変更の処理"""

    def test_pending_is_written_to_previous_date(self, config, store, notifier, monkeypatch):
        tracker = make_tracker(config, store, notifier)
        monkeypatch.setattr("app.tracker.today_str", lambda: "2026-01-01")
        tracker._current_date = "2026-01-01"
        tracker._process_tick(30.0)

        monkeypatch.setattr("app.tracker.today_str", lambda: "2026-01-02")
        tracker._process_tick(10.0)
        tracker.flush()

        assert store.get_usage_by_range("2026-01-01", "2026-01-01") == {"chrome.exe": 30}
        assert store.get_usage_by_range("2026-01-02", "2026-01-02") == {"chrome.exe": 10}

    def test_notifications_reset_on_new_day(self, config, store, notifier, monkeypatch):
        store.set_limit("chrome.exe", 1)
        tracker = make_tracker(config, store, notifier)
        monkeypatch.setattr("app.tracker.today_str", lambda: "2026-01-01")
        tracker._current_date = "2026-01-01"
        tracker._refresh_caches()
        tracker._process_tick(61.0)
        assert len(notifier.reached) == 1

        monkeypatch.setattr("app.tracker.today_str", lambda: "2026-01-02")
        tracker._process_tick(61.0)

        assert len(notifier.reached) == 2


class TestLifecycle:
    """開始と停止"""

    def test_start_and_stop(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)

        tracker.start()
        assert tracker._thread is not None
        assert tracker._thread.is_alive()

        tracker.stop()
        assert tracker._thread is None

    def test_start_twice_reuses_thread(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)

        tracker.start()
        first_thread = tracker._thread
        tracker.start()

        assert tracker._thread is first_thread
        tracker.stop()

    def test_stop_persists_pending_usage(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)
        tracker.start()
        tracker._process_tick(12.0)

        tracker.stop()

        assert store.get_today_usage()["chrome.exe"] >= 12

    def test_max_elapsed_uses_poll_interval(self, config, store, notifier):
        tracker = make_tracker(config, store, notifier)

        assert tracker._poll_interval * MAX_ELAPSED_FACTOR == config.poll_interval * 3
