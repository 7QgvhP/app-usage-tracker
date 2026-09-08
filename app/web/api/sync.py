"""
sync.py - スマホからの受信のルート

この配下だけがLANへ公開される（アクセス制御は app/web/__init__.py）。
"""

from __future__ import annotations

from flask import current_app, jsonify, request
from werkzeug.exceptions import BadRequest

from app.storage import now_str
from app.sync import ValidationError, normalize_sessions, validate_device
from app.web.api.blueprint import api_bp
from app.web.api.helpers import _store


@api_bp.route("/sync/usage", methods=["POST"])
def sync_usage():
    """外部端末（スマホ）の使用区間を受け取る

    認証は create_app() の before_request で済ませているため、
    ここでは内容の検証と取り込みだけを行う。
    同じ external_id の区間は無視されるので、何度送っても二重にならない。
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise BadRequest("JSONオブジェクトを送信してください")

    config = current_app.config["APP_CONFIG"]
    try:
        device = validate_device(payload.get("device"))
        sessions = normalize_sessions(payload.get("sessions"), config.sync_max_sessions)
    except ValidationError as e:
        raise BadRequest(str(e)) from e

    store = _store()
    # 送るものが無くても、届いていること自体を記録する
    store.touch_device(device)

    if not sessions:
        return jsonify({"accepted": 0, "skipped": 0, "dates": [], "device": device})

    result = store.import_sessions(device, sessions)
    return jsonify({**result, "device": device})


@api_bp.route("/sync/info")
def sync_info():
    """同期の状態を返す（接続確認にも使う）"""
    config = current_app.config["APP_CONFIG"]
    return jsonify(
        {
            "ok": True,
            "version": current_app.config["APP_VERSION"],
            "max_sessions_per_request": config.sync_max_sessions,
            "server_time": now_str(),
        }
    )
