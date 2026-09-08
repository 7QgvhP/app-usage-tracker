"""
helpers.py - APIの各ルートが共通で使う道具

Flaskの current_app から部品を取り出す入口と、入力の検証、
応答の組み立てをまとめている。ルート本体は各モジュールに置く。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from flask import current_app, request
from werkzeug.exceptions import BadRequest

from app.storage import VALID_PERIODS, UsageStore, today_str

# 画面が表示する期間と、APIが一度に返せる上限
HISTORY_DAYS = 30
MAX_HISTORY_DAYS = 180


def _store() -> UsageStore:
    return current_app.config["STORE"]


def _tracker():
    return current_app.config["TRACKER"]


def _mini_window():
    return current_app.config.get("MINI_WINDOW")


def _to_usage_list(
    usage: dict[str, int],
    limits: dict[str, int] | None = None,
    by_device: list[dict] | None = None,
) -> list[dict]:
    """使用時間の辞書を、使用時間の多い順のリストへ変換する

    by_device を渡すと、アプリごとに「どの端末で使ったか」を添える。
    """
    breakdown: dict[str, dict[str, int]] = {}
    for row in by_device or []:
        breakdown.setdefault(row["app_name"], {})[row["device"]] = row["seconds"]

    result = []
    for app_name, seconds in sorted(usage.items(), key=lambda item: -item[1]):
        entry = {
            "app": app_name,
            "seconds": seconds,
            "minutes": round(seconds / 60, 1),
        }
        if limits is not None:
            entry["limit"] = limits.get(app_name)
        if by_device is not None:
            per_device = breakdown.get(app_name, {})
            # 使用時間の多い端末を先に並べる
            entry["devices"] = sorted(per_device, key=lambda d: -per_device[d])
            entry["device_seconds"] = per_device
        result.append(entry)
    return result


def _sync_health() -> list[dict]:
    """端末ごとの受信状況を返す

    しばらく受信が無い端末は stale として示す。スマホ側のOSは
    数日分しかイベントを保持しないため、気付かずにいると記録が失われる。
    """
    config = current_app.config["APP_CONFIG"]
    if not config.sync_enabled:
        return []

    limit = timedelta(hours=config.sync_stale_hours)
    now = datetime.now()
    result = []

    for device, last_seen in sorted(_store().get_device_seen().items()):
        try:
            elapsed = now - datetime.strptime(last_seen, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        result.append(
            {
                "device": device,
                "last_seen": last_seen,
                "elapsed_hours": round(elapsed.total_seconds() / 3600, 1),
                "stale": elapsed > limit,
            }
        )
    return result


def _selected_date() -> str:
    """表示する日付を返す（date の指定が無ければ今日）

    ダッシュボードとタイムラインで日付を切り替えられるようにするため、
    日付に依存するAPIはこの値を基準にする。
    """
    return _normalize_date(request.args.get("date", today_str()))


def _device_labels() -> dict[str, str]:
    """端末名 → 画面表示名の対応表"""
    return current_app.config["APP_CONFIG"].device_labels


# ── 使用時間 ──


def _normalize_date(value: str) -> str:
    """日付を YYYY-MM-DD へ正規化する

    "2026-3-1" のような表記も受け付ける。データベースは0埋めした形式で
    保持しているため、そのまま照会すると何も見つからなくなってしまう。
    """
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        raise BadRequest("date は YYYY-MM-DD 形式で指定してください")


# ── 制限時間 ──


def _checked_period(value: str) -> str:
    """期間の指定を検証して返す（不正なら 400）

    3つのルートが同じ検証をしていたため、ここへ集約した。
    """
    if value not in VALID_PERIODS:
        raise BadRequest(f"period は {' / '.join(VALID_PERIODS)} のいずれかを指定してください")
    return value
