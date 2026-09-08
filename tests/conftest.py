"""
conftest.py - テスト共通のフィクスチャ
"""

from __future__ import annotations

import copy
import os
import sys

import pytest

# プロジェクトルートをインポート対象に加える
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import DEFAULTS, Config  # noqa: E402
from app.storage import UsageStore  # noqa: E402


@pytest.fixture
def store(tmp_path):
    """テスト用の一時データベースを持つデータストア"""
    usage_store = UsageStore(str(tmp_path / "data" / "test.db"))
    yield usage_store
    usage_store.close()


@pytest.fixture
def config():
    """テスト用の設定（監視間隔を短くしたもの）"""
    data = copy.deepcopy(DEFAULTS)
    data["tracker"]["poll_interval_seconds"] = 1
    data["tracker"]["flush_interval_seconds"] = 1
    return Config(data)


class FakeNotifier:
    """通知内容を記録するだけの通知クラス"""

    def __init__(self):
        self.reached: list[tuple[str, int]] = []
        self.approaching: list[tuple[str, int, int]] = []

    def notify_limit_reached(self, app_name, limit_minutes):
        self.reached.append((app_name, limit_minutes))
        return True

    def notify_limit_approaching(self, app_name, limit_minutes, remaining_minutes):
        self.approaching.append((app_name, limit_minutes, remaining_minutes))
        return True


@pytest.fixture
def notifier():
    return FakeNotifier()
