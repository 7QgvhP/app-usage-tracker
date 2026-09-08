"""
sync.py - 外部端末（スマホ）からの受信データの検証

通信そのものは Flask 側が担当し、ここでは共有トークンの管理と、
受け取った内容の検証・整形だけを行う純粋な処理を置く。
"""

from __future__ import annotations

import logging
import os
import re
import secrets
from datetime import datetime

logger = logging.getLogger(__name__)

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# 端末名に使える文字（データベースの絞り込みキーになるため厳しめに制限する）
DEVICE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")

# 1件あたりの上限。異常な値でデータベースを膨らませないための歯止め
MAX_APP_NAME_LENGTH = 200
MAX_EXTERNAL_ID_LENGTH = 200
# 24時間を超える区間は日付をまたいでおり、送信側の組み立て誤りとみなす
MAX_SESSION_SECONDS = 24 * 60 * 60


class ValidationError(ValueError):
    """受信データの内容が不正な場合に送出される例外"""


# ── 共有トークン ──


def load_or_create_token(path: str) -> str:
    """同期用の共有トークンを読み込む（無ければ生成して保存する）

    設定ファイルは画面共有などで映る可能性があるため、トークンは
    config.json とは別のファイルへ置く。
    """
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                token = f.read().strip()
            if token:
                return token
            logger.warning(f"トークンファイルが空のため作り直します: {path}")
        except OSError as e:
            raise OSError(f"トークンファイルを読み込めませんでした ({path}): {e}") from e

    token = secrets.token_urlsafe(24)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(token + "\n")
    logger.info(f"同期用のトークンを生成しました: {path}")
    return token


# ── 受信データの検証 ──


def validate_device(name: object) -> str:
    """端末名を検証して返す

    'pc' はこのPC自身の記録を指す予約語のため、受け入れない。
    """
    if not isinstance(name, str):
        raise ValidationError("device は文字列で指定してください")

    device = name.strip().lower()
    if device == "pc":
        raise ValidationError("device に 'pc' は指定できません（このPCの記録用に予約されています）")
    if not DEVICE_PATTERN.match(device):
        raise ValidationError(
            "device は英小文字・数字・ハイフン・アンダースコアの1〜32文字で指定してください"
        )
    return device


def _parse_time(value: object, field: str, index: int) -> datetime:
    """時刻文字列を datetime へ変換する"""
    if not isinstance(value, str):
        raise ValidationError(f"{index}番目の {field} は文字列で指定してください")
    try:
        return datetime.strptime(value.strip(), TIME_FORMAT)
    except ValueError:
        raise ValidationError(
            f"{index}番目の {field} の形式が不正です（YYYY-MM-DD HH:MM:SS）: {value}"
        ) from None


def normalize_session(raw: object, index: int) -> dict:
    """使用区間1件を検証し、データベースへ渡せる形へ整える"""
    if not isinstance(raw, dict):
        raise ValidationError(f"{index}番目の要素がオブジェクトではありません")

    app_name = raw.get("app_name")
    if not isinstance(app_name, str) or not app_name.strip():
        raise ValidationError(f"{index}番目の app_name が空です")
    app_name = app_name.strip()[:MAX_APP_NAME_LENGTH]

    external_id = raw.get("external_id")
    if not isinstance(external_id, str) or not external_id.strip():
        raise ValidationError(f"{index}番目の external_id が空です")
    external_id = external_id.strip()[:MAX_EXTERNAL_ID_LENGTH]

    started = _parse_time(raw.get("started_at"), "started_at", index)
    ended = _parse_time(raw.get("ended_at"), "ended_at", index)
    if ended < started:
        raise ValidationError(f"{index}番目の ended_at が started_at より前です")

    span = int((ended - started).total_seconds())
    if span > MAX_SESSION_SECONDS:
        raise ValidationError(f"{index}番目の区間が24時間を超えています")

    try:
        seconds = int(raw.get("seconds", span))
    except (TypeError, ValueError):
        raise ValidationError(f"{index}番目の seconds は整数で指定してください") from None
    if seconds < 0:
        raise ValidationError(f"{index}番目の seconds が負の値です")
    # 無操作時間を差し引いた値は許すが、区間の長さは超えられない
    if seconds > span:
        raise ValidationError(f"{index}番目の seconds が区間の長さ（{span}秒）を超えています")

    return {
        "date": started.strftime("%Y-%m-%d"),
        "app_name": app_name,
        "started_at": started.strftime(TIME_FORMAT),
        "ended_at": ended.strftime(TIME_FORMAT),
        "seconds": seconds,
        "external_id": external_id,
    }


def normalize_sessions(raw: object, max_count: int) -> list[dict]:
    """使用区間の配列をまとめて検証する"""
    if not isinstance(raw, list):
        raise ValidationError("sessions は配列で指定してください")
    if len(raw) > max_count:
        raise ValidationError(f"一度に送れる区間は {max_count} 件までです（{len(raw)} 件）")

    return [normalize_session(item, index) for index, item in enumerate(raw)]
