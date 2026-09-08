"""1日分の記録の組み立て"""

from __future__ import annotations

import pytest

from app.report import (
    DailyReport,
    active_spans,
    build_detail_lines,
    build_report,
    build_summary_text,
    format_duration,
)
from tests.duration_cases import DURATION_CASES

LABELS = {"pc": "PC", "android": "スマホ"}


@pytest.fixture
def filled(store):
    """PCとスマホの記録がある1日を用意する"""
    store.add_session("Claude", "2026-03-02 09:00:00", "2026-03-02 10:00:00", 3600)
    store.add_usage("Claude", 3600, "2026-03-02")
    store.add_session("Chrome", "2026-03-02 21:00:00", "2026-03-02 21:30:00", 1800)
    store.add_usage("Chrome", 1800, "2026-03-02")
    store.import_sessions("android", [{
        "date": "2026-03-02", "app_name": "X (Twitter)",
        "started_at": "2026-03-02 22:00:00", "ended_at": "2026-03-02 22:40:00",
        "seconds": 2400, "external_id": "a:1",
    }])
    return store


class TestFormatDuration:
    """表記は画面・スマホと同じ規則に従う"""

    @pytest.mark.parametrize("seconds,expected", DURATION_CASES)
    def test_共通の仕様どおりに整形する(self, seconds, expected):
        assert format_duration(seconds) == expected


class TestActiveSpans:
    """活動した時間帯のまとめ方"""

    def test_連続する時間帯をまとめる(self):
        hours = [0] * 24
        for h in (9, 10, 11):
            hours[h] = 3600
        assert active_spans(hours) == ["9〜12時"]

    def test_離れた時間帯は別に出す(self):
        hours = [0] * 24
        hours[9] = 3600
        hours[20] = 3600
        hours[21] = 3600
        assert active_spans(hours) == ["9時台", "20〜22時"]

    def test_短い時間は無視する(self):
        """数十秒の切り替えで時間帯が細切れになるのを防ぐ"""
        hours = [0] * 24
        hours[9] = 3600
        hours[14] = 30
        assert active_spans(hours) == ["9時台"]

    def test_記録が無ければ空(self):
        assert active_spans([0] * 24) == []


class TestBuildReport:
    """データベースからの組み立て"""

    def test_記録が無い日は空になる(self, store):
        report = build_report(store, "2026-03-02")
        assert report.is_empty

    def test_合計は重なりを除いた実時間(self, store):
        # 同じ時間帯を2台で使う
        store.add_session("Claude", "2026-03-02 09:00:00", "2026-03-02 10:00:00", 3600)
        store.add_usage("Claude", 3600, "2026-03-02")
        store.import_sessions("android", [{
            "date": "2026-03-02", "app_name": "YouTube",
            "started_at": "2026-03-02 09:00:00", "ended_at": "2026-03-02 10:00:00",
            "seconds": 3600, "external_id": "a:1",
        }])

        report = build_report(store, "2026-03-02")

        assert report.total_seconds == 3600
        assert report.overlap_seconds == 3600

    def test_端末別とアプリ別が入る(self, filled):
        report = build_report(filled, "2026-03-02")

        assert report.device_seconds == {"pc": 5400, "android": 2400}
        assert report.top_app == ("Claude", 3600)
        assert report.app_count == 3

    def test_前日との差が入る(self, filled):
        filled.add_session("Claude", "2026-03-01 09:00:00", "2026-03-01 09:30:00", 1800)

        report = build_report(filled, "2026-03-02")

        assert report.previous_seconds == 1800
        assert report.diff_seconds == report.total_seconds - 1800

    def test_短時間のアプリはアプリ数に数えない(self, store):
        store.add_session("Claude", "2026-03-02 09:00:00", "2026-03-02 10:00:00", 3600)
        store.add_usage("Claude", 3600, "2026-03-02")
        store.add_usage("ShellHost", 30, "2026-03-02")

        assert build_report(store, "2026-03-02").app_count == 1

    def test_アプリごとの時間帯が入る(self, filled):
        report = build_report(filled, "2026-03-02")

        assert report.app_hours["Claude"] == {9: 3600}
        assert report.app_hours["X (Twitter)"] == {22: 2400}


class TestSummaryText:
    """要約の文章"""

    def test_合計と端末の内訳を含む(self, filled):
        text = build_summary_text(build_report(filled, "2026-03-02"), LABELS)

        assert "3月2日（月）は" in text
        assert "2時間10分使用" in text
        assert "PC 1時間30分" in text
        assert "スマホ 40分" in text

    def test_前日の記録が無ければ増減を書かない(self, filled):
        text = build_summary_text(build_report(filled, "2026-03-02"), LABELS)

        assert "前日より" not in text

    def test_前日との増減を書く(self, filled):
        filled.add_session("Claude", "2026-03-01 09:00:00", "2026-03-01 09:30:00", 1800)

        text = build_summary_text(build_report(filled, "2026-03-02"), LABELS)

        assert "前日より1時間40分多い" in text

    def test_活動した時間帯と上位アプリを含む(self, filled):
        text = build_summary_text(build_report(filled, "2026-03-02"), LABELS)

        assert "9時台" in text and "21〜23時" in text
        assert "Claude 1時間" in text

    def test_2000文字に収まる(self, filled):
        """Notion の rich_text の上限を超えない"""
        text = build_summary_text(build_report(filled, "2026-03-02"), LABELS)

        assert len(text) < 2000


class TestDetailLines:
    """本文に載せる内訳"""

    def test_アプリごとに時間帯を添える(self, filled):
        lines = build_detail_lines(build_report(filled, "2026-03-02"))

        assert lines[0] == "Claude 1時間（9時 60分）"

    def test_短時間のアプリは載せない(self, filled):
        filled.add_usage("ShellHost", 30, "2026-03-02")

        lines = build_detail_lines(build_report(filled, "2026-03-02"))

        assert not any("ShellHost" in line for line in lines)
