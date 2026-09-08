"""
logging_setup.py - ログ出力の初期化

ファイルへのローテーション出力と、コンソールへの出力を設定する。
pythonw.exe での実行時は stdout/stderr が None になるため、その場合は
ファイル出力のみとする。
"""

from __future__ import annotations

import io
import logging
import sys
from logging.handlers import RotatingFileHandler

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def _ensure_utf8(stream):
    """標準ストリームをUTF-8へ切り替える（絵文字等での文字化け防止）"""
    if stream is None:
        return None
    try:
        if getattr(stream, "encoding", "").lower() not in ("utf-8", "utf8"):
            return io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        # buffer を持たないストリームは変換せずそのまま使う
        return stream
    return stream


def setup_logging(
    log_path: str,
    level: str = "INFO",
    max_bytes: int = 1024 * 1024,
    backup_count: int = 3,
) -> None:
    """ルートロガーを初期化する

    Args:
        log_path: ログファイルの絶対パス
        level: ログレベル名（INFO / DEBUG など）
        max_bytes: 1ファイルあたりの最大サイズ
        backup_count: 保持する世代数
    """
    handlers: list[logging.Handler] = []

    try:
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        handlers.append(file_handler)
    except OSError as e:
        # ファイルを開けない場合でもコンソール出力だけで起動を継続する
        print(f"ログファイルを開けませんでした: {e}", file=sys.stderr)

    sys.stdout = _ensure_utf8(sys.stdout)
    sys.stderr = _ensure_utf8(sys.stderr)
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))

    log_level = getattr(logging, level, logging.INFO)
    if not isinstance(log_level, int):
        log_level = logging.INFO

    logging.basicConfig(level=log_level, format=LOG_FORMAT, handlers=handlers, force=True)

    # waitress のアクセスログは冗長なため警告以上のみ表示する
    logging.getLogger("waitress").setLevel(logging.WARNING)
