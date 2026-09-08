"""
timeline.py - 使用区間の整形

データベースに記録された使用区間を、そのまま並べると細切れで読みにくいため、
短い中断の結合と、短すぎる区間の除外を行ってから表示用に整える。
時刻の計算のみを行い、データベースにも画面にも依存しない。
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timedelta

from app.storage import LOCAL_DEVICE

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
SECONDS_PER_DAY = 24 * 60 * 60


def parse_time(value: str) -> datetime:
    """"YYYY-MM-DD HH:MM:SS" を datetime へ変換する"""
    return datetime.strptime(value, TIME_FORMAT)


def seconds_since_midnight(moment: datetime) -> int:
    """その日の0時からの経過秒数を返す"""
    return moment.hour * 3600 + moment.minute * 60 + moment.second


def merge_intervals(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """重なり合う区間をひとつにまとめる

    PCとスマホを同時に使っていた時間を二重に数えないために用いる。
    """
    merged: list[list[datetime]] = []

    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    return [(start, end) for start, end in merged]


def union_seconds(sessions: list[dict]) -> int:
    """区間の重なりを除いた実時間を秒で返す

    単純に足すと、PCとスマホを同時に使っていた時間が二重に数えられ、
    1日の合計が24時間を超えてしまう。

    開始・終了の時刻を持たない記録は重なりを判断できないため、
    その秒数はそのまま加える。
    """
    intervals = []
    without_time = 0

    for session in sessions:
        if session.get("started_at") and session.get("ended_at"):
            intervals.append((parse_time(session["started_at"]), parse_time(session["ended_at"])))
        else:
            without_time += int(session.get("seconds", 0))

    merged = sum(int((end - start).total_seconds()) for start, end in merge_intervals(intervals))
    return merged + without_time


def merge_sessions(sessions: list[dict], gap_seconds: int) -> list[dict]:
    """同じアプリが短い間隔で続く区間をまとめる

    ウィンドウを一瞬離れて戻るたびに区間が分かれると読みにくいため、
    gap_seconds 以内の中断は同じ区間として扱う。

    端末が異なる区間は結合しない。PCとスマホで同時に使っていた場合、
    まとめてしまうと重なった時間帯を1つの区間として描いてしまうため。
    """
    merged: list[dict] = []

    for session in sorted(sessions, key=lambda s: s["started_at"]):
        device = session.get("device", LOCAL_DEVICE)
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and previous["app_name"] == session["app_name"]
            and previous["device"] == device
        ):
            gap = (parse_time(session["started_at"]) - parse_time(previous["ended_at"])).total_seconds()
            if 0 <= gap <= gap_seconds:
                previous["ended_at"] = max(previous["ended_at"], session["ended_at"])
                previous["seconds"] += session["seconds"]
                continue

        merged.append(
            {
                "app_name": session["app_name"],
                "device": device,
                "started_at": session["started_at"],
                "ended_at": session["ended_at"],
                "seconds": session["seconds"],
            }
        )

    return merged


def build_timeline(sessions: list[dict], min_seconds: int, gap_seconds: int) -> list[dict]:
    """表示用の使用区間を組み立てる

    結合してから短い区間を除く。位置合わせに使えるよう、その日の0時からの
    経過秒数（offset）と長さ（length）も持たせる。
    """
    result = []

    for session in merge_sessions(sessions, gap_seconds):
        if session["seconds"] < min_seconds:
            continue

        start = parse_time(session["started_at"])
        end = parse_time(session["ended_at"])
        offset = seconds_since_midnight(start)
        # 日付をまたぐ区間は分割済みだが、念のため当日内に収める
        length = max(1, min(int((end - start).total_seconds()), SECONDS_PER_DAY - offset))

        result.append(
            {
                "app": session["app_name"],
                "device": session["device"],
                "start": start.strftime("%H:%M"),
                "end": end.strftime("%H:%M"),
                "started_at": session["started_at"],
                "ended_at": session["ended_at"],
                "seconds": int(session["seconds"]),
                "offset": offset,
                "length": length,
            }
        )

    return result


def summarize(timeline: list[dict]) -> list[dict]:
    """アプリ別の合計時間を、多い順に返す

    同じアプリを複数の端末で使っている場合は合算し、
    どの端末で使ったかを devices に並べる（使用時間の多い順）。
    """
    by_app: dict[str, list[dict]] = {}
    per_device: dict[str, dict[str, int]] = {}

    for item in timeline:
        app = item["app"]
        device = item.get("device", LOCAL_DEVICE)
        by_app.setdefault(app, []).append(item)
        per_device.setdefault(app, {})
        per_device[app][device] = per_device[app].get(device, 0) + item["seconds"]

    # 同じアプリを2台で同時に使っていた場合、その重なりは1回だけ数える
    totals = {app: union_seconds(items) for app, items in by_app.items()}

    return [
        {
            "app": app,
            "seconds": seconds,
            "devices": sorted(per_device[app], key=lambda d: -per_device[app][d]),
        }
        for app, seconds in sorted(totals.items(), key=lambda item: -item[1])
    ]


def day_summary(timeline: list[dict], previous_total: int = 0) -> dict:
    """その日の要約（開始・終了・最長の区間・前日との差）を返す

    timeline は build_timeline の結果（開始時刻順）を渡す。
    """
    if not timeline:
        return {
            "total": 0,
            "start": None,
            "end": None,
            "longest": None,
            "previous_total": previous_total,
            "diff": -previous_total,
        }

    # 同時に使っていた時間を二重に数えないよう、重なりを除いた実時間を用いる
    total = union_seconds(timeline)
    longest = max(timeline, key=lambda item: item["seconds"])

    return {
        "total": total,
        "start": timeline[0]["start"],
        # 最後に終わった区間の時刻（開始順とは限らないため最大値を取る）
        "end": max(item["ended_at"] for item in timeline)[11:16],
        "longest": {
            "app": longest["app"],
            "start": longest["start"],
            "end": longest["end"],
            "seconds": longest["seconds"],
        },
        "previous_total": previous_total,
        "diff": total - previous_total,
    }


# ── 過去の記録（日 × 時間）──


def hourly_usage(sessions: list[dict]) -> list[int]:
    """1日分の使用区間を、0時〜23時の各1時間へ秒数として振り分ける

    1つの区間が複数の時間帯にまたがる場合は、重なった分だけ各時間へ加算する。
    """
    hours = [0] * 24

    intervals = []
    for session in sessions:
        start = parse_time(session["started_at"])
        end = parse_time(session["ended_at"])
        # 日付をまたぐ区間は分割済みだが、念のため当日内に収める
        end = min(end, start.replace(hour=23, minute=59, second=59) + timedelta(seconds=1))
        if end > start:
            intervals.append((start, end))

    # 重なりを除いてから割り振る。1つの時間帯が3600秒を超えないようにするため
    for start, end in merge_intervals(intervals):
        cursor = start
        while cursor < end:
            next_hour = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            slice_end = min(end, next_hour)
            hours[cursor.hour] += int((slice_end - cursor).total_seconds())
            cursor = slice_end

    return hours


def recent_dates(days: int, today: date_type | None = None) -> list[str]:
    """今日を含む直近 days 日の日付を、新しい順で返す"""
    base = today or datetime.now().date()
    return [(base - timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(days)]


def build_history(sessions: list[dict], dates: list[str]) -> list[dict]:
    """日付ごとに、1時間ごとの使用秒数と合計を組み立てる

    記録のない日も 0 の行として残し、表が途切れないようにする。
    """
    by_date: dict[str, list[dict]] = {date: [] for date in dates}
    for session in sessions:
        day = session["started_at"][:10]
        if day in by_date:
            by_date[day].append(session)

    history = []
    for date in dates:
        hours = hourly_usage(by_date[date])
        history.append({"date": date, "hours": hours, "total": sum(hours)})
    return history
