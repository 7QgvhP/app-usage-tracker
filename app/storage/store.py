"""
store.py - 使用時間の読み書き

接続はスレッドごとに保持し、Webサーバースレッドと計測スレッドから
安全に利用できるようにしている。

記録された名前は、対応表（app/naming.py）で束ねてから返す。
"""

from __future__ import annotations

import functools
import inspect
import logging
import os
import sqlite3
import threading

from app.storage.constants import LOCAL_DEVICE
from app.storage.display import DisplayNames
from app.storage.dates import now_str, today_str
from app.storage.migrations import _apply_migrations

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """データベース操作に失敗した場合に送出される例外"""


def _guard(message: str):
    """SQLite の例外をログへ残し、StorageError へ変換するデコレータ

    どのメソッドも「失敗したらログを出して StorageError にする」という
    同じ扱いをするため、その定型をここへ集約している。

    message には引数の名前を波括弧で埋め込める（例: "記録に失敗 ({app_name})"）。
    展開は失敗したときだけ行うため、通常の呼び出しに負担は無い。
    """

    def decorate(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except sqlite3.Error as e:
                logger.error(f"{_describe(message, func, args, kwargs)}: {e}")
                raise StorageError(str(e)) from e

        return wrapper

    return decorate


def _describe(message: str, func, args, kwargs) -> str:
    """メッセージ中の {引数名} を実際の値へ置き換える

    値の取得に失敗しても、元の失敗を隠さないよう雛形のまま返す。
    """
    try:
        bound = inspect.signature(func).bind(*args, **kwargs)
        bound.apply_defaults()
        return message.format(**bound.arguments)
    except Exception:
        return message


# ── スキーマ移行 ──


class UsageStore:
    """使用時間と制限設定を管理するデータストア"""

    def __init__(self, db_path: str, names=None):
        """
        Args:
            names: アプリ名の対応表（AppNameRegistry）。省略時は規則だけで照合する
        """
        self.db_path = db_path
        # 記録された名前とキー・表示名の対応は DisplayNames が受け持つ
        self._names = DisplayNames(names)
        self._local = threading.local()
        self._all_connections: list[sqlite3.Connection] = []
        self._lock = threading.Lock()
        # スキーマの用意は最初の接続でのみ行う（複数スレッドからの二重実行を防ぐ）
        self._schema_ready = False

    # ── 接続管理 ──

    def _connect(self) -> sqlite3.Connection:
        """スレッドローカルなDB接続を取得する（未作成なら初期化も行う）"""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn

        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            # 終了時に別スレッドから接続を閉じられるようにする
            # （Python 3.11以降の sqlite3 は直列化モードで動作するため共有しても安全）
            conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            # 計測スレッドとWebスレッドの同時アクセスでのロック待ちを減らす
            conn.execute("PRAGMA journal_mode = WAL")
            with self._lock:
                if not self._schema_ready:
                    _apply_migrations(conn, self.db_path)
                    self._schema_ready = True
        except (sqlite3.Error, OSError) as e:
            logger.error(f"データベースへ接続できませんでした ({self.db_path}): {e}")
            raise StorageError(str(e)) from e

        self._local.conn = conn
        with self._lock:
            self._all_connections.append(conn)
        return conn

    def close(self) -> None:
        """開いている全ての接続を閉じる"""
        with self._lock:
            connections = list(self._all_connections)
            self._all_connections.clear()

        for conn in connections:
            try:
                # WALファイルが肥大化したまま残らないよう、切断前に本体へ統合する
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error as e:
                # 他の接続が使用中の場合は統合できないが、切断自体は続行する
                logger.debug(f"WALの統合をスキップしました: {e}")

            try:
                conn.close()
            except sqlite3.Error as e:
                logger.warning(f"データベース接続の切断に失敗しました: {e}")

        self._local = threading.local()

    # ── 端末の絞り込み ──

    @staticmethod
    def _device_filter(device: str | None, params: list) -> str:
        """端末指定を WHERE 句の断片へ変換する

        device が None のときは全端末を対象とする。既定は LOCAL_DEVICE のため、
        呼び出し側を変えない限り従来どおりこのPCの記録だけが返る。
        """
        if device is None:
            return ""
        params.append(device)
        return " AND device = ?"

    # ── 使用時間の記録 ──

    def add_usage(
        self, app_name: str, seconds: int, date: str | None = None, device: str = LOCAL_DEVICE
    ) -> None:
        """アプリの使用時間を加算する"""
        self.add_usage_bulk({app_name: seconds}, date, device)

    @_guard("使用時間の記録に失敗しました")
    def add_usage_bulk(
        self, usage: dict[str, int], date: str | None = None, device: str = LOCAL_DEVICE
    ) -> None:
        """複数アプリの使用時間をまとめて加算する（1トランザクション）"""
        rows = [
            (date or today_str(), app_name, self._names.key_for(app_name, device), device, int(seconds))
            for app_name, seconds in usage.items()
            if int(seconds) > 0
        ]
        if not rows:
            return

        conn = self._connect()
        with conn:
            conn.executemany(
                """
                INSERT INTO usage_log (date, app_name, app_key, device, seconds)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(date, app_key, device)
                DO UPDATE SET seconds = seconds + excluded.seconds
                """,
                rows,
            )

        # 新しいアプリを観測していれば対応表へ反映する
        self._names.save()

    # ── 使用時間の取得 ──

    @_guard("本日の使用時間の取得に失敗しました")
    def get_today_usage(self, device: str | None = LOCAL_DEVICE) -> dict[str, int]:
        """今日のアプリ別使用時間を返す {app_name: seconds}"""
        params: list = [today_str()]
        clause = self._device_filter(device, params)
        conn = self._connect()
        rows = conn.execute(
            f"""
            SELECT app_key, app_name, SUM(seconds) AS seconds
            FROM usage_log
            WHERE date = ?{clause}
            GROUP BY app_key, app_name
            """,
            params,
        ).fetchall()
        return self._names.fold(rows)

    @_guard("本日の使用時間の取得に失敗しました")
    def get_today_usage_by_key(self, device: str | None = LOCAL_DEVICE) -> dict[str, int]:
        """今日のアプリ別使用時間を照合キーで返す {app_key: seconds}

        制限時間の判定に使う。表示名は編集で変わり得るため、
        判定は必ずキーで行う（表示名で照合すると通知が出なくなる）。
        """
        params: list = [today_str()]
        clause = self._device_filter(device, params)
        conn = self._connect()
        rows = conn.execute(
            f"""
            SELECT app_key, SUM(seconds) AS seconds
            FROM usage_log
            WHERE date = ?{clause}
            GROUP BY app_key
            """,
            params,
        ).fetchall()
        return {row["app_key"]: row["seconds"] for row in rows}

    @_guard("表示名の取得に失敗しました")
    def get_display_map(self) -> dict[str, str]:
        """記録済みの全キーについて「照合キー → 表示名」を返す

        ミニウィンドウのように、キーしか持たない場所で表記を揃えるために使う。
        """
        conn = self._connect()
        rows = conn.execute("SELECT DISTINCT app_key, app_name FROM usage_log").fetchall()
        return self._names.map_for(rows)

    @_guard("期間別使用時間の取得に失敗しました")
    def get_usage_by_range(
        self, start_date: str, end_date: str, device: str | None = LOCAL_DEVICE
    ) -> dict[str, int]:
        """指定期間のアプリ別使用時間を集計して返す {app_name: seconds}"""
        params: list = [start_date, end_date]
        clause = self._device_filter(device, params)
        conn = self._connect()
        rows = conn.execute(
            f"""
            SELECT app_key, app_name, SUM(seconds) AS seconds
            FROM usage_log
            WHERE date >= ? AND date <= ?{clause}
            GROUP BY app_key, app_name
            """,
            params,
        ).fetchall()
        folded = self._names.fold(rows)
        return dict(sorted(folded.items(), key=lambda item: -item[1]))

    @_guard("端末別使用時間の取得に失敗しました")
    def get_usage_by_device(self, start_date: str, end_date: str) -> list[dict]:
        """指定期間の使用時間を、アプリ×端末の単位で返す

        合算した合計だけでなく「どの端末で使ったか」を示すために用いる。
        """
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT app_key, app_name, device, SUM(seconds) AS seconds
            FROM usage_log
            WHERE date >= ? AND date <= ?
            GROUP BY app_key, app_name, device
            """,
            (start_date, end_date),
        ).fetchall()

        # 同じキーの表記ゆれをまとめ、表示名で返す
        display = self._names.map_for(rows)

        totals: dict[tuple[str, str], int] = {}
        for row in rows:
            pair = (display[row["app_key"]], row["device"])
            totals[pair] = totals.get(pair, 0) + row["seconds"]

        return [
            {"app_name": app, "device": device, "seconds": seconds}
            for (app, device), seconds in sorted(totals.items(), key=lambda x: -x[1])
        ]

    @_guard("日別使用時間の取得に失敗しました")
    @_guard("日別使用時間の取得に失敗しました")
    def get_daily_seconds_by_key(
        self, start_date: str, end_date: str, device: str | None = LOCAL_DEVICE
    ) -> list[dict]:
        """期間内の日別×アプリ別の使用時間を照合キーで返す

        制限の超過判定に使う。表示名は「どの行を見たか」で変わるため
        （PCの記録だけを見ると `chrome.exe`、スマホも含めると `Chrome`）、
        突き合わせは必ずキーで行う。
        """
        params: list = [start_date, end_date]
        clause = self._device_filter(device, params)
        conn = self._connect()
        rows = conn.execute(
            f"""
            SELECT date, app_key, SUM(seconds) AS seconds
            FROM usage_log
            WHERE date >= ? AND date <= ?{clause}
            GROUP BY date, app_key
            ORDER BY date
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    @_guard("日別使用時間の取得に失敗しました")
    def get_daily_breakdown(
        self, start_date: str, end_date: str, device: str | None = LOCAL_DEVICE
    ) -> list[dict]:
        """期間内の日別×アプリ別の使用時間を返す（表示名）"""
        params: list = [start_date, end_date]
        clause = self._device_filter(device, params)
        conn = self._connect()
        rows = conn.execute(
            f"""
            SELECT date, app_key, app_name, SUM(seconds) AS seconds
            FROM usage_log
            WHERE date >= ? AND date <= ?{clause}
            GROUP BY date, app_key, app_name
            ORDER BY date
            """,
            params,
        ).fetchall()

        display = self._names.map_for(rows)

        totals: dict[tuple[str, str], int] = {}
        order: list[tuple[str, str]] = []
        for row in rows:
            pair = (row["date"], display[row["app_key"]])
            if pair not in totals:
                order.append(pair)
            totals[pair] = totals.get(pair, 0) + row["seconds"]

        return [
            {"date": date, "app_name": app, "seconds": totals[(date, app)]}
            for date, app in order
        ]

    # ── 使用区間（いつ使ったか） ──

    @_guard("使用区間の記録に失敗しました ({app_name})")
    def add_session(
        self,
        app_name: str,
        started_at: str,
        ended_at: str,
        seconds: int,
        date: str | None = None,
        device: str = LOCAL_DEVICE,
    ) -> int:
        """使用区間を1件登録し、そのIDを返す

        Args:
            started_at / ended_at: "YYYY-MM-DD HH:MM:SS"
            seconds: 実際に使用した秒数（スリープ等を除く）
        """
        conn = self._connect()
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO usage_session
                    (date, app_name, app_key, started_at, ended_at, seconds, device)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    date or started_at[:10],
                    app_name,
                    self._names.key_for(app_name, device),
                    started_at,
                    ended_at,
                    int(seconds),
                    device,
                ),
            )
            return int(cursor.lastrowid)

    @_guard("使用区間の更新に失敗しました (id={session_id})")
    def update_session(self, session_id: int, ended_at: str, seconds: int) -> None:
        """進行中の使用区間の終了時刻と秒数を更新する"""
        conn = self._connect()
        with conn:
            conn.execute(
                "UPDATE usage_session SET ended_at = ?, seconds = ? WHERE id = ?",
                (ended_at, int(seconds), int(session_id)),
            )

    @_guard("使用区間の取得に失敗しました ({date})")
    def get_sessions(self, date: str, device: str | None = LOCAL_DEVICE) -> list[dict]:
        """指定日の使用区間を開始時刻順に返す"""
        params: list = [date]
        clause = self._device_filter(device, params)
        conn = self._connect()
        rows = conn.execute(
            f"""
            SELECT id, app_name, app_key, started_at, ended_at, seconds, device
            FROM usage_session
            WHERE date = ?{clause}
            ORDER BY started_at, id
            """,
            params,
        ).fetchall()
        return self._names.rename_rows(rows)

    @_guard("期間内の使用区間の取得に失敗しました ({start_date}〜{end_date})")
    def get_sessions_range(
        self, start_date: str, end_date: str, device: str | None = LOCAL_DEVICE
    ) -> list[dict]:
        """指定期間の使用区間を日付・開始時刻順に返す"""
        params: list = [start_date, end_date]
        clause = self._device_filter(device, params)
        conn = self._connect()
        rows = conn.execute(
            f"""
            SELECT date, app_name, app_key, started_at, ended_at, seconds, device
            FROM usage_session
            WHERE date >= ? AND date <= ?{clause}
            ORDER BY started_at, id
            """,
            params,
        ).fetchall()
        return self._names.rename_rows(rows)

    @_guard("記録日の取得に失敗しました")
    def get_session_dates(self, limit: int = 90, device: str | None = LOCAL_DEVICE) -> list[str]:
        """使用区間が記録されている日付を新しい順に返す"""
        params: list = []
        clause = self._device_filter(device, params)
        params.append(int(limit))
        conn = self._connect()
        rows = conn.execute(
            f"""
            SELECT DISTINCT date FROM usage_session
            WHERE 1 = 1{clause}
            ORDER BY date DESC LIMIT ?
            """,
            params,
        ).fetchall()
        return [row["date"] for row in rows]

    # ── 外部端末からの取り込み ──

    @_guard("使用区間の取り込みに失敗しました ({device})")
    def import_sessions(self, device: str, sessions: list[dict]) -> dict:
        """スマホなど外部端末の使用区間を取り込む

        同じ external_id の区間は既に取り込み済みとみなし、行は増やさない。
        ただし表示名だけは更新する。送信側でアプリ名の判定が良くなった場合に、
        送り直せば過去の記録も直せるようにするため。

        取り込んだ日の usage_log は加算ではなく、区間から集計し直して置き換える。
        再送や部分的な再送があっても合計が膨らまないようにするため。

        Returns:
            {"accepted": 新たに登録した件数, "skipped": 重複で無視した件数,
             "dates": 影響を受けた日付のリスト}
        """
        if device == LOCAL_DEVICE:
            # このPC自身の記録は usage_log が正であり、区間から作り直すと壊れる
            raise ValueError(f"端末名 '{LOCAL_DEVICE}' は取り込みに使用できません")

        rows = [
            (
                session["date"],
                session["app_name"],
                session["started_at"],
                session["ended_at"],
                int(session["seconds"]),
                device,
                session["external_id"],
                self._names.key_for(session["app_name"], device),
            )
            for session in sessions
        ]
        dates = sorted({row[0] for row in rows})

        conn = self._connect()
        with conn:
            # 表示名の更新も変更として数えられてしまうため、
            # 行数の増分から新規登録の件数を求める
            before = conn.execute(
                "SELECT COUNT(*) FROM usage_session WHERE device = ?", (device,)
            ).fetchone()[0]
            conn.executemany(
                """
                INSERT INTO usage_session
                    (date, app_name, started_at, ended_at, seconds, device,
                     external_id, app_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device, external_id) WHERE external_id IS NOT NULL
                DO UPDATE SET app_name = excluded.app_name, app_key = excluded.app_key
                """,
                rows,
            )
            after = conn.execute(
                "SELECT COUNT(*) FROM usage_session WHERE device = ?", (device,)
            ).fetchone()[0]
            accepted = after - before

            # 影響を受けた日だけ、区間から日次合計を作り直す
            for date in dates:
                conn.execute(
                    "DELETE FROM usage_log WHERE device = ? AND date = ?", (device, date)
                )
                conn.execute(
                    """
                    INSERT INTO usage_log (date, app_name, app_key, device, seconds)
                    SELECT date, MIN(app_name), app_key, device, SUM(seconds)
                    FROM usage_session
                    WHERE device = ? AND date = ?
                    GROUP BY date, app_key, device
                    """,
                    (device, date),
                )

        logger.info(
            f"{device} から使用区間を取り込みました: "
            f"新規 {accepted}件 / 重複 {len(rows) - accepted}件 / 対象日 {len(dates)}日"
        )
        return {"accepted": accepted, "skipped": len(rows) - accepted, "dates": dates}

    @_guard("記録済みのアプリ名を取得できませんでした")
    def register_existing(self) -> int:
        """記録済みのアプリ名を対応表へ取り込む

        移行直後や対応表を消した後でも、どの端末でどう記録されたかを
        一覧できるようにするために起動時へ呼ぶ。

        Returns:
            取り込んだ表記の数
        """
        if not self._names.has_registry:
            return 0

        conn = self._connect()
        rows = conn.execute(
            "SELECT DISTINCT app_name, device FROM usage_log"
        ).fetchall()

        for row in rows:
            self._names.register(row["app_name"], row["device"])
        self._names.save()
        return len(rows)

    @_guard("照合キーの再計算に失敗しました")
    def renormalize(self) -> int:
        """記録済みのアプリ名から照合キーを計算し直す

        対応表（data/app_names.json）を編集して束ね方を変えたときに、
        過去の記録へも反映するために用いる。
        キーが変わると1つにまとまる行が出るため、集計し直して入れ替える。

        Returns:
            キーが変わった行の数
        """
        conn = self._connect()
        pairs = conn.execute(
            "SELECT DISTINCT app_name, app_key FROM usage_log"
        ).fetchall()
        changed = [p for p in pairs if p["app_key"] != self._names.key_for(p["app_name"])]
        if not changed:
            return 0

        logger.info(f"照合キーを計算し直します（対象の表記 {len(changed)}種）")
        with conn:
            # 日次集計は同じキーの行がぶつかるため、集計し直して入れ替える
            rows = conn.execute(
                "SELECT date, app_name, device, seconds FROM usage_log"
            ).fetchall()
            totals: dict[tuple, dict] = {}
            for row in rows:
                key = self._names.key_for(row["app_name"])
                slot = totals.setdefault(
                    (row["date"], key, row["device"]),
                    {"name": row["app_name"], "seconds": 0},
                )
                slot["seconds"] += row["seconds"]

            conn.execute("DELETE FROM usage_log")
            conn.executemany(
                """
                INSERT INTO usage_log (date, app_name, app_key, device, seconds)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (date, slot["name"], key, device, slot["seconds"])
                    for (date, key, device), slot in totals.items()
                ],
            )

            # 使用区間は一意制約が無いため、その場で書き換えられる
            for row in conn.execute(
                "SELECT DISTINCT app_name FROM usage_session"
            ).fetchall():
                conn.execute(
                    "UPDATE usage_session SET app_key = ? WHERE app_name = ?",
                    (self._names.key_for(row["app_name"]), row["app_name"]),
                )

        return len(changed)

    @_guard("受信時刻の記録に失敗しました ({device})")
    def touch_device(self, device: str, seen_at: str | None = None) -> None:
        """端末から受信したことを記録する

        送るものが無い場合でも呼ばれる。届いているかどうかを知るための値で、
        使用時間の有無とは別に扱う。
        """
        conn = self._connect()
        with conn:
            conn.execute(
                """
                INSERT INTO device_seen (device, last_seen) VALUES (?, ?)
                ON CONFLICT(device) DO UPDATE SET last_seen = excluded.last_seen
                """,
                (device, seen_at or now_str()),
            )

    @_guard("受信時刻の取得に失敗しました")
    def get_device_seen(self) -> dict[str, str]:
        """端末ごとの最終受信時刻を返す {device: "YYYY-MM-DD HH:MM:SS"}"""
        conn = self._connect()
        rows = conn.execute("SELECT device, last_seen FROM device_seen").fetchall()
        return {row["device"]: row["last_seen"] for row in rows}

    # ── Notion への送信記録 ──

    @_guard("Notionの送信記録の取得に失敗しました")
    def get_notion_sent(self) -> dict[str, str]:
        """送信済みの日を返す {date: page_id}"""
        conn = self._connect()
        rows = conn.execute("SELECT date, page_id FROM notion_sync").fetchall()
        return {row["date"]: row["page_id"] for row in rows}

    @_guard("Notionの送信記録の保存に失敗しました ({date})")
    def mark_notion_sent(self, date: str, page_id: str) -> None:
        """その日を送信済みとして控える（送り直した場合は上書き）"""
        conn = self._connect()
        with conn:
            conn.execute(
                """
                INSERT INTO notion_sync (date, page_id, sent_at)
                VALUES (?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    page_id = excluded.page_id, sent_at = excluded.sent_at
                """,
                (date, page_id, now_str()),
            )

    # ── 制限時間設定 ──

    def key_for(self, app_name: str) -> str:
        """記録された名前や表示名から照合キーを求める

        画面は表示名でやり取りするため、制限時間の出し入れで変換に使う。
        """
        return self._names.key_for(app_name)

    @_guard("制限時間の設定に失敗しました ({app_name})")
    def set_limit(self, app_name: str, limit_minutes: int) -> None:
        """アプリの制限時間を設定する

        表示名で受け取り、照合キーで保存する。記録される名前と表示名が
        違うアプリ（`chrome.exe` と `Chrome`）でも同じ制限が働くようにするため。
        """
        conn = self._connect()
        with conn:
            conn.execute(
                """
                INSERT INTO app_limits (app_key, limit_minutes)
                VALUES (?, ?)
                ON CONFLICT(app_key) DO UPDATE SET limit_minutes = excluded.limit_minutes
                """,
                (self.key_for(app_name), int(limit_minutes)),
            )

    @_guard("制限時間の削除に失敗しました ({app_name})")
    def remove_limit(self, app_name: str) -> None:
        """アプリの制限時間を削除する（表示名で受け取る）"""
        conn = self._connect()
        with conn:
            conn.execute("DELETE FROM app_limits WHERE app_key = ?", (self.key_for(app_name),))

    @_guard("制限時間の取得に失敗しました")
    def get_limits(self) -> dict[str, int]:
        """全アプリの制限時間を返す {app_key: limit_minutes}

        キーで返すため、そのままでは画面に出せない。
        表示名が要る場合は get_limits_by_name() を使う。
        """
        conn = self._connect()
        rows = conn.execute("SELECT app_key, limit_minutes FROM app_limits").fetchall()
        return {row["app_key"]: row["limit_minutes"] for row in rows}

    @_guard("制限時間の取得に失敗しました")
    def get_limits_by_name(self) -> dict[str, int]:
        """全アプリの制限時間を表示名で返す {app_name: limit_minutes}

        画面と、記録から表示名を引けないキー（まだ一度も使っていないアプリ）
        の両方に対応するため、記録済みの表記を突き合わせて解決する。
        """
        conn = self._connect()
        limits = conn.execute("SELECT app_key, limit_minutes FROM app_limits").fetchall()
        if not limits:
            return {}

        observed = conn.execute("SELECT DISTINCT app_key, app_name FROM usage_log").fetchall()
        display = self._names.map_for(observed)

        return {
            display.get(row["app_key"], row["app_key"]): row["limit_minutes"]
            for row in limits
        }
