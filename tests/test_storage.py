"""
test_storage.py - データストアのテスト
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import date

import pytest

from app.storage import UsageStore, get_period_dates, today_str


class TestUsageLog:
    """使用時間の記録"""

    def test_add_usage_accumulates(self, store):
        store.add_usage("chrome.exe", 60)
        store.add_usage("chrome.exe", 30)

        assert store.get_today_usage() == {"chrome.exe": 90}

    def test_add_usage_bulk_writes_multiple_apps(self, store):
        store.add_usage_bulk({"chrome.exe": 60, "code.exe": 120})

        assert store.get_today_usage() == {"chrome.exe": 60, "code.exe": 120}

    def test_add_usage_bulk_ignores_zero_and_negative(self, store):
        store.add_usage_bulk({"chrome.exe": 0, "code.exe": -5, "notepad.exe": 10})

        assert store.get_today_usage() == {"notepad.exe": 10}

    def test_add_usage_bulk_with_empty_dict_is_noop(self, store):
        store.add_usage_bulk({})

        assert store.get_today_usage() == {}

    def test_japanese_app_name_round_trips(self, store):
        store.add_usage("鳴潮", 300)

        assert store.get_today_usage() == {"鳴潮": 300}

    def test_usage_is_recorded_per_date(self, store):
        store.add_usage("chrome.exe", 60, date="2026-01-01")
        store.add_usage("chrome.exe", 60, date="2026-01-02")

        assert store.get_usage_by_range("2026-01-01", "2026-01-02") == {"chrome.exe": 120}
        assert store.get_usage_by_range("2026-01-01", "2026-01-01") == {"chrome.exe": 60}


class TestUsageQueries:
    """使用時間の集計"""

    @pytest.fixture(autouse=True)
    def seed(self, store):
        store.add_usage_bulk({"chrome.exe": 100, "code.exe": 50}, date="2026-03-01")
        store.add_usage_bulk({"chrome.exe": 200}, date="2026-03-02")
        store.add_usage_bulk({"code.exe": 999}, date="2026-04-01")

    def test_range_excludes_outside_dates(self, store):
        assert store.get_usage_by_range("2026-03-01", "2026-03-31") == {
            "chrome.exe": 300,
            "code.exe": 50,
        }

    def test_range_with_no_data_returns_empty(self, store):
        assert store.get_usage_by_range("2020-01-01", "2020-12-31") == {}

    def test_daily_breakdown_returns_rows_sorted_by_date(self, store):
        rows = store.get_daily_breakdown("2026-03-01", "2026-03-02")

        assert len(rows) == 3
        assert [row["date"] for row in rows] == ["2026-03-01", "2026-03-01", "2026-03-02"]
        assert {"date", "app_name", "seconds"} == set(rows[0].keys())


class TestSessions:
    """使用区間の記録"""

    def test_add_and_get_session(self, store):
        store.add_session("chrome.exe", "2026-08-14 09:00:00", "2026-08-14 09:30:00", 1800)

        sessions = store.get_sessions("2026-08-14")

        assert len(sessions) == 1
        assert sessions[0]["app_name"] == "chrome.exe"
        assert sessions[0]["started_at"] == "2026-08-14 09:00:00"
        assert sessions[0]["seconds"] == 1800

    def test_date_is_derived_from_start_time(self, store):
        store.add_session("chrome.exe", "2026-08-14 23:50:00", "2026-08-14 23:59:00", 540)

        assert len(store.get_sessions("2026-08-14")) == 1
        assert store.get_sessions("2026-08-15") == []

    def test_update_extends_session(self, store):
        session_id = store.add_session(
            "chrome.exe", "2026-08-14 09:00:00", "2026-08-14 09:10:00", 600
        )

        store.update_session(session_id, "2026-08-14 09:40:00", 2400)

        session = store.get_sessions("2026-08-14")[0]
        assert session["ended_at"] == "2026-08-14 09:40:00"
        assert session["seconds"] == 2400

    def test_sessions_are_ordered_by_start(self, store):
        store.add_session("b.exe", "2026-08-14 14:00:00", "2026-08-14 15:00:00", 3600)
        store.add_session("a.exe", "2026-08-14 09:00:00", "2026-08-14 10:00:00", 3600)

        assert [s["app_name"] for s in store.get_sessions("2026-08-14")] == ["a.exe", "b.exe"]

    def test_session_dates_are_newest_first(self, store):
        store.add_session("a.exe", "2026-08-12 09:00:00", "2026-08-12 09:30:00", 1800)
        store.add_session("a.exe", "2026-08-14 09:00:00", "2026-08-14 09:30:00", 1800)
        store.add_session("a.exe", "2026-08-13 09:00:00", "2026-08-13 09:30:00", 1800)

        assert store.get_session_dates() == ["2026-08-14", "2026-08-13", "2026-08-12"]

    def test_japanese_app_name(self, store):
        store.add_session("鳴潮", "2026-08-14 20:00:00", "2026-08-14 21:00:00", 3600)

        assert store.get_sessions("2026-08-14")[0]["app_name"] == "鳴潮"

    def test_no_sessions_for_unknown_date(self, store):
        assert store.get_sessions("2020-01-01") == []


class TestLimits:
    """制限時間の設定（保存は照合キー、画面へは表示名）"""

    def test_set_and_get_limit(self, store):
        store.set_limit("chrome.exe", 60)

        # 判定に使う側はキーで返る
        assert store.get_limits() == {"chrome": 60}

    def test_set_limit_overwrites_existing(self, store):
        store.set_limit("chrome.exe", 60)
        store.set_limit("chrome.exe", 120)

        assert store.get_limits() == {"chrome": 120}

    def test_remove_limit(self, store):
        store.set_limit("chrome.exe", 60)
        store.remove_limit("chrome.exe")

        assert store.get_limits() == {}

    def test_remove_unknown_limit_is_noop(self, store):
        store.remove_limit("unknown.exe")

        assert store.get_limits() == {}

    def test_表示名で設定しても記録名に効く(self, store):
        """画面は表示名でやり取りするが、判定は記録名から求めたキーで行う

        以前は表示名のまま保存していたため、PCが chrome.exe として
        記録するアプリに Chrome の制限を設定しても働かなかった。
        """
        store.add_usage("chrome.exe", 600, "2026-08-24")

        store.set_limit("Chrome", 30)

        # トラッカーが記録名から引いても同じ制限に当たる
        assert store.get_limits()[store.key_for("chrome.exe")] == 30

    def test_別の表記で設定し直すと上書きされる(self, store):
        """同じアプリを違う表記で設定しても、二重にならない"""
        store.set_limit("chrome.exe", 60)
        store.set_limit("Chrome", 30)

        assert store.get_limits() == {"chrome": 30}

    def test_画面向けには表示名で返る(self, store):
        store.add_usage("chrome.exe", 600, "2026-08-24", device="pc")
        store.add_usage("Chrome", 300, "2026-08-24", device="android")
        store.set_limit("Chrome", 30)

        assert store.get_limits_by_name() == {"Chrome": 30}

    def test_記録の無いアプリの制限はキーのまま返る(self, store):
        """一度も使っていないアプリは表示名を決められないため、そのまま出す"""
        store.set_limit("まだ使っていないアプリ", 30)

        assert store.get_limits_by_name() == {store.key_for("まだ使っていないアプリ"): 30}


class TestPeriodDates:
    """期間の算出"""

    def test_day_returns_same_date(self):
        assert get_period_dates("day", date(2026, 7, 15)) == ("2026-07-15", "2026-07-15")

    def test_week_starts_on_monday(self):
        # 2026-07-15 は水曜日。その日を含む週の全体（月〜日）を返す
        assert get_period_dates("week", date(2026, 7, 15)) == ("2026-07-13", "2026-07-19")

    def test_week_on_monday_covers_whole_week(self):
        assert get_period_dates("week", date(2026, 7, 13)) == ("2026-07-13", "2026-07-19")

    def test_month_covers_whole_month(self):
        assert get_period_dates("month", date(2026, 7, 15)) == ("2026-07-01", "2026-07-31")

    def test_月末の日数に合わせる(self):
        # うるう年の2月
        assert get_period_dates("month", date(2024, 2, 10)) == ("2024-02-01", "2024-02-29")
        assert get_period_dates("month", date(2026, 2, 10)) == ("2026-02-01", "2026-02-28")

    def test_limitを渡すとその日で打ち切る(self):
        # まだ来ていない日付を期間に含めないための指定
        assert get_period_dates("week", date(2026, 7, 15), limit=date(2026, 7, 15)) == (
            "2026-07-13",
            "2026-07-15",
        )
        assert get_period_dates("month", date(2026, 7, 15), limit=date(2026, 7, 15)) == (
            "2026-07-01",
            "2026-07-15",
        )

    def test_limitが期間より後なら影響しない(self):
        assert get_period_dates("week", date(2026, 7, 15), limit=date(2026, 12, 31)) == (
            "2026-07-13",
            "2026-07-19",
        )

    def test_limitが期間より前でも開始日は下回らない(self):
        # 過去の週を、それより前の日で打ち切ろうとした場合
        assert get_period_dates("week", date(2026, 7, 15), limit=date(2026, 1, 1)) == (
            "2026-07-13",
            "2026-07-13",
        )

    def test_unknown_period_falls_back_to_day(self):
        assert get_period_dates("year", date(2026, 7, 15)) == ("2026-07-15", "2026-07-15")


class TestConnection:
    """接続の扱い"""

    def test_database_file_is_created(self, tmp_path):
        db_path = tmp_path / "nested" / "usage.db"
        store = UsageStore(str(db_path))
        store.get_limits()

        assert db_path.exists()
        store.close()

    def test_store_is_usable_after_close(self, store):
        store.add_usage("chrome.exe", 10)
        store.close()

        # 接続は必要になった時点で再作成される
        assert store.get_today_usage() == {"chrome.exe": 10}

    def test_close_from_another_thread(self, tmp_path, caplog):
        """別スレッドが作った接続も終了時に閉じられること

        計測スレッドやWebスレッドが作った接続を、メインスレッドの終了処理から
        閉じられないと、WALの統合が行われないまま残ってしまう。
        """
        db_path = str(tmp_path / "data" / "usage.db")
        store = UsageStore(db_path)

        worker = threading.Thread(target=lambda: store.add_usage("chrome.exe", 60))
        worker.start()
        worker.join()

        with caplog.at_level(logging.WARNING):
            store.close()

        assert "切断に失敗" not in caplog.text

    def test_wal_is_merged_on_close(self, tmp_path):
        """終了時にWALファイルがDB本体へ統合されること"""
        db_path = str(tmp_path / "data" / "usage.db")
        store = UsageStore(db_path)
        for i in range(200):
            store.add_usage_bulk({f"app{i}.exe": 60})
        assert os.path.exists(db_path + "-wal")

        store.close()

        assert not os.path.exists(db_path + "-wal")

    def test_today_str_format(self):
        assert len(today_str()) == 10
        assert today_str().count("-") == 2
