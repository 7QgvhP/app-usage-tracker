"""
usage.py - 使用時間のルート

/usage/today  … 指定日のアプリ別（全端末の合算・制限つき）
/usage/summary… 指定期間の実時間・アプリ数・超過数・前の期間との増減
/usage/<期間> … 日 / 週 / 月の集計
/usage/daily-breakdown … 日別×アプリ別
"""

from __future__ import annotations

from datetime import datetime, timedelta

from flask import jsonify, request

from app.storage import LOCAL_DEVICE, UsageStore, get_period_dates
from app.timeline import union_seconds
from app.web.api.blueprint import api_bp
from app.web.api.helpers import (
    _checked_period,
    _selected_date,
    _store,
    _to_usage_list,
)


@api_bp.route("/usage/today")
def get_today_usage():
    """指定日の使用時間（全端末の合算・制限設定つき）

    date を省略すると今日。画面の日付切り替えで過去の日も見られる。
    """
    store = _store()
    date = _selected_date()
    return jsonify(
        _to_usage_list(
            store.get_usage_by_range(date, date, device=None),
            store.get_limits_by_name(),
            store.get_usage_by_device(date, date),
        )
    )


@api_bp.route("/usage/summary")
def get_usage_summary():
    """指定期間の実時間・アプリ数・超過数を返す

    アプリ別の合計を足し上げると、PCとスマホを同時に使っていた時間が
    二重に数えられる。ここでは重なりを除いた実時間を返す。

    period（day / week / month）を指定すると、その期間で集計する。
    画面の統計欄をグラフの期間へ合わせるために用いる。
    """
    period = request.args.get("period", "day")
    period = _checked_period(period)

    base = datetime.strptime(_selected_date(), "%Y-%m-%d").date()
    start, end = get_period_dates(period, base, limit=datetime.now().date())
    store = _store()

    per_device: dict[str, int] = {}
    for row in store.get_usage_by_device(start, end):
        per_device[row["device"]] = per_device.get(row["device"], 0) + row["seconds"]

    actual = _actual_seconds(store, start, end)
    simple = sum(per_device.values())

    # 1つ前の期間との比較。増減が分かるようにする
    previous_start, previous_end = _previous_range(period, start, end)
    previous = _actual_seconds(store, previous_start, previous_end)

    return jsonify(
        {
            "period": period,
            "date": end,
            "start": start,
            "end": end,
            "total_seconds": actual,
            "simple_total_seconds": simple,
            "overlap_seconds": max(0, simple - actual),
            "devices": per_device,
            "app_count": len(store.get_usage_by_range(start, end, device=None)),
            "over_limit_count": _count_over_limit(store, start, end),
            "previous_start": previous_start,
            "previous_end": previous_end,
            "previous_seconds": previous,
            "diff_seconds": actual - previous,
        }
    )


def _actual_seconds(store: UsageStore, start: str, end: str) -> int:
    """期間中の実時間を返す（同時に使っていた重なりを除いた秒数）

    日をまたぐ重なりは無いため、日ごとに重なりを除いてから足し合わせる。
    """
    by_date: dict[str, list] = {}
    for session in store.get_sessions_range(start, end, device=None):
        by_date.setdefault(session["date"], []).append(session)
    return sum(union_seconds(items) for items in by_date.values())


def _previous_range(period: str, start: str, end: str) -> tuple[str, str]:
    """比較用に、1つ前の期間から同じ日数だけ切り出す

    今の期間は途中であることが多い（週の途中など）。前の期間を丸ごと比べると
    日数が違うぶん増えて見えるため、経過日数を揃えて同じ長さで比べる。

    ただし前の期間より長くは取らない。月の日数は揃わないため、
    31日の月と2月を比べると翌月へはみ出してしまう。
    """
    start_date = datetime.strptime(start, "%Y-%m-%d").date()
    end_date = datetime.strptime(end, "%Y-%m-%d").date()
    days = (end_date - start_date).days + 1

    # 今の期間の前日を含む期間が、1つ前の期間にあたる
    previous_start, previous_last = get_period_dates(period, start_date - timedelta(days=1))
    base = datetime.strptime(previous_start, "%Y-%m-%d").date()
    limit = datetime.strptime(previous_last, "%Y-%m-%d").date()
    return previous_start, min(base + timedelta(days=days - 1), limit).strftime("%Y-%m-%d")


def _count_over_limit(store: UsageStore, start: str, end: str) -> int:
    """期間中に制限を超えたアプリの数を返す

    制限は1日あたりの時間なので、日ごとに判定し、
    1日でも超えたアプリを数える。

    判定はこのPCの使用時間だけで行う。通知を出すトラッカーが
    PCの使用時間で判定しているため、画面と食い違わないようにする。
    """
    # 突き合わせは照合キーで行う。表示名は見た行によって変わるため
    limits = store.get_limits()
    if not limits:
        return 0

    exceeded = {
        row["app_key"]
        for row in store.get_daily_seconds_by_key(start, end, device=LOCAL_DEVICE)
        if row["app_key"] in limits and row["seconds"] / 60 >= limits[row["app_key"]]
    }
    return len(exceeded)


@api_bp.route("/usage/daily-breakdown")
def get_daily_breakdown():
    """日別×アプリ別の使用時間"""
    period = request.args.get("period", "week")
    period = _checked_period(period)

    start, end = get_period_dates(period, limit=datetime.now().date())
    return jsonify(_store().get_daily_breakdown(start, end, device=None))


@api_bp.route("/usage/<period>")
def get_usage_by_period(period: str):
    """期間別の使用時間（day / week / month）

    画面の見出しに対象期間を出すため、集計と一緒に開始日・終了日も返す。
    期間の区切り方（週は月曜始まり・月は1日始まり）をサーバー側だけで
    決められるようにするため、画面側では計算しない。
    """
    period = _checked_period(period)

    # 選んだ日を含む期間を求める。まだ来ていない日付は含めない
    base = datetime.strptime(_selected_date(), "%Y-%m-%d").date()
    start, end = get_period_dates(period, base, limit=datetime.now().date())
    store = _store()
    return jsonify(
        {
            "period": period,
            "start": start,
            "end": end,
            "apps": _to_usage_list(
                store.get_usage_by_range(start, end, device=None),
                by_device=store.get_usage_by_device(start, end),
            ),
        }
    )


# ── 使用時刻（タイムライン） ──
