"""
report.py - 1日分の記録をまとめる

Notion へ送る内容を組み立てる。**送信手段には依存しない**ため、
このモジュールだけで中身を確かめられる。実際の送信は app/notion.py。

数え方は画面と揃える。合計は同時使用の重なりを除いた実時間で、
ダッシュボードの「合計」と一致する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.storage import LOCAL_DEVICE
from app.timeline import hourly_usage, union_seconds

WEEKDAYS = "月火水木金土日"

# 本文の詳細に載せる下限（秒）。切り替えの雑音を落とす
DETAIL_MIN_SECONDS = 300

# アプリ数に数える下限（秒）
COUNT_MIN_SECONDS = 60

# 活動した時間帯とみなす下限（秒／1時間あたり）
ACTIVE_HOUR_SECONDS = 300


@dataclass
class DailyReport:
    """1日分の記録"""

    date: str
    total_seconds: int = 0
    previous_seconds: int = 0
    device_seconds: dict[str, int] = field(default_factory=dict)
    overlap_seconds: int = 0
    app_count: int = 0
    over_limit_count: int = 0
    # (アプリ名, 秒数) を多い順に
    apps: list[tuple[str, int]] = field(default_factory=list)
    # 0時〜23時の使用秒数
    hours: list[int] = field(default_factory=lambda: [0] * 24)
    # アプリ名 → {時: 秒数}
    app_hours: dict[str, dict[int, int]] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """記録が無い日か"""
        return self.total_seconds <= 0

    @property
    def diff_seconds(self) -> int:
        """前日との増減"""
        return self.total_seconds - self.previous_seconds

    @property
    def top_app(self) -> tuple[str, int] | None:
        """最も長く使ったアプリ"""
        return self.apps[0] if self.apps else None


def format_duration(seconds: int) -> str:
    """秒を「9時間10分」の形へ（表記は画面と揃える）"""
    if 0 < seconds < 60:
        return "1分未満"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}分"
    hours, rest = divmod(minutes, 60)
    return f"{hours}時間{rest}分" if rest else f"{hours}時間"


def active_spans(hours: list[int], threshold: int = ACTIVE_HOUR_SECONDS) -> list[str]:
    """使用のあった時間帯を「0〜4時」のように連続でまとめる

    threshold 未満の時間は「使っていない」とみなす。数十秒の切り替えで
    時間帯が細切れになるのを防ぐため。
    """
    active = [i for i, seconds in enumerate(hours) if seconds >= threshold]
    if not active:
        return []

    spans = []
    start = previous = active[0]
    for hour in active[1:]:
        if hour != previous + 1:
            spans.append((start, previous))
            start = hour
        previous = hour
    spans.append((start, previous))

    return [f"{a}〜{b + 1}時" if a != b else f"{a}時台" for a, b in spans]


def build_summary_text(report: DailyReport, device_labels: dict[str, str]) -> str:
    """要約の文章を組み立てる

    生成には言語モデルを使わない。日々の記録は数値がずれてはいけないためで、
    形が毎日そろっていることは、後から読み返すうえでも利点になる。
    """
    target = datetime.strptime(report.date, "%Y-%m-%d").date()
    parts = []

    inner = "・".join(
        f"{device_labels.get(device, device)} {format_duration(seconds)}"
        for device, seconds in sorted(report.device_seconds.items(), key=lambda x: -x[1])
    )
    head = f"{target.month}月{target.day}日（{WEEKDAYS[target.weekday()]}）は{format_duration(report.total_seconds)}使用"
    parts.append(f"{head}（{inner}）。" if inner else f"{head}。")

    if report.previous_seconds > 0:
        diff = report.diff_seconds
        if abs(diff) < 600:
            parts.append("前日とほぼ同じ。")
        else:
            parts.append(f"前日より{format_duration(abs(diff))}{'多い' if diff > 0 else '少ない'}。")

    spans = active_spans(report.hours)
    if spans:
        parts.append(f"{'、'.join(spans)}が中心。")

    top = [(name, sec) for name, sec in report.apps if sec >= DETAIL_MIN_SECONDS][:3]
    if top:
        listed = "、".join(f"{name} {format_duration(sec)}" for name, sec in top)
        parts.append(f"最も長かったのは{listed}。")

    if report.over_limit_count > 0:
        parts.append(f"制限時間を超えたアプリが{report.over_limit_count}件。")

    return "".join(parts)


def build_detail_lines(report: DailyReport, minimum: int = DETAIL_MIN_SECONDS) -> list[str]:
    """アプリごとの「いつ・どれだけ」を1行ずつ組み立てる"""
    lines = []
    for name, total in report.apps:
        if total < minimum:
            continue
        by_hour = report.app_hours.get(name, {})
        slots = [
            f"{hour}時 {seconds // 60}分"
            for hour, seconds in sorted(by_hour.items())
            if seconds >= 60
        ]
        detail = f"（{' / '.join(slots)}）" if slots else ""
        lines.append(f"{name} {format_duration(total)}{detail}")
    return lines


def build_report(store, date: str, config=None) -> DailyReport:
    """データベースから1日分の記録を組み立てる"""
    report = DailyReport(date=date)

    sessions = store.get_sessions(date, device=None)
    report.total_seconds = union_seconds(sessions)
    if report.is_empty:
        return report

    previous = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    report.previous_seconds = union_seconds(store.get_sessions(previous, device=None))

    for row in store.get_usage_by_device(date, date):
        report.device_seconds[row["device"]] = (
            report.device_seconds.get(row["device"], 0) + row["seconds"]
        )
    simple = sum(report.device_seconds.values())
    report.overlap_seconds = max(0, simple - report.total_seconds)

    usage = store.get_usage_by_range(date, date, device=None)
    report.apps = sorted(usage.items(), key=lambda item: -item[1])
    report.app_count = sum(1 for _, seconds in report.apps if seconds >= COUNT_MIN_SECONDS)

    report.hours = hourly_usage(sessions)
    report.app_hours = _app_hours(sessions)
    report.over_limit_count = _count_over_limit(store, date)
    return report


def _app_hours(sessions: list[dict]) -> dict[str, dict[int, int]]:
    """区間を「アプリ → {時: 秒数}」へ振り分ける

    同じアプリの端末間の重なりまでは除かない。1時間あたりの値としては
    多めに出ることがあるが、いつ使ったかを示す用途には足りる。
    """
    result: dict[str, dict[int, int]] = {}
    for session in sessions:
        hour = int(session["started_at"][11:13])
        by_hour = result.setdefault(session["app_name"], {})
        by_hour[hour] = by_hour.get(hour, 0) + session["seconds"]
    return result


def _count_over_limit(store, date: str) -> int:
    """その日に制限時間を超えたアプリの数（判定はこのPCの使用時間で行う）"""
    limits = store.get_limits()
    if not limits:
        return 0

    return sum(
        1
        for row in store.get_daily_seconds_by_key(date, date, device=LOCAL_DEVICE)
        if row["app_key"] in limits and row["seconds"] / 60 >= limits[row["app_key"]]
    )
