"""
test_timeline.py - 使用区間の整形のテスト
"""

from __future__ import annotations

from app.timeline import (
    merge_intervals,
    union_seconds,
    build_history,
    build_timeline,
    day_summary,
    hourly_usage,
    merge_sessions,
    parse_time,
    recent_dates,
    seconds_since_midnight,
    summarize,
)


def session(app, start, end, seconds=None):
    """テスト用の使用区間（時刻は "HH:MM:SS" で指定）"""
    started = f"2026-08-14 {start}"
    ended = f"2026-08-14 {end}"
    if seconds is None:
        seconds = int((parse_time(ended) - parse_time(started)).total_seconds())
    return {"app_name": app, "started_at": started, "ended_at": ended, "seconds": seconds}


class TestMergeSessions:
    """短い中断の結合"""

    def test_same_app_within_gap_is_merged(self):
        sessions = [
            session("chrome.exe", "09:00:00", "09:10:00"),
            session("chrome.exe", "09:10:30", "09:20:00"),
        ]

        merged = merge_sessions(sessions, gap_seconds=60)

        assert len(merged) == 1
        assert merged[0]["started_at"].endswith("09:00:00")
        assert merged[0]["ended_at"].endswith("09:20:00")
        assert merged[0]["seconds"] == 600 + 570

    def test_gap_beyond_threshold_is_kept_separate(self):
        sessions = [
            session("chrome.exe", "09:00:00", "09:10:00"),
            session("chrome.exe", "09:15:00", "09:20:00"),
        ]

        assert len(merge_sessions(sessions, gap_seconds=60)) == 2

    def test_different_apps_are_not_merged(self):
        sessions = [
            session("chrome.exe", "09:00:00", "09:10:00"),
            session("code.exe", "09:10:10", "09:20:00"),
        ]

        assert len(merge_sessions(sessions, gap_seconds=60)) == 2

    def test_three_consecutive_sessions_merge_into_one(self):
        sessions = [
            session("chrome.exe", "09:00:00", "09:05:00"),
            session("chrome.exe", "09:05:20", "09:10:00"),
            session("chrome.exe", "09:10:20", "09:15:00"),
        ]

        merged = merge_sessions(sessions, gap_seconds=60)

        assert len(merged) == 1
        assert merged[0]["ended_at"].endswith("09:15:00")

    def test_unsorted_input_is_handled(self):
        sessions = [
            session("chrome.exe", "09:10:30", "09:20:00"),
            session("chrome.exe", "09:00:00", "09:10:00"),
        ]

        merged = merge_sessions(sessions, gap_seconds=60)

        assert len(merged) == 1
        assert merged[0]["started_at"].endswith("09:00:00")

    def test_empty_input(self):
        assert merge_sessions([], gap_seconds=60) == []


class TestBuildTimeline:
    """表示用データの組み立て"""

    def test_short_session_is_excluded(self):
        sessions = [session("chrome.exe", "09:00:00", "09:00:20")]

        assert build_timeline(sessions, min_seconds=30, gap_seconds=60) == []

    def test_long_enough_session_is_kept(self):
        sessions = [session("chrome.exe", "09:00:00", "09:40:00")]

        result = build_timeline(sessions, min_seconds=30, gap_seconds=60)

        assert len(result) == 1
        assert result[0]["app"] == "chrome.exe"
        assert result[0]["start"] == "09:00"
        assert result[0]["end"] == "09:40"
        assert result[0]["seconds"] == 2400

    def test_offset_and_length_for_positioning(self):
        sessions = [session("chrome.exe", "09:30:00", "10:00:00")]

        result = build_timeline(sessions, min_seconds=30, gap_seconds=60)

        # 0時からの経過秒数と長さ（帯の配置に使う）
        assert result[0]["offset"] == 9 * 3600 + 30 * 60
        assert result[0]["length"] == 1800

    def test_merged_before_filtering(self):
        # 単体では30秒未満でも、結合すれば残る
        sessions = [
            session("chrome.exe", "09:00:00", "09:00:20"),
            session("chrome.exe", "09:00:40", "09:01:00"),
        ]

        result = build_timeline(sessions, min_seconds=30, gap_seconds=60)

        assert len(result) == 1
        assert result[0]["seconds"] == 40

    def test_sessions_are_ordered_by_start(self):
        sessions = [
            session("code.exe", "14:00:00", "15:00:00"),
            session("chrome.exe", "09:00:00", "10:00:00"),
        ]

        result = build_timeline(sessions, min_seconds=30, gap_seconds=60)

        assert [r["start"] for r in result] == ["09:00", "14:00"]

    def test_length_never_exceeds_the_day(self):
        sessions = [session("chrome.exe", "23:30:00", "23:59:59")]

        result = build_timeline(sessions, min_seconds=30, gap_seconds=60)

        assert result[0]["offset"] + result[0]["length"] <= 24 * 3600


class TestUnionSeconds:
    """重なりを除いた実時間"""

    def session(self, start, end, app="a", device="pc", seconds=None):
        s = f"2026-08-23 {start}:00"
        e = f"2026-08-23 {end}:00"
        span = (int(end[:2]) * 60 + int(end[3:])) - (int(start[:2]) * 60 + int(start[3:]))
        return {
            "app": app,
            "device": device,
            "started_at": s,
            "ended_at": e,
            "seconds": span * 60 if seconds is None else seconds,
        }

    def test_重ならない区間は単純な合計と同じ(self):
        sessions = [self.session("09:00", "10:00"), self.session("11:00", "12:00")]
        assert union_seconds(sessions) == 7200

    def test_完全に重なる区間は1回だけ数える(self):
        # PCとスマホで同じ時間帯を使っていた場合
        sessions = [
            self.session("09:00", "10:00", device="pc"),
            self.session("09:00", "10:00", device="android"),
        ]
        assert union_seconds(sessions) == 3600

    def test_一部が重なる区間(self):
        sessions = [
            self.session("09:00", "10:00", device="pc"),
            self.session("09:30", "11:00", device="android"),
        ]
        # 9:00〜11:00 の2時間
        assert union_seconds(sessions) == 7200

    def test_一方が他方に含まれる場合(self):
        sessions = [
            self.session("09:00", "12:00", device="pc"),
            self.session("10:00", "11:00", device="android"),
        ]
        assert union_seconds(sessions) == 3 * 3600

    def test_隣接する区間はつながる(self):
        sessions = [self.session("09:00", "10:00"), self.session("10:00", "11:00")]
        assert union_seconds(sessions) == 7200

    def test_時刻を持たない記録はそのまま足す(self):
        # 日次集計しか無い古い記録が混ざっても壊れないようにする
        assert union_seconds([{"app": "a", "seconds": 600}]) == 600

    def test_空なら0(self):
        assert union_seconds([]) == 0

    def test_区間の統合(self):
        from datetime import datetime as dt
        intervals = [
            (dt(2026, 8, 23, 9), dt(2026, 8, 23, 10)),
            (dt(2026, 8, 23, 9, 30), dt(2026, 8, 23, 11)),
            (dt(2026, 8, 23, 12), dt(2026, 8, 23, 13)),
        ]
        assert merge_intervals(intervals) == [
            (dt(2026, 8, 23, 9), dt(2026, 8, 23, 11)),
            (dt(2026, 8, 23, 12), dt(2026, 8, 23, 13)),
        ]


class TestSummarize:
    """アプリ別の合計"""

    def test_totals_are_sorted_by_duration(self):
        timeline = [
            {"app": "chrome.exe", "seconds": 600},
            {"app": "code.exe", "seconds": 1800},
            {"app": "chrome.exe", "seconds": 300},
        ]

        assert summarize(timeline) == [
            {"app": "code.exe", "seconds": 1800, "devices": ["pc"]},
            {"app": "chrome.exe", "seconds": 900, "devices": ["pc"]},
        ]

    def test_同じアプリを複数の端末で使った場合は合算する(self):
        timeline = [
            {"app": "YouTube", "seconds": 600, "device": "pc"},
            {"app": "YouTube", "seconds": 1800, "device": "android"},
        ]

        # 使用時間の多い端末が先に並ぶ
        assert summarize(timeline) == [
            {"app": "YouTube", "seconds": 2400, "devices": ["android", "pc"]},
        ]

    def test_端末の指定が無い区間はPCとして扱う(self):
        timeline = [{"app": "code.exe", "seconds": 60}]
        assert summarize(timeline)[0]["devices"] == ["pc"]

    def test_empty_timeline(self):
        assert summarize([]) == []


class TestSecondsSinceMidnight:
    """0時からの経過秒数"""

    def test_midnight(self):
        assert seconds_since_midnight(parse_time("2026-08-14 00:00:00")) == 0

    def test_noon(self):
        assert seconds_since_midnight(parse_time("2026-08-14 12:00:00")) == 12 * 3600

    def test_with_minutes_and_seconds(self):
        assert seconds_since_midnight(parse_time("2026-08-14 09:30:45")) == 9 * 3600 + 30 * 60 + 45


class TestDaySummary:
    """その日の要約"""

    def build(self, sessions, previous_total=0):
        timeline = build_timeline(sessions, min_seconds=30, gap_seconds=60)
        return day_summary(timeline, previous_total)

    def test_start_and_end(self):
        summary = self.build([
            session("chrome.exe", "08:42:00", "09:35:00"),
            session("code.exe", "14:00:00", "16:48:00"),
        ])

        assert summary["start"] == "08:42"
        assert summary["end"] == "16:48"

    def test_longest_session(self):
        summary = self.build([
            session("chrome.exe", "08:42:00", "09:35:00"),
            session("code.exe", "14:00:00", "16:48:00"),
        ])

        assert summary["longest"]["app"] == "code.exe"
        assert summary["longest"]["seconds"] == 2 * 3600 + 48 * 60

    def test_total_and_diff(self):
        summary = self.build([session("chrome.exe", "09:00:00", "10:00:00")], previous_total=1800)

        assert summary["total"] == 3600
        assert summary["previous_total"] == 1800
        assert summary["diff"] == 1800

    def test_negative_diff(self):
        summary = self.build([session("chrome.exe", "09:00:00", "09:30:00")], previous_total=3600)

        assert summary["diff"] == -1800

    def test_end_uses_the_latest_finish(self):
        # 開始順と終了順が一致しない場合でも、最後に終わった時刻を返す
        summary = self.build([
            session("a.exe", "09:00:00", "12:00:00"),
            session("b.exe", "10:00:00", "10:30:00"),
        ])

        assert summary["end"] == "12:00"

    def test_empty_day(self):
        summary = self.build([], previous_total=3600)

        assert summary["total"] == 0
        assert summary["start"] is None
        assert summary["longest"] is None
        assert summary["diff"] == -3600


class TestHourlyUsage:
    """1時間ごとの振り分け"""

    def test_session_within_one_hour(self):
        hours = hourly_usage([session("chrome.exe", "09:10:00", "09:40:00")])

        assert hours[9] == 1800
        assert sum(hours) == 1800

    def test_session_spanning_hours(self):
        hours = hourly_usage([session("chrome.exe", "09:40:00", "11:10:00")])

        assert hours[9] == 1200
        assert hours[10] == 3600
        assert hours[11] == 600

    def test_multiple_sessions_accumulate(self):
        hours = hourly_usage([
            session("chrome.exe", "09:00:00", "09:20:00"),
            session("code.exe", "09:30:00", "09:50:00"),
        ])

        assert hours[9] == 2400

    def test_always_returns_24_values(self):
        assert len(hourly_usage([])) == 24
        assert sum(hourly_usage([])) == 0

    def test_late_night_session(self):
        hours = hourly_usage([session("chrome.exe", "23:30:00", "23:59:00")])

        assert hours[23] == 1740


class TestRecentDates:
    """対象の日付"""

    def test_returns_requested_count(self):
        assert len(recent_dates(30)) == 30

    def test_newest_first(self):
        dates = recent_dates(3)

        assert dates[0] > dates[1] > dates[2]


class TestBuildHistory:
    """履歴の組み立て"""

    def test_days_without_records_are_kept(self):
        dates = ["2026-08-14", "2026-08-13", "2026-08-12"]
        sessions = [session("chrome.exe", "09:00:00", "10:00:00")]  # 8/14 のみ

        history = build_history(sessions, dates)

        assert [row["date"] for row in history] == dates
        assert history[0]["total"] == 3600
        assert history[1]["total"] == 0
        assert history[2]["total"] == 0

    def test_each_row_has_24_hours(self):
        history = build_history([], recent_dates(5))

        assert all(len(row["hours"]) == 24 for row in history)

    def test_sessions_outside_range_are_ignored(self):
        sessions = [session("chrome.exe", "09:00:00", "10:00:00")]  # 8/14

        history = build_history(sessions, ["2026-08-20", "2026-08-19"])

        assert all(row["total"] == 0 for row in history)
