"""
test_api.py - Web API のテスト
"""

from __future__ import annotations

import pytest

from app.mini_window import MiniWindowController
from app.storage import StorageError
from app.web import create_app


class FakeTracker:
    """一時停止状態のみを持つテスト用トラッカー"""

    def __init__(self):
        self._paused = False
        self.limits_changed_count = 0

    @property
    def is_paused(self):
        return self._paused

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def notify_limits_changed(self):
        self.limits_changed_count += 1


@pytest.fixture
def tracker():
    return FakeTracker()


@pytest.fixture
def mini_window():
    return MiniWindowController()


@pytest.fixture
def client(store, tracker, config, mini_window):
    app = create_app(store, tracker, config, mini_window)
    return app.test_client()


class TestDashboard:
    """ダッシュボード画面"""

    def test_dashboard_renders(self, client):
        res = client.get("/")

        assert res.status_code == 200
        assert b"App Usage Tracker" in res.data


class TestUsageApi:
    """使用時間API"""

    def test_today_returns_apps_sorted_by_usage(self, client, store):
        store.add_usage_bulk({"chrome.exe": 60, "code.exe": 300})

        data = client.get("/api/usage/today").get_json()

        assert [item["app"] for item in data] == ["code.exe", "chrome.exe"]
        assert data[0]["seconds"] == 300
        assert data[0]["minutes"] == 5.0

    def test_today_includes_limit(self, client, store):
        store.add_usage("chrome.exe", 60)
        store.set_limit("chrome.exe", 30)

        data = client.get("/api/usage/today").get_json()

        assert data[0]["limit"] == 30

    def test_today_with_no_data_returns_empty_list(self, client):
        assert client.get("/api/usage/today").get_json() == []

    def test_japanese_app_name_is_not_escaped(self, client, store):
        store.add_usage("鳴潮", 60)

        res = client.get("/api/usage/today")

        assert "鳴潮".encode("utf-8") in res.data
        assert res.get_json()[0]["app"] == "鳴潮"

    @pytest.mark.parametrize("period", ["day", "week", "month"])
    def test_valid_periods(self, client, period):
        res = client.get(f"/api/usage/{period}")

        assert res.status_code == 200
        data = res.get_json()
        assert isinstance(data["apps"], list)

    @pytest.mark.parametrize("period", ["day", "week", "month"])
    def test_期間の範囲を返す(self, client, period):
        # 画面の見出しに出すため、集計と一緒に対象期間も返す
        data = client.get(f"/api/usage/{period}").get_json()

        assert data["period"] == period
        assert data["start"] <= data["end"]

    def test_週は月曜始まり(self, client):
        from datetime import datetime

        data = client.get("/api/usage/week").get_json()
        assert datetime.strptime(data["start"], "%Y-%m-%d").weekday() == 0

    def test_月は1日始まり(self, client):
        data = client.get("/api/usage/month").get_json()
        assert data["start"].endswith("-01")

    def test_日付を指定するとその日の集計を返す(self, client, store):
        store.add_usage("code.exe", 1800, "2026-03-01")

        data = client.get("/api/usage/today?date=2026-03-01").get_json()

        assert data == [{"app": "code.exe", "seconds": 1800, "minutes": 30.0,
                         "limit": None, "devices": ["pc"], "device_seconds": {"pc": 1800}}]

    def test_日付を指定するとその日を含む週を返す(self, client):
        # 2026-03-01 は日曜。週は月曜始まりなので 02-23〜03-01
        data = client.get("/api/usage/week?date=2026-03-01").get_json()

        assert data["start"] == "2026-02-23"
        assert data["end"] == "2026-03-01"

    def test_日付を指定するとその日を含む月を返す(self, client):
        # 過ぎた月なので、月の全体（1日〜末日）が返る
        data = client.get("/api/usage/month?date=2026-03-15").get_json()

        assert data["start"] == "2026-03-01"
        assert data["end"] == "2026-03-31"

    def test_今月はまだ来ていない日を含めない(self, client):
        from app.storage import today_str

        data = client.get("/api/usage/month").get_json()

        assert data["end"] == today_str()

    def test_実時間の集計も日付を指定できる(self, client, store):
        store.add_session("code.exe", "2026-03-01 09:00:00", "2026-03-01 10:00:00", 3600)

        data = client.get("/api/usage/summary?date=2026-03-01").get_json()

        assert data["date"] == "2026-03-01"
        assert data["total_seconds"] == 3600

    def test_不正な日付は400(self, client):
        assert client.get("/api/usage/today?date=2026-13-99").status_code == 400
        assert client.get("/api/usage/week?date=abc").status_code == 400

    def test_集計は期間で切り替えられる(self, client, store):
        store.add_usage("code.exe", 600, "2026-03-01")
        store.add_usage("chrome.exe", 300, "2026-03-02")

        day = client.get("/api/usage/summary?date=2026-03-02&period=day").get_json()
        month = client.get("/api/usage/summary?date=2026-03-02&period=month").get_json()

        assert day["start"] == "2026-03-02"
        assert day["app_count"] == 1
        assert month["start"] == "2026-03-01"
        assert month["app_count"] == 2

    def test_集計の実時間は日ごとに重なりを除く(self, client, store):
        # 同じ時間帯を2台で使った日が2日
        for date in ("2026-03-01", "2026-03-02"):
            store.add_session("code.exe", f"{date} 09:00:00", f"{date} 10:00:00", 3600)
            # 日次集計はトラッカーが別に書き込むため、テストでも用意する
            store.add_usage("code.exe", 3600, date)
            store.import_sessions("android", [{
                "date": date, "app_name": "YouTube",
                "started_at": f"{date} 09:00:00", "ended_at": f"{date} 10:00:00",
                "seconds": 3600, "external_id": f"a:{date}",
            }])

        data = client.get("/api/usage/summary?date=2026-03-02&period=month").get_json()

        # 単純に足すと4時間だが、重なりを除くと2時間
        assert data["simple_total_seconds"] == 4 * 3600
        assert data["total_seconds"] == 2 * 3600

    def test_超過は日ごとに判定する(self, client, store):
        store.set_limit("code.exe", 30)
        # 1日あたりは20分ずつなので、合計40分でも超過にはならない
        store.add_usage("code.exe", 20 * 60, "2026-03-01")
        store.add_usage("code.exe", 20 * 60, "2026-03-02")

        data = client.get("/api/usage/summary?date=2026-03-02&period=month").get_json()
        assert data["over_limit_count"] == 0

        # 1日でも超えれば数える（3日目だけ40分）
        store.add_usage("code.exe", 40 * 60, "2026-03-03")
        data = client.get("/api/usage/summary?date=2026-03-03&period=month").get_json()
        assert data["over_limit_count"] == 1

    def test_超過の判定はPCの使用時間だけで行う(self, client, store):
        # 通知を出すトラッカーと基準を揃えるため、スマホ分は数えない
        store.set_limit("YouTube", 30)
        store.import_sessions("android", [{
            "date": "2026-03-01", "app_name": "YouTube",
            "started_at": "2026-03-01 09:00:00", "ended_at": "2026-03-01 10:00:00",
            "seconds": 3600, "external_id": "a:1",
        }])

        data = client.get("/api/usage/summary?date=2026-03-01&period=day").get_json()
        assert data["over_limit_count"] == 0

    def test_前日との増減を返す(self, client, store):
        store.add_session("code.exe", "2026-03-01 09:00:00", "2026-03-01 10:00:00", 3600)
        store.add_session("code.exe", "2026-03-02 09:00:00", "2026-03-02 09:30:00", 1800)

        data = client.get("/api/usage/summary?date=2026-03-02&period=day").get_json()

        assert data["previous_start"] == "2026-03-01"
        assert data["previous_end"] == "2026-03-01"
        assert data["previous_seconds"] == 3600
        assert data["diff_seconds"] == -1800

    def test_過ぎた週は7日分をまるごと比べる(self, client, store):
        # 2026-03-02 は月曜。既に過ぎた週なので7日そろっている
        data = client.get("/api/usage/summary?date=2026-03-02&period=week").get_json()

        assert (data["start"], data["end"]) == ("2026-03-02", "2026-03-08")
        assert (data["previous_start"], data["previous_end"]) == ("2026-02-23", "2026-03-01")

    def test_途中の週は経過日数だけを比べる(self, client):
        """今週は今日で切れるため、前の週も同じ日数に揃える"""
        from datetime import date

        data = client.get("/api/usage/summary?period=week").get_json()

        def span(start, end):
            return (date.fromisoformat(end) - date.fromisoformat(start)).days

        assert span(data["start"], data["end"]) == span(
            data["previous_start"], data["previous_end"]
        )
        # 前の期間が今の期間へ食い込まない
        assert date.fromisoformat(data["previous_end"]) < date.fromisoformat(data["start"])

    def test_前の期間は翌月へはみ出さない(self, client, store):
        # 3月は31日、2月は28日。日数を揃えると3月へ食い込むため、月末で止める
        data = client.get("/api/usage/summary?date=2026-03-31&period=month").get_json()

        assert data["start"] == "2026-03-01"
        assert data["previous_start"] == "2026-02-01"
        assert data["previous_end"] == "2026-02-28"

    def test_前の期間の実時間も重なりを除く(self, client, store):
        # 前日は2台で同じ時間帯を使っている（単純な合計は2時間、実時間は1時間）
        store.add_session("code.exe", "2026-03-01 09:00:00", "2026-03-01 10:00:00", 3600)
        store.import_sessions("android", [{
            "date": "2026-03-01", "app_name": "YouTube",
            "started_at": "2026-03-01 09:00:00", "ended_at": "2026-03-01 10:00:00",
            "seconds": 3600, "external_id": "a:1",
        }])

        data = client.get("/api/usage/summary?date=2026-03-02&period=day").get_json()

        assert data["previous_seconds"] == 3600

    def test_記録の無い前の期間は0(self, client, store):
        store.add_session("code.exe", "2026-03-02 09:00:00", "2026-03-02 10:00:00", 3600)

        data = client.get("/api/usage/summary?date=2026-03-02&period=day").get_json()

        assert data["previous_seconds"] == 0
        assert data["diff_seconds"] == 3600

    def test_集計の不正な期間は400(self, client):
        assert client.get("/api/usage/summary?period=year").status_code == 400

    def test_履歴はアプリで絞り込める(self, client, store):
        from app.storage import today_str

        today = today_str()
        store.add_session("code.exe", f"{today} 09:00:00", f"{today} 10:00:00", 3600)
        store.add_session("chrome.exe", f"{today} 11:00:00", f"{today} 11:30:00", 1800)

        全体 = client.get("/api/history").get_json()
        絞込 = client.get("/api/history?app=code.exe").get_json()

        total = lambda d: sum(r["total"] for r in d["rows"])
        assert total(全体) == 5400
        assert total(絞込) == 3600
        assert 絞込["app"] == "code.exe"

    def test_履歴は選べるアプリの一覧を返す(self, client, store):
        from app.storage import today_str

        today = today_str()
        store.add_session("chrome.exe", f"{today} 09:00:00", f"{today} 09:10:00", 600)
        store.add_session("code.exe", f"{today} 10:00:00", f"{today} 11:00:00", 3600)

        data = client.get("/api/history").get_json()

        # 使用時間の多い順に並ぶ
        assert data["apps"] == ["code.exe", "chrome.exe"]

    def test_絞り込んでも候補は減らない(self, client, store):
        from app.storage import today_str

        today = today_str()
        store.add_session("code.exe", f"{today} 09:00:00", f"{today} 10:00:00", 3600)
        store.add_session("chrome.exe", f"{today} 11:00:00", f"{today} 11:30:00", 1800)

        data = client.get("/api/history?app=code.exe").get_json()
        assert set(data["apps"]) == {"code.exe", "chrome.exe"}

    def test_該当しないアプリなら空になる(self, client, store):
        from app.storage import today_str

        today = today_str()
        store.add_session("code.exe", f"{today} 09:00:00", f"{today} 10:00:00", 3600)

        data = client.get("/api/history?app=存在しない").get_json()
        assert sum(r["total"] for r in data["rows"]) == 0
        # 行そのものは残り、表が途切れない
        assert len(data["rows"]) == 30

    def test_invalid_period_returns_400(self, client):
        res = client.get("/api/usage/year")

        assert res.status_code == 400
        assert "error" in res.get_json()

    def test_daily_breakdown_returns_rows(self, client, store):
        from app.storage import today_str

        store.add_usage("chrome.exe", 60)

        data = client.get("/api/usage/daily-breakdown?period=week").get_json()

        assert data == [{"date": today_str(), "app_name": "chrome.exe", "seconds": 60}]

    def test_daily_breakdown_rejects_invalid_period(self, client):
        assert client.get("/api/usage/daily-breakdown?period=year").status_code == 400


class TestTimelineApi:
    """タイムラインAPI"""

    def test_timeline_returns_sessions(self, client, store):
        from app.storage import today_str

        date = today_str()
        store.add_session("chrome.exe", f"{date} 09:00:00", f"{date} 09:40:00", 2400)

        data = client.get("/api/timeline").get_json()

        assert data["date"] == date
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["start"] == "09:00"
        assert data["sessions"][0]["end"] == "09:40"
        assert data["totals"] == [
            {"app": "chrome.exe", "seconds": 2400, "devices": ["pc"]}
        ]

    def test_timeline_for_specified_date(self, client, store):
        store.add_session("code.exe", "2026-03-01 14:00:00", "2026-03-01 15:00:00", 3600)

        data = client.get("/api/timeline?date=2026-03-01").get_json()

        assert data["date"] == "2026-03-01"
        assert data["sessions"][0]["app"] == "code.exe"

    def test_short_sessions_are_filtered(self, client, store):
        store.add_session("chrome.exe", "2026-03-01 09:00:00", "2026-03-01 09:00:10", 10)

        data = client.get("/api/timeline?date=2026-03-01").get_json()

        assert data["sessions"] == []

    def test_adjacent_sessions_are_merged(self, client, store):
        store.add_session("chrome.exe", "2026-03-01 09:00:00", "2026-03-01 09:10:00", 600)
        store.add_session("chrome.exe", "2026-03-01 09:10:30", "2026-03-01 09:20:00", 570)

        data = client.get("/api/timeline?date=2026-03-01").get_json()

        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["end"] == "09:20"

    def test_unpadded_date_is_normalized(self, client, store):
        # 0埋めしていない表記でも照会できること
        store.add_session("a.exe", "2026-03-01 09:00:00", "2026-03-01 09:30:00", 1800)

        data = client.get("/api/timeline?date=2026-3-1").get_json()

        assert data["date"] == "2026-03-01"
        assert len(data["sessions"]) == 1

    def test_invalid_date_returns_400(self, client):
        assert client.get("/api/timeline?date=abc").status_code == 400
        assert client.get("/api/timeline?date=2026-13-45").status_code == 400

    def test_empty_day(self, client):
        data = client.get("/api/timeline?date=2020-01-01").get_json()

        assert data["sessions"] == []
        assert data["totals"] == []

    def test_recorded_dates(self, client, store):
        store.add_session("a.exe", "2026-03-01 09:00:00", "2026-03-01 09:30:00", 1800)
        store.add_session("a.exe", "2026-03-03 09:00:00", "2026-03-03 09:30:00", 1800)

        assert client.get("/api/timeline/dates").get_json() == ["2026-03-03", "2026-03-01"]


class TestTimelineSummaryApi:
    """タイムラインの要約"""

    def test_summary_is_included(self, client, store):
        store.add_session("chrome.exe", "2026-03-02 08:40:00", "2026-03-02 09:30:00", 3000)
        store.add_session("code.exe", "2026-03-02 14:00:00", "2026-03-02 16:00:00", 7200)

        summary = client.get("/api/timeline?date=2026-03-02").get_json()["summary"]

        assert summary["start"] == "08:40"
        assert summary["end"] == "16:00"
        assert summary["longest"]["app"] == "code.exe"
        assert summary["total"] == 10200

    def test_previous_day_is_compared(self, client, store):
        store.add_session("a.exe", "2026-03-01 09:00:00", "2026-03-01 09:30:00", 1800)
        store.add_session("a.exe", "2026-03-02 09:00:00", "2026-03-02 10:00:00", 3600)

        summary = client.get("/api/timeline?date=2026-03-02").get_json()["summary"]

        assert summary["previous_total"] == 1800
        assert summary["diff"] == 1800

    def test_summary_for_empty_day(self, client):
        summary = client.get("/api/timeline?date=2020-01-01").get_json()["summary"]

        assert summary["total"] == 0
        assert summary["start"] is None


class TestHistoryApi:
    """履歴API"""

    def test_history_returns_requested_days(self, client):
        data = client.get("/api/history?days=7").get_json()

        assert data["days"] == 7
        assert len(data["rows"]) == 7
        assert all(len(row["hours"]) == 24 for row in data["rows"])

    def test_rows_are_newest_first(self, client):
        rows = client.get("/api/history?days=5").get_json()["rows"]

        assert [r["date"] for r in rows] == sorted([r["date"] for r in rows], reverse=True)

    def test_usage_is_placed_in_the_right_hour(self, client, store):
        from app.storage import today_str

        date = today_str()
        store.add_session("chrome.exe", f"{date} 14:00:00", f"{date} 14:30:00", 1800)

        row = client.get("/api/history?days=1").get_json()["rows"][0]

        assert row["hours"][14] == 1800
        assert row["total"] == 1800

    def test_days_is_capped(self, client):
        from app.web.api import MAX_HISTORY_DAYS

        assert client.get("/api/history?days=9999").get_json()["days"] == MAX_HISTORY_DAYS

    def test_days_below_one_is_raised(self, client):
        assert client.get("/api/history?days=0").get_json()["days"] == 1

    def test_invalid_days_returns_400(self, client):
        assert client.get("/api/history?days=abc").status_code == 400


class TestLimitsApi:
    """制限時間API"""

    def test_get_limits_empty(self, client):
        assert client.get("/api/limits").get_json() == []

    def test_set_and_get_limit(self, client):
        res = client.post("/api/limits", json={"app": "chrome.exe", "minutes": 60})

        assert res.status_code == 200
        assert res.get_json()["ok"] is True
        # 記録が無いため表示名を決められず、照合キーのまま返る
        assert client.get("/api/limits").get_json() == [{"app": "chrome", "minutes": 60}]

    def test_一覧は表示名で返る(self, client, store):
        store.add_usage("chrome.exe", 600, "2026-03-01", device="pc")
        store.add_usage("Chrome", 300, "2026-03-01", device="android")

        client.post("/api/limits", json={"app": "Chrome", "minutes": 60})

        assert client.get("/api/limits").get_json() == [{"app": "Chrome", "minutes": 60}]

    def test_表示名で設定した制限が記録名のアプリにも効く(self, client, store):
        # 画面は Chrome と出すが、PCは chrome.exe として記録する
        store.add_usage("chrome.exe", 40 * 60, "2026-03-01", device="pc")
        store.add_usage("Chrome", 1, "2026-03-01", device="android")

        client.post("/api/limits", json={"app": "Chrome", "minutes": 30})

        data = client.get("/api/usage/summary?date=2026-03-01&period=day").get_json()
        assert data["over_limit_count"] == 1

    def test_set_limit_notifies_tracker(self, client, tracker):
        client.post("/api/limits", json={"app": "chrome.exe", "minutes": 60})

        assert tracker.limits_changed_count == 1

    def test_zero_minutes_removes_limit(self, client, store):
        store.set_limit("chrome.exe", 60)

        client.post("/api/limits", json={"app": "chrome.exe", "minutes": 0})

        assert store.get_limits() == {}

    def test_string_minutes_are_accepted(self, client):
        res = client.post("/api/limits", json={"app": "chrome.exe", "minutes": "45"})

        assert res.status_code == 200
        assert client.get("/api/limits").get_json()[0]["minutes"] == 45

    @pytest.mark.parametrize(
        "payload",
        [
            {"minutes": 60},
            {"app": "chrome.exe"},
            {"app": "   ", "minutes": 60},
            {"app": "chrome.exe", "minutes": "abc"},
        ],
    )
    def test_invalid_payload_returns_400(self, client, payload):
        assert client.post("/api/limits", json=payload).status_code == 400

    def test_non_json_body_returns_400(self, client):
        res = client.post("/api/limits", data="not json", content_type="text/plain")

        assert res.status_code == 400

    def test_delete_limit(self, client, store):
        store.set_limit("chrome.exe", 60)

        res = client.delete("/api/limits/chrome.exe")

        assert res.status_code == 200
        assert store.get_limits() == {}

    def test_delete_limit_with_special_characters(self, client, store):
        # ブラウザのサイト判定では記号や空白を含む名前になる
        store.set_limit("X (Twitter)", 30)

        res = client.delete("/api/limits/X%20(Twitter)")

        assert res.status_code == 200
        assert store.get_limits() == {}

    def test_delete_limit_with_japanese_name(self, client, store):
        store.set_limit("鳴潮", 30)

        res = client.delete("/api/limits/%E9%B3%B4%E6%BD%AE")

        assert res.status_code == 200
        assert store.get_limits() == {}


class TestStatusApi:
    """トラッカーの状態API"""

    def test_status_reports_running(self, client):
        data = client.get("/api/status").get_json()

        assert data["paused"] is False
        assert data["available"] is True
        assert "version" in data

    def test_toggle_pause_switches_state(self, client):
        assert client.post("/api/toggle-pause").get_json()["paused"] is True
        assert client.post("/api/toggle-pause").get_json()["paused"] is False

    def test_status_without_tracker(self, store, config):
        client = create_app(store, None, config).test_client()

        data = client.get("/api/status").get_json()

        assert data["paused"] is False
        assert data["available"] is False

    def test_toggle_pause_without_tracker(self, store, config):
        client = create_app(store, None, config).test_client()

        assert client.post("/api/toggle-pause").get_json()["available"] is False


class TestMiniWindowApi:
    """ミニウィンドウの再表示API"""

    def test_status_includes_mini_window_state(self, client):
        data = client.get("/api/status").get_json()

        assert data["mini_window"] == {"available": True, "visible": False}

    def test_show_requests_display(self, client, mini_window):
        res = client.post("/api/mini-window/show")

        assert res.get_json() == {
            "ok": True,
            "available": True,
            "visible": False,
            "requested": True,
        }
        assert mini_window.wait_for_request(0.01) is True

    def test_show_while_visible_does_not_request(self, client, mini_window):
        mini_window.set_visible(True)

        res = client.post("/api/mini-window/show")

        assert res.get_json()["requested"] is False
        # 表示中に要求を積むと、閉じた直後に再表示されてしまう
        assert mini_window.wait_for_request(0.01) is False

    def test_status_reflects_visibility(self, client, mini_window):
        mini_window.set_visible(True)

        assert client.get("/api/status").get_json()["mini_window"]["visible"] is True

    def test_show_without_controller(self, store, tracker, config):
        client = create_app(store, tracker, config).test_client()

        res = client.post("/api/mini-window/show")

        assert res.get_json() == {"ok": False, "available": False, "visible": False}

    def test_status_without_controller(self, store, tracker, config):
        client = create_app(store, tracker, config).test_client()

        assert client.get("/api/status").get_json()["mini_window"]["available"] is False


class TestErrorHandling:
    """エラー応答"""

    def test_unknown_api_returns_json_404(self, client):
        res = client.get("/api/does-not-exist")

        assert res.status_code == 404
        assert res.is_json
        assert "error" in res.get_json()

    def test_storage_error_returns_json_500(self, client, store, monkeypatch):
        def fail(*args, **kwargs):
            raise StorageError("DB接続失敗")

        # 日付を指定できるようにしたため、この経路は範囲指定で取得する
        monkeypatch.setattr(store, "get_usage_by_range", fail)

        res = client.get("/api/usage/today")

        assert res.status_code == 500
        assert res.get_json() == {"error": "Internal Server Error"}

    def test_unknown_page_returns_html_404(self, client):
        res = client.get("/does-not-exist")

        assert res.status_code == 404
        assert not res.is_json
