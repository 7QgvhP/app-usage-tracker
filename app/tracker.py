"""
tracker.py - アクティブウィンドウの監視と使用時間の集計

一定間隔でフォアグラウンドのアプリを確認し、前回確認時からの
「実際の経過時間」を加算する。集計はメモリ上で行い、一定間隔でまとめて
データベースへ書き出すことで書き込み回数を抑えている。
"""

from __future__ import annotations

import datetime
import logging
import threading
import time
from typing import Callable, Optional

from app.config import Config
from app.notifier import Notifier
from app.storage import StorageError, UsageStore, today_str

logger = logging.getLogger(__name__)

# スリープ復帰などで生じる異常な経過時間を打ち切る倍率（監視間隔の何倍まで許容するか）
MAX_ELAPSED_FACTOR = 3


def clamp_elapsed(elapsed: float, max_elapsed: float) -> float:
    """経過時間を許容範囲へ収める

    スリープ・休止状態から復帰すると前回の走査から数時間が経過していることがあるが、
    その間はPCを使用していないため、そのまま計上せず上限値で打ち切る。
    """
    if elapsed < 0:
        return 0.0
    return min(elapsed, max_elapsed)


class AppTracker:
    """アプリ使用時間トラッカー

    Args:
        config: アプリケーション設定
        store: 使用時間の保存先
        notifier: 通知の送信先（省略時は既定の Notifier）
        sampler: アクティブアプリ名を返す関数（省略時は Windows API を使用）
        idle_provider: 無操作の経過秒数を返す関数（省略時は Windows API を使用）
    """

    def __init__(
        self,
        config: Config,
        store: UsageStore,
        notifier: Optional[Notifier] = None,
        sampler: Optional[Callable[[], Optional[str]]] = None,
        idle_provider: Optional[Callable[[], float]] = None,
    ):
        self._config = config
        self._store = store
        self._notifier = notifier or Notifier()
        self._sampler = sampler
        self._idle_provider = idle_provider

        # 設定値は毎回の走査で参照するため、起動時に取り出しておく
        self._poll_interval = config.poll_interval
        self._flush_interval = config.flush_interval
        self._notify_before = config.notify_before_minutes
        self._idle_enabled = config.idle_detection_enabled
        self._idle_threshold = config.idle_threshold_seconds
        self._use_executable_name = config.use_executable_name
        self._ignore_processes = config.ignore_processes
        self._browser_processes = config.browser_processes
        self._browser_site_rules = config.browser_site_rules

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._paused = False

        # 集計状態は監視スレッド以外（ミニウィンドウ等）からも読むためロックで保護する
        self._state_lock = threading.Lock()
        self._current_app: Optional[str] = None
        self._is_idle = False

        # 未書き出しの使用時間（秒・小数を含む）
        self._pending: dict[str, float] = {}
        self._current_date: str = today_str()

        # 進行中の使用区間（いつ使ったかの記録）
        self._session_lock = threading.Lock()
        self._session_app: Optional[str] = None
        self._session_started = datetime.datetime.now()
        self._session_ended = self._session_started
        self._session_seconds = 0.0
        self._session_id: Optional[int] = None

        # DBアクセスを毎回行わないためのキャッシュ
        self._usage_cache: dict[str, int] = {}
        self._limits_cache: dict[str, int] = {}
        # 照合キー → 表示名（ミニウィンドウの表記を画面へ揃えるため）
        self._display_cache: dict[str, str] = {}
        self._limits_dirty = True

        self._notified_reached: set[str] = set()
        self._notified_approaching: set[str] = set()

    # ── 監視の開始・停止 ──

    def start(self) -> None:
        """監視スレッドを開始する"""
        if self._thread is not None and self._thread.is_alive():
            logger.debug("トラッカーは既に動作しています")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="TrackerThread", daemon=True)
        self._thread.start()
        logger.info(
            f"トラッカーを開始しました（監視間隔 {self._poll_interval:.0f}秒 / "
            f"書き出し間隔 {self._flush_interval:.0f}秒 / "
            f"アイドル検知 {'有効' if self._idle_enabled else '無効'}）"
        )

    def stop(self) -> None:
        """監視スレッドを停止する（未書き出しのデータは保存される）"""
        self._stop_event.set()

        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=self._poll_interval + 5)
            if thread.is_alive():
                logger.warning("トラッカーの停止がタイムアウトしました")
            else:
                self._thread = None

        # スレッドが応答しない場合に備え、呼び出し側でも書き出しを試みる
        self._close_session()
        self.flush()
        logger.info("トラッカーを停止しました")

    def pause(self) -> None:
        """計測を一時停止する"""
        self._paused = True
        logger.info("計測を一時停止しました")

    def resume(self) -> None:
        """計測を再開する"""
        self._paused = False
        logger.info("計測を再開しました")

    @property
    def is_paused(self) -> bool:
        return self._paused

    def notify_limits_changed(self) -> None:
        """制限設定が変更されたことを通知し、次回走査でキャッシュを更新させる"""
        self._limits_dirty = True

    def get_current_usage(self) -> dict:
        """現在アクティブなアプリと、その日の使用時間を返す

        書き出し前のメモリ上の集計も合算するため、DBへの書き出し間隔を
        待たずに実時間へ追従した値が得られる。

        Returns:
            {"app": アプリ名 or None, "seconds": そのアプリの今日の使用秒数,
             "total_seconds": 全アプリ合計の今日の使用秒数,
             "limit_minutes": そのアプリの制限時間 or None,
             "paused": 一時停止中か, "idle": 離席判定中か}
        """
        with self._state_lock:
            app_name = self._current_app
            display = app_name
            seconds = 0.0
            limit = None
            if app_name:
                key = self._store.key_for(app_name)
                # ミニウィンドウの表記をダッシュボードへ揃える
                display = self._display_cache.get(key, app_name)
                seconds = self._used_seconds(key)
                limit = self._limits_cache.get(key)
            total = sum(self._usage_cache.values()) + sum(self._pending.values())

            return {
                "app": display,
                "seconds": int(seconds),
                "total_seconds": int(total),
                "limit_minutes": limit,
                "paused": self._paused,
                "idle": self._is_idle,
            }

    # ── 監視ループ ──

    def _loop(self) -> None:
        """監視のメインループ"""
        self._current_date = today_str()
        self._refresh_caches()

        max_elapsed = self._poll_interval * MAX_ELAPSED_FACTOR
        last_tick = time.monotonic()
        last_flush = last_tick

        # wait() は停止要求で True を返すため、そのままループの終了条件になる
        while not self._stop_event.wait(self._poll_interval):
            try:
                now = time.monotonic()
                raw_elapsed = now - last_tick
                last_tick = now

                elapsed = clamp_elapsed(raw_elapsed, max_elapsed)
                if elapsed < raw_elapsed:
                    logger.info(
                        f"{raw_elapsed:.0f}秒の空白を検出したため {elapsed:.0f}秒として計上します"
                    )
                    # スリープを挟んだ区間を1つの長大な区間にしないよう、ここで区切る
                    self._close_session()

                self._process_tick(elapsed)

                if now - last_flush >= self._flush_interval:
                    self.flush()
                    self._refresh_caches()
                    last_flush = now

            except Exception as e:
                logger.error(f"監視処理でエラーが発生しました: {e}", exc_info=True)

        self._close_session()
        self.flush()

    def _process_tick(self, elapsed: float) -> None:
        """1回分の走査を処理する

        Args:
            elapsed: 前回の走査からの経過秒数
        """
        # 日付が変わったら前日分を確定させ、通知済みの記録をリセットする
        current_date = today_str()
        if current_date != self._current_date:
            # 日付をまたぐ区間は、日ごとに集計できるようここで分割する
            self._close_session()
            self.flush()
            self._current_date = current_date
            self._notified_reached.clear()
            self._notified_approaching.clear()
            self._refresh_caches()

        if self._limits_dirty:
            self._refresh_limits()

        if self._paused:
            self._close_session()
            with self._state_lock:
                self._is_idle = False
            return

        if self._idle_enabled and self._get_idle_seconds() >= self._idle_threshold:
            self._close_session()
            with self._state_lock:
                self._is_idle = True
            return

        app_name = self._get_active_app()

        with self._state_lock:
            self._is_idle = False
            self._current_app = app_name
            if app_name:
                self._pending[app_name] = self._pending.get(app_name, 0.0) + elapsed

        if app_name:
            self._extend_session(app_name, elapsed)
            self._check_limits(app_name)
        else:
            # 計測対象外のアプリへ移った場合も区間を区切る
            self._close_session()

    def flush(self) -> None:
        """未書き出しの使用時間をデータベースへ保存する

        秒未満の端数は次回へ繰り越し、丸めによる誤差の蓄積を防ぐ。
        """
        # 進行中の使用区間も保存し、強制終了時の取りこぼしを最小限にする
        self._save_session()

        # 書き出す分の切り出しはロック内で行い、DBアクセス自体はロックを解放してから行う
        with self._state_lock:
            if not self._pending:
                return

            to_write: dict[str, int] = {}
            carry_over: dict[str, float] = {}
            for app_name, seconds in self._pending.items():
                whole = int(seconds)
                if whole > 0:
                    to_write[app_name] = whole
                fraction = seconds - whole
                if fraction > 0:
                    carry_over[app_name] = fraction

            if not to_write:
                return

            self._pending = carry_over
            target_date = self._current_date

        try:
            self._store.add_usage_bulk(to_write, target_date)
        except StorageError:
            # 保存に失敗した分は破棄せず、次回の書き出しで再試行する
            with self._state_lock:
                for app_name, seconds in to_write.items():
                    self._pending[app_name] = self._pending.get(app_name, 0.0) + seconds
            logger.warning("使用時間の保存に失敗したため、次回の書き出しで再試行します")
            return

        # キャッシュは照合キーで持つため、書き出した分もキーへ寄せて足す
        # （キーの算出はDBに触れないが、ロックの外で済ませておく）
        written = {}
        for app_name, seconds in to_write.items():
            key = self._store.key_for(app_name)
            written[key] = written.get(key, 0) + seconds

        with self._state_lock:
            for key, seconds in written.items():
                self._usage_cache[key] = self._usage_cache.get(key, 0) + seconds

    # ── 使用区間（いつ使ったか） ──

    def _extend_session(self, app_name: str, elapsed: float) -> None:
        """使用区間を延長する（アプリが変わっていれば区切って新しく始める）"""
        now = datetime.datetime.now()
        with self._session_lock:
            if self._session_app != app_name:
                self._write_session()
                self._session_app = app_name
                # 走査の間隔ぶん手前から使い始めていたはずなので、その分さかのぼる
                self._session_started = now - datetime.timedelta(seconds=elapsed)
                self._session_seconds = 0.0
                self._session_id = None

            self._session_seconds += elapsed
            self._session_ended = now

    def _close_session(self) -> None:
        """進行中の使用区間を確定して閉じる"""
        with self._session_lock:
            if self._session_app is None:
                return
            self._write_session()
            self._session_app = None
            self._session_id = None
            self._session_seconds = 0.0

    def _save_session(self) -> None:
        """進行中の使用区間を保存する（区間は閉じない）"""
        with self._session_lock:
            self._write_session()

    def _write_session(self) -> None:
        """使用区間をデータベースへ書き出す（_session_lock を保持した状態で呼ぶ）

        1秒に満たない区間は記録しない。初回は登録し、以降は同じ行を更新する。
        """
        if self._session_app is None:
            return

        seconds = int(self._session_seconds)
        if seconds < 1:
            return

        started = self._session_started.strftime("%Y-%m-%d %H:%M:%S")
        ended = self._session_ended.strftime("%Y-%m-%d %H:%M:%S")
        try:
            if self._session_id is None:
                self._session_id = self._store.add_session(
                    self._session_app, started, ended, seconds
                )
            else:
                self._store.update_session(self._session_id, ended, seconds)
        except StorageError:
            logger.warning("使用区間を保存できませんでした（計測は継続します）")

    # ── 内部処理 ──

    def _get_active_app(self) -> Optional[str]:
        """現在アクティブなアプリ名を取得する"""
        if self._sampler is not None:
            return self._sampler()

        from app import window

        return window.get_active_app_name(
            self._ignore_processes,
            self._browser_processes,
            self._browser_site_rules,
            self._use_executable_name,
        )

    def _get_idle_seconds(self) -> float:
        """無操作の経過秒数を取得する"""
        if self._idle_provider is not None:
            return self._idle_provider()

        from app import window

        return window.get_idle_seconds()

    def _refresh_caches(self) -> None:
        """今日の使用時間と制限設定のキャッシュを更新する

        使用時間・制限とも照合キーで保持する。表示名は編集で変わり得るため、
        判定に使うと通知が出なくなることがある。
        """
        try:
            usage = self._store.get_today_usage_by_key()
            display = self._store.get_display_map()
            with self._state_lock:
                self._usage_cache = usage
                self._display_cache = display
        except StorageError:
            logger.warning("使用時間のキャッシュ更新に失敗したため、前回の値を使用します")
        self._refresh_limits()

    def _refresh_limits(self) -> None:
        """制限設定のキャッシュを更新する"""
        try:
            self._limits_cache = self._store.get_limits()
            self._limits_dirty = False
        except StorageError:
            logger.warning("制限設定のキャッシュ更新に失敗したため、前回の値を使用します")

    def _used_seconds(self, key: str) -> float:
        """そのキーの今日の使用秒数（書き出し前の分も含む）

        書き出し前の集計は記録される名前で持っているため、
        同じキーへ寄るものを足し合わせる。
        """
        pending = sum(
            seconds
            for name, seconds in self._pending.items()
            if self._store.key_for(name) == key
        )
        return self._usage_cache.get(key, 0) + pending

    def _check_limits(self, app_name: str) -> None:
        """使用時間が制限に達していないか確認し、必要なら通知する

        照合はキーで行う。画面から `Chrome` に設定した制限が、
        `chrome.exe` として記録されるアプリにも効くようにするため。
        """
        key = self._store.key_for(app_name)
        limit_minutes = self._limits_cache.get(key)
        if not limit_minutes:
            return

        # 通知に出す名前も画面と揃える（記録名のままだと表記が食い違う）
        display = self._display_cache.get(key, app_name)

        used_seconds = self._used_seconds(key)
        used_minutes = used_seconds / 60

        # 通知済みの管理もキーで行う。同じアプリを別の表記で二度通知しないため
        if used_minutes >= limit_minutes:
            if key not in self._notified_reached:
                self._notifier.notify_limit_reached(display, limit_minutes)
                self._notified_reached.add(key)
            return

        if self._notify_before <= 0 or key in self._notified_approaching:
            return

        if limit_minutes - used_minutes <= self._notify_before:
            remaining = max(1, int(limit_minutes - used_minutes))
            self._notifier.notify_limit_approaching(display, limit_minutes, remaining)
            self._notified_approaching.add(key)
