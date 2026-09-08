"""
migrations.py - スキーマの定義と移行

PRAGMA user_version を見て、不足している移行だけを順に適用する。
移行はDDLを含むため、明示的なトランザクションで巻き戻せるようにしている。
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from datetime import datetime

from app.storage.constants import LOCAL_DEVICE

logger = logging.getLogger(__name__)

# スキーマのバージョン。_MIGRATIONS を追加したらこの値も上げる
SCHEMA_VERSION = 5

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS usage_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        app_name TEXT NOT NULL,
        app_key TEXT NOT NULL DEFAULT '',
        device TEXT NOT NULL DEFAULT 'pc',
        seconds INTEGER NOT NULL DEFAULT 0,
        UNIQUE(date, app_key, device)
    );
    CREATE TABLE IF NOT EXISTS app_limits (
        app_key TEXT PRIMARY KEY,
        limit_minutes INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS usage_session (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        app_name TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT NOT NULL,
        seconds INTEGER NOT NULL DEFAULT 0,
        device TEXT NOT NULL DEFAULT 'pc',
        external_id TEXT,
        app_key TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS device_seen (
        device TEXT PRIMARY KEY,
        last_seen TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS notion_sync (
        date TEXT PRIMARY KEY,
        page_id TEXT NOT NULL,
        sent_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_usage_date ON usage_log(date);
    CREATE INDEX IF NOT EXISTS idx_usage_app ON usage_log(app_key);
    CREATE INDEX IF NOT EXISTS idx_session_date ON usage_session(date);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_session_external
        ON usage_session(device, external_id) WHERE external_id IS NOT NULL;
"""


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """テーブルが存在するか調べる"""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _migrate_to_v1(conn: sqlite3.Connection) -> None:
    """端末を区別する列を追加する

    usage_log は一意制約を UNIQUE(date, app_name) から
    UNIQUE(date, app_name, device) へ変えるが、SQLite は ALTER TABLE で
    一意制約を変更できないため、作り直して中身を移す。
    既存の記録はすべてこのPCのものとして扱う。
    """
    conn.execute(
        """
        CREATE TABLE usage_log_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            app_name TEXT NOT NULL,
            device TEXT NOT NULL DEFAULT 'pc',
            seconds INTEGER NOT NULL DEFAULT 0,
            UNIQUE(date, app_name, device)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO usage_log_new (id, date, app_name, device, seconds)
        SELECT id, date, app_name, ?, seconds FROM usage_log
        """,
        (LOCAL_DEVICE,),
    )
    # 旧テーブルを消すとインデックスも消えるため、改名後に作り直す
    conn.execute("DROP TABLE usage_log")
    conn.execute("ALTER TABLE usage_log_new RENAME TO usage_log")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_date ON usage_log(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_app ON usage_log(app_name)")

    # usage_session は一意制約が無いため、列の追加だけで済む
    # （この表自体が無い古いDBは、後続の _SCHEMA 適用で最新の形で作られる）
    if _table_exists(conn, "usage_session"):
        conn.execute(f"ALTER TABLE usage_session ADD COLUMN device TEXT NOT NULL DEFAULT '{LOCAL_DEVICE}'")
        conn.execute("ALTER TABLE usage_session ADD COLUMN external_id TEXT")
        # external_id を持つ行（外部から取り込んだ記録）だけを重複禁止にする
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_session_external
            ON usage_session(device, external_id) WHERE external_id IS NOT NULL
            """
        )


def _migrate_to_v2(conn: sqlite3.Connection) -> None:
    """照合用のキーを追加する

    PCとスマホで名前が違う同じアプリを束ねるため、集計の単位を
    app_name から app_key へ移す。usage_log は一意制約を
    UNIQUE(date, app_key, device) へ変えるため作り直す。

    既存の記録のキーは空のままとし、起動時の再計算で埋める。
    """
    conn.execute(
        """
        CREATE TABLE usage_log_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            app_name TEXT NOT NULL,
            app_key TEXT NOT NULL DEFAULT '',
            device TEXT NOT NULL DEFAULT 'pc',
            seconds INTEGER NOT NULL DEFAULT 0,
            UNIQUE(date, app_key, device)
        )
        """
    )
    # 移行時点では app_name をそのままキーとして入れる（起動時に正しい値へ直す）
    conn.execute(
        """
        INSERT INTO usage_log_new (date, app_name, app_key, device, seconds)
        SELECT date, app_name, app_name, device, SUM(seconds)
        FROM usage_log GROUP BY date, app_name, device
        """
    )
    conn.execute("DROP TABLE usage_log")
    conn.execute("ALTER TABLE usage_log_new RENAME TO usage_log")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_date ON usage_log(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_app ON usage_log(app_key)")

    if _table_exists(conn, "usage_session"):
        conn.execute("ALTER TABLE usage_session ADD COLUMN app_key TEXT NOT NULL DEFAULT ''")
        conn.execute("UPDATE usage_session SET app_key = app_name")


def _migrate_to_v3(conn: sqlite3.Connection) -> None:
    """端末から最後に受信した時刻を持つ表を作る

    スマホ側が長く動かないと、OSが保持しなくなった分の記録は
    取り返せない。気付けるようにするため受信時刻を控える。
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS device_seen (
            device TEXT PRIMARY KEY,
            last_seen TEXT NOT NULL
        )
        """
    )


def _migrate_to_v4(conn: sqlite3.Connection) -> None:
    """制限時間を表示名ではなく照合キーで持つ

    表示名で持っていたため、記録される名前と表示名が違うアプリ
    （PCは `chrome.exe`、画面は `Chrome`）では制限が働かなかった。
    通知を出すトラッカーは記録された名前で照合するためである。

    キーの算出は Python 側の規則に依るため、SQL だけでは移せない。
    ここで読み出して変換し、入れ直す。
    """
    from app.naming import normalize_key

    rows = conn.execute("SELECT app_name, limit_minutes FROM app_limits").fetchall()

    converted: dict[str, int] = {}
    for row in rows:
        key = normalize_key(row["app_name"])
        # 別々の表示名が同じキーへ寄る場合は、厳しい方（短い方）を残す
        if key in converted:
            logger.warning(
                f"制限時間が同じアプリへ重なったため短い方を残します: {row['app_name']}"
            )
            converted[key] = min(converted[key], row["limit_minutes"])
        else:
            converted[key] = row["limit_minutes"]

    conn.execute("DROP TABLE app_limits")
    conn.execute(
        """
        CREATE TABLE app_limits (
            app_key TEXT PRIMARY KEY,
            limit_minutes INTEGER NOT NULL
        )
        """
    )
    conn.executemany(
        "INSERT INTO app_limits (app_key, limit_minutes) VALUES (?, ?)",
        sorted(converted.items()),
    )


def _migrate_to_v5(conn: sqlite3.Connection) -> None:
    """Notion へ送信済みの日を控える表を作る

    ページIDも持つことで、送り直すときに検索せず更新できる。
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notion_sync (
            date TEXT PRIMARY KEY,
            page_id TEXT NOT NULL,
            sent_at TEXT NOT NULL
        )
        """
    )


# 添字がそのまま「適用後のバージョン - 1」に対応する
_MIGRATIONS = [
    _migrate_to_v1,
    _migrate_to_v2,
    _migrate_to_v3,
    _migrate_to_v4,
    _migrate_to_v5,
]


def _backup_database(db_path: str) -> None:
    """移行前のデータベースを複製して残す

    複製に失敗しても移行自体は続行できるため、警告のみに留める。
    """
    if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
        return

    backup_path = f"{db_path}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    try:
        shutil.copy2(db_path, backup_path)
        logger.info(f"移行前のデータベースを複製しました: {backup_path}")
    except OSError as e:
        logger.warning(f"データベースの複製に失敗しました（移行は継続します）: {e}")


def _apply_migrations(conn: sqlite3.Connection, db_path: str) -> None:
    """user_version を見て、不足している移行を順に適用する

    新規のデータベースには移行を流さず、最新のスキーマを直接作る。
    """
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])

    # 表が1つも無ければ新規作成とみなす（user_version は両者とも 0 のため）
    if not _table_exists(conn, "usage_log"):
        conn.executescript(_SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
        return

    if version >= SCHEMA_VERSION:
        # 既に最新。表の追加漏れだけ補う
        conn.executescript(_SCHEMA)
        conn.commit()
        return

    _backup_database(db_path)

    # DDL を含む移行を確実に巻き戻せるよう、明示的にトランザクションを制御する
    # （既定の isolation_level では DDL が即時確定してしまう）
    previous = conn.isolation_level
    conn.isolation_level = None
    try:
        for index in range(version, SCHEMA_VERSION):
            target = index + 1
            logger.info(f"データベースをバージョン {target} へ移行します")
            conn.execute("BEGIN")
            try:
                _MIGRATIONS[index](conn)
                conn.execute(f"PRAGMA user_version = {target}")
                conn.execute("COMMIT")
            except sqlite3.Error:
                conn.execute("ROLLBACK")
                raise
            logger.info(f"バージョン {target} への移行が完了しました")
    finally:
        conn.isolation_level = previous

    conn.executescript(_SCHEMA)
    conn.commit()
