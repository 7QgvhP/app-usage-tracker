"""データベースの自動バックアップ"""

import os
import sqlite3
from datetime import date, datetime, timedelta

import pytest

from app.backup import (
    BackupError,
    BackupScheduler,
    create_backup,
    latest_backup_date,
    list_backups,
    prune_backups,
)


def make_database(path, rows=3):
    """検証用のデータベースを作る"""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE usage_log (app_name TEXT, seconds INTEGER)")
    conn.executemany(
        "INSERT INTO usage_log VALUES (?, ?)", [(f"app{i}", i * 60) for i in range(rows)]
    )
    conn.commit()
    conn.close()
    return str(path)


class TestCreateBackup:
    """複製の取得"""

    def test_backup_contains_same_rows(self, tmp_path):
        db = make_database(tmp_path / "usage.db", rows=5)
        backup_dir = str(tmp_path / "backups")

        path = create_backup(db, backup_dir)

        conn = sqlite3.connect(path)
        assert conn.execute("SELECT COUNT(*) FROM usage_log").fetchone()[0] == 5
        conn.close()

    def test_backup_works_while_database_is_open(self, tmp_path):
        """アプリの動作中でも取得できる（WALで開いたまま複製する）"""
        db = make_database(tmp_path / "usage.db", rows=2)
        live = sqlite3.connect(db)
        live.execute("PRAGMA journal_mode = WAL")
        live.execute("INSERT INTO usage_log VALUES ('あとから', 30)")
        live.commit()

        try:
            path = create_backup(db, str(tmp_path / "backups"))
        finally:
            live.close()

        conn = sqlite3.connect(path)
        # WAL に留まっている行も複製へ含まれる
        assert conn.execute("SELECT COUNT(*) FROM usage_log").fetchone()[0] == 3
        conn.close()

    def test_missing_database_raises(self, tmp_path):
        with pytest.raises(BackupError):
            create_backup(str(tmp_path / "ない.db"), str(tmp_path / "backups"))

    def test_temporary_file_is_not_left_behind(self, tmp_path):
        db = make_database(tmp_path / "usage.db")
        backup_dir = str(tmp_path / "backups")

        create_backup(db, backup_dir)

        assert [n for n in os.listdir(backup_dir) if n.endswith(".tmp")] == []


class TestListBackups:
    """複製の一覧と日付の判定"""

    def test_returns_oldest_first(self, tmp_path):
        db = make_database(tmp_path / "usage.db")
        backup_dir = str(tmp_path / "backups")
        base = datetime(2026, 8, 20, 9, 0, 0)

        for days in (2, 0, 1):
            create_backup(db, backup_dir, moment=base + timedelta(days=days))

        names = [os.path.basename(p) for p in list_backups(backup_dir)]
        assert names == [
            "usage-20260820-090000.db",
            "usage-20260821-090000.db",
            "usage-20260822-090000.db",
        ]

    def test_ignores_unrelated_files(self, tmp_path):
        """利用者が置いた別のファイルは対象にしない"""
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        (backup_dir / "usage-20260820-090000.db").write_text("x")
        (backup_dir / "手動控え.db").write_text("x")
        (backup_dir / "usage.db.bak-20260820").write_text("x")

        names = [os.path.basename(p) for p in list_backups(str(backup_dir))]
        assert names == ["usage-20260820-090000.db"]

    def test_latest_date_is_none_when_empty(self, tmp_path):
        assert latest_backup_date(str(tmp_path / "ない")) is None

    def test_latest_date_uses_newest(self, tmp_path):
        db = make_database(tmp_path / "usage.db")
        backup_dir = str(tmp_path / "backups")
        create_backup(db, backup_dir, moment=datetime(2026, 8, 20, 9, 0, 0))
        create_backup(db, backup_dir, moment=datetime(2026, 8, 22, 9, 0, 0))

        assert latest_backup_date(backup_dir) == date(2026, 8, 22)


class TestPruneBackups:
    """世代数の管理"""

    def test_keeps_newest(self, tmp_path):
        db = make_database(tmp_path / "usage.db")
        backup_dir = str(tmp_path / "backups")
        base = datetime(2026, 8, 20, 9, 0, 0)
        for days in range(5):
            create_backup(db, backup_dir, moment=base + timedelta(days=days))

        removed = prune_backups(backup_dir, keep=2)

        assert len(removed) == 3
        names = [os.path.basename(p) for p in list_backups(backup_dir)]
        assert names == ["usage-20260823-090000.db", "usage-20260824-090000.db"]

    def test_does_nothing_when_under_limit(self, tmp_path):
        db = make_database(tmp_path / "usage.db")
        backup_dir = str(tmp_path / "backups")
        create_backup(db, backup_dir)

        assert prune_backups(backup_dir, keep=7) == []
        assert len(list_backups(backup_dir)) == 1

    def test_keep_is_at_least_one(self, tmp_path):
        """設定に 0 が入っていても、最後の1つは残す"""
        db = make_database(tmp_path / "usage.db")
        backup_dir = str(tmp_path / "backups")
        create_backup(db, backup_dir, moment=datetime(2026, 8, 20, 9, 0, 0))
        create_backup(db, backup_dir, moment=datetime(2026, 8, 21, 9, 0, 0))

        prune_backups(backup_dir, keep=0)

        assert len(list_backups(backup_dir)) == 1


class TestBackupScheduler:
    """取得の要否の判定"""

    def scheduler(self, tmp_path, keep=7):
        db = make_database(tmp_path / "usage.db")
        return BackupScheduler(db, str(tmp_path / "backups"), keep=keep)

    def test_takes_backup_on_first_run(self, tmp_path):
        scheduler = self.scheduler(tmp_path)
        assert scheduler.run_if_due() is not None

    def test_skips_when_today_is_already_taken(self, tmp_path):
        scheduler = self.scheduler(tmp_path)
        scheduler.run_if_due()

        assert scheduler.run_if_due() is None
        assert len(list_backups(scheduler.backup_dir)) == 1

    def test_takes_backup_when_date_changes(self, tmp_path):
        scheduler = self.scheduler(tmp_path)
        scheduler.run_if_due(now=datetime(2026, 8, 26, 23, 59, 0))

        assert scheduler.run_if_due(now=datetime(2026, 8, 27, 0, 1, 0)) is not None
        assert len(list_backups(scheduler.backup_dir)) == 2

    def test_same_day_at_different_times_is_skipped(self, tmp_path):
        """同じ日なら時刻が違っても取り直さない"""
        scheduler = self.scheduler(tmp_path)
        scheduler.run_if_due(now=datetime(2026, 8, 27, 1, 0, 0))

        assert scheduler.run_if_due(now=datetime(2026, 8, 27, 23, 0, 0)) is None

    def test_prunes_after_taking(self, tmp_path):
        scheduler = self.scheduler(tmp_path, keep=2)
        base = datetime(2026, 8, 20, 9, 0, 0)
        for days in range(3):
            create_backup(scheduler.db_path, scheduler.backup_dir, moment=base + timedelta(days=days))

        scheduler.run_if_due()

        assert len(list_backups(scheduler.backup_dir)) == 2

    def test_failure_does_not_raise(self, tmp_path):
        """複製に失敗してもアプリを止めない"""
        scheduler = BackupScheduler(str(tmp_path / "ない.db"), str(tmp_path / "backups"))
        assert scheduler.run_if_due() is None

    def test_thread_takes_backup_and_stops(self, tmp_path):
        scheduler = self.scheduler(tmp_path)
        scheduler.check_interval = 60
        scheduler.start()
        try:
            for _ in range(50):
                if list_backups(scheduler.backup_dir):
                    break
                import time

                time.sleep(0.05)
        finally:
            scheduler.stop()

        assert len(list_backups(scheduler.backup_dir)) == 1
        assert scheduler._thread is None
