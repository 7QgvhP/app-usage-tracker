"""
limits.py - 制限時間のルート

設定を変えたときは、通知を出すトラッカーへ知らせる必要がある。
"""

from __future__ import annotations

from flask import jsonify, request
from werkzeug.exceptions import BadRequest

from app.web.api.blueprint import api_bp
from app.web.api.helpers import _store, _tracker


@api_bp.route("/limits", methods=["GET"])
def get_limits():
    """制限時間設定の一覧"""
    limits = _store().get_limits_by_name()
    return jsonify([{"app": app_name, "minutes": minutes} for app_name, minutes in limits.items()])


@api_bp.route("/limits", methods=["POST"])
def set_limit():
    """制限時間を設定する（0以下を指定した場合は解除）"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadRequest("JSON形式のリクエストが必要です")

    app_name = str(data.get("app", "")).strip()
    minutes_raw = data.get("minutes")

    if not app_name or minutes_raw is None:
        raise BadRequest("app と minutes は必須です")

    try:
        minutes = int(minutes_raw)
    except (TypeError, ValueError):
        raise BadRequest("minutes は整数で指定してください")

    store = _store()
    if minutes <= 0:
        store.remove_limit(app_name)
    else:
        store.set_limit(app_name, minutes)

    _notify_limits_changed()
    return jsonify({"ok": True, "app": app_name, "minutes": max(0, minutes)})


@api_bp.route("/limits/<path:app_name>", methods=["DELETE"])
def delete_limit(app_name: str):
    """制限時間を削除する"""
    _store().remove_limit(app_name)
    _notify_limits_changed()
    return jsonify({"ok": True, "app": app_name})


def _notify_limits_changed() -> None:
    """制限設定の変更をトラッカーへ伝え、キャッシュを更新させる"""
    tracker = _tracker()
    if tracker is not None:
        tracker.notify_limits_changed()


# ── トラッカーの状態 ──
