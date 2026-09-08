"""
timeline.py - 使用時刻と履歴のルート

/timeline       … 1日の使用区間と、時間帯ごとの集計
/timeline/dates … 記録のある日の一覧
/history        … 直近30日分の「日 × 時間帯」
"""

from __future__ import annotations

from datetime import datetime, timedelta

from flask import current_app, jsonify, request
from werkzeug.exceptions import BadRequest

from app.storage import UsageStore, today_str
from app.timeline import build_history, build_timeline, day_summary, recent_dates, summarize
from app.web.api.blueprint import api_bp
from app.web.api.helpers import (
    HISTORY_DAYS,
    MAX_HISTORY_DAYS,
    _normalize_date,
    _store,
)


@api_bp.route("/timeline")
def get_timeline():
    """指定した日の使用区間を返す（日付の省略時は今日）"""
    date = _normalize_date(request.args.get("date", today_str()))

    config = current_app.config["APP_CONFIG"]
    store = _store()
    timeline = _build_day(store, date, config)

    # 前日との比較のため、前日の合計も求める
    previous = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    previous_total = sum(item["seconds"] for item in _build_day(store, previous, config))

    return jsonify(
        {
            "date": date,
            "sessions": timeline,
            "totals": summarize(timeline),
            "summary": day_summary(timeline, previous_total),
        }
    )


def _build_day(store: UsageStore, date: str, config) -> list[dict]:
    """指定日の使用区間を、表示用に整形して返す"""
    return build_timeline(
        store.get_sessions(date, device=None),
        min_seconds=config.timeline_min_session_seconds,
        gap_seconds=config.timeline_merge_gap_seconds,
    )


@api_bp.route("/history")
def get_history():
    """直近の日ごと・1時間ごとの使用時間を返す（ヒートマップ用）

    app を指定すると、そのアプリだけの推移になる。
    選べる候補として、期間内に記録のあるアプリの一覧も返す。
    """
    try:
        days = int(request.args.get("days", HISTORY_DAYS))
    except (TypeError, ValueError):
        raise BadRequest("days は整数で指定してください")

    days = min(max(days, 1), MAX_HISTORY_DAYS)
    dates = recent_dates(days)
    sessions = _store().get_sessions_range(dates[-1], dates[0], device=None)

    # 候補は絞り込む前の全体から作る（選んだあとも一覧が減らないようにする）
    totals: dict[str, int] = {}
    for session in sessions:
        totals[session["app_name"]] = totals.get(session["app_name"], 0) + session["seconds"]
    apps = sorted(totals, key=lambda name: -totals[name])

    app = request.args.get("app", "").strip()
    if app:
        sessions = [s for s in sessions if s["app_name"] == app]

    return jsonify(
        {
            "days": days,
            "start": dates[-1],
            "end": dates[0],
            "app": app,
            "apps": apps,
            "rows": build_history(sessions, dates),
        }
    )


@api_bp.route("/timeline/dates")
def get_timeline_dates():
    """使用区間が記録されている日付の一覧（新しい順）"""
    return jsonify(_store().get_session_dates(device=None))
