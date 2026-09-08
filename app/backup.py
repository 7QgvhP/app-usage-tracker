"""
app/backup.py - データベースの自動バックアップ

記録の複製を1日1回作り、世代数の上限を超えた古いものから削除する。
複製には SQLite の backup API を使うため、アプリの動作中でも安全に取得できる
（ファイルのコピーと違い、書き込み途中の状態が混ざらない）。
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)

# バックアップの既定の確認間隔（秒）。日付が変わったかを見るだけなので1時間で足りる
DEFAULT_CHECK_INTERVAL = 3600

# 自動で作った複製だけを対象にするための名前の形式
_BACKUP_NAME = re.compile(r"^usage-(\d{8})-\d{6}\.db$")


class BackupError(Exception):
    """バックアップの取得に失敗した"""


def backup_filename(moment: Optional[datetime] = None) -> str:
    """複製のファイル名を組み立てる（名前順に並べると時刻順になる）"""
    return f"usage-{(moment or datetime.now()).strftime('%Y%m%d-%H%M%S')}.db"


def list_backups(backup_dir: str) -> list[str]:
    """複製のフルパスを古い順に返す

    自動で作った名前の形式に合うものだけを対象とし、
    利用者が別途置いたファイルには触れない。
    """
    try:
        entries = os.listdir(backup_dir)
    except OSError:
        return []

    names = sorted(name for name in entries if _BACKUP_NAME.match(name))
    return [os.path.join(backup_dir, name) for name in names]


def latest_backup_date(backup_dir: str) -> Optional[date]:
    """最も新しい複製が作られた日付を返す（1つも無ければ None）"""
    backups = list_backups(backup_dir)
    if not backups:
        return None

    match = _BACKUP_NAME.match(os.path.basename(backups[-1]))
    if not match:
        return None

    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def create_backup(db_path: str, backup_dir: str, moment: Optional[datetime] = None) -> str:
    """データベースを複製し、作成したファイルのパスを返す

    途中で失敗した複製を有効なものと誤認しないよう、
    一時ファイルへ書き出してから最終的な名前へ差し替える。

    Raises:
        BackupError: 複製できなかった場合
    """
    if not os.path.exists(db_path):
        raise BackupError(f"データベースが見つかりません: {db_path}")

    destination = os.path.join(backup_dir, backup_filename(moment))
    working = f"{destination}.tmp"

    try:
        os.makedirs(backup_dir, exist_ok=True)
        source = sqlite3.connect(db_path, timeout=30)
        try:
            target = sqlite3.connect(working)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
        os.replace(working, destination)
    except (sqlite3.Error, OSError) as e:
        _remove_quietly(working)
        raise BackupError(str(e)) from e

    return destination


def prune_backups(backup_dir: str, keep: int) -> list[str]:
    """世代数の上限を超えた古い複製を削除し、削除したパスを返す"""
    if keep < 1:
        keep = 1

    backups = list_backups(backup_dir)
    removed = []
    for path in backups[: max(0, len(backups) - keep)]:
        if _remove_quietly(path):
            removed.append(path)
    return removed


def _remove_quietly(path: str) -> bool:
    """ファイルを削除する（存在しない場合や失敗しても例外にしない）"""
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False
    except OSError as e:
        logger.warning(f"古いバックアップを削除できませんでした ({path}): {e}")
        return False


class BackupScheduler:
    """1日1回のバックアップを担う常駐スレッド

    起動直後に一度確認し、以後は一定間隔で日付が変わったかを見る。
    バックアップの失敗でアプリ全体が止まらないよう、例外はログに留める。
    """

    def __init__(
        self,
        db_path: str,
        backup_dir: str,
        keep: int = 7,
        check_interval: int = DEFAULT_CHECK_INTERVAL,
    ):
        self.db_path = db_path
        self.backup_dir = backup_dir
        self.keep = keep
        self.check_interval = check_interval
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def run_if_due(self, now: Optional[datetime] = None) -> Optional[str]:
        """その日の複製がまだ無ければ取得する

        判定に使う日付とファイル名の時刻は同じ値から導く
        （別々に現在時刻を取ると、日付をまたぐ瞬間に食い違うため）。

        Returns:
            作成した複製のパス。取得しなかった場合は None。
        """
        now = now or datetime.now()
        if latest_backup_date(self.backup_dir) == now.date():
            return None

        try:
            path = create_backup(self.db_path, self.backup_dir, moment=now)
        except BackupError as e:
            logger.warning(f"データベースのバックアップに失敗しました: {e}")
            return None

        size = os.path.getsize(path)
        logger.info(f"データベースをバックアップしました: {path} ({size:,} バイト)")

        for removed in prune_backups(self.backup_dir, self.keep):
            logger.info(f"古いバックアップを削除しました: {removed}")

        return path

    def start(self) -> None:
        """常駐スレッドを開始する"""
        if self._thread is not None:
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="BackupThread", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """常駐スレッドを停止する"""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _loop(self) -> None:
        """終了を求められるまで、一定間隔で取得の要否を確かめる"""
        while not self._stop_event.is_set():
            try:
                self.run_if_due()
            except Exception as e:
                # 想定外の例外でスレッドが落ちると以後一切バックアップされなくなる
                logger.error(f"バックアップ処理で予期しない例外が発生しました: {e}", exc_info=True)
            self._stop_event.wait(self.check_interval)
