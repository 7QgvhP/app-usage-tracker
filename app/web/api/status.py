"""
status.py - 稼働状態と操作のルート

/status            … 計測の状態、端末、同期の健全性
/mini-window/show  … 小型ウィンドウの表示要求
/toggle-pause      … 計測の一時停止と再開
"""

from __future__ import annotations

from flask import current_app, jsonify

from app.storage import LOCAL_DEVICE
from app.web.api.blueprint import api_bp
from app.web.api.helpers import (
    _device_labels,
    _mini_window,
    _sync_health,
    _tracker,
)


@api_bp.route("/status")
def get_status():
    """トラッカーの状態"""
    tracker = _tracker()
    mini_window = _mini_window()
    return jsonify(
        {
            "paused": bool(tracker.is_paused) if tracker else False,
            "available": tracker is not None,
            "version": current_app.config["APP_VERSION"],
            "devices": _device_labels(),
            "local_device": LOCAL_DEVICE,
            "sync": _sync_health(),
            "mini_window": {
                "available": mini_window is not None,
                "visible": bool(mini_window.visible) if mini_window else False,
            },
        }
    )


@api_bp.route("/mini-window/show", methods=["POST"])
def show_mini_window():
    """ミニウィンドウの表示を要求する

    tkinter はメインスレッドでしか扱えないため、ここでは要求を登録するだけで、
    実際の表示はメインスレッドが行う。
    """
    mini_window = _mini_window()
    if mini_window is None:
        return jsonify({"ok": False, "available": False, "visible": False})

    if mini_window.visible:
        return jsonify({"ok": True, "available": True, "visible": True, "requested": False})

    mini_window.request_show()
    return jsonify({"ok": True, "available": True, "visible": False, "requested": True})


@api_bp.route("/toggle-pause", methods=["POST"])
def toggle_pause():
    """計測の一時停止／再開を切り替える"""
    tracker = _tracker()
    if tracker is None:
        return jsonify({"paused": False, "available": False})

    if tracker.is_paused:
        tracker.resume()
    else:
        tracker.pause()

    return jsonify({"paused": tracker.is_paused, "available": True})


@api_bp.route("/notion/send", methods=["POST"])
def notion_send():
    """未送信の日を Notion へ登録する（画面やテストからの手動実行）

    日付が変わったときの自動送信と同じ処理を、待たずに動かすためのもの。
    """
    publisher = current_app.config.get("NOTION")
    if publisher is None:
        return jsonify({"ok": False, "reason": "Notion連携が組み込まれていません"}), 503

    reason = publisher.reason_unavailable()
    if reason:
        return jsonify({"ok": False, "reason": reason}), 400

    pending = publisher.pending_dates()
    sent = publisher.run_pending()
    return jsonify({"ok": True, "sent": sent, "pending": pending})
