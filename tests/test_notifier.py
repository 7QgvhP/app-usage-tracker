"""
test_notifier.py - 通知処理のテスト

winotify を差し替え、実際にトーストを表示せずに検証する。
"""

from __future__ import annotations

import os

import pytest

from app import notifier as notifier_module
from app.notifier import DEFAULT_ICON_PATH, Notifier


class FakeNotification:
    """生成時の引数を記録するだけの通知クラス"""

    instances: list[dict] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeNotification.instances.append(kwargs)

    def show(self):
        return True


@pytest.fixture
def fake_toast(monkeypatch):
    FakeNotification.instances = []
    monkeypatch.setattr(notifier_module, "Notification", FakeNotification)
    monkeypatch.setattr(notifier_module, "_WINOTIFY_AVAILABLE", True)
    return FakeNotification


class TestNotification:
    """通知の送信"""

    def test_limit_reached_contains_app_and_minutes(self, fake_toast):
        notifier = Notifier()

        assert notifier.notify_limit_reached("chrome.exe", 60) is True
        sent = fake_toast.instances[0]
        assert "chrome.exe" in sent["msg"]
        assert "60" in sent["msg"]

    def test_limit_approaching_contains_remaining(self, fake_toast):
        notifier = Notifier()

        notifier.notify_limit_approaching("鳴潮", 120, 5)

        assert "鳴潮" in fake_toast.instances[0]["msg"]
        assert "5" in fake_toast.instances[0]["msg"]

    def test_send_failure_is_handled(self, fake_toast, monkeypatch):
        # 通知の失敗で計測が止まらないこと
        def boom(**_kwargs):
            raise RuntimeError("通知に失敗")

        monkeypatch.setattr(notifier_module, "Notification", boom)

        assert Notifier().notify_limit_reached("chrome.exe", 60) is False

    def test_unavailable_notifier_returns_false(self, monkeypatch):
        monkeypatch.setattr(notifier_module, "_WINOTIFY_AVAILABLE", False)

        assert Notifier().notify_limit_reached("chrome.exe", 60) is False


class TestIcon:
    """通知アイコン"""

    def test_default_icon_file_exists(self):
        assert os.path.exists(DEFAULT_ICON_PATH)

    def test_existing_icon_is_passed(self, fake_toast):
        Notifier().notify_limit_reached("chrome.exe", 60)

        assert fake_toast.instances[0]["icon"] == DEFAULT_ICON_PATH

    def test_missing_icon_is_omitted(self, fake_toast, tmp_path):
        # アイコンが無くても通知自体は送信する
        notifier = Notifier(icon_path=str(tmp_path / "missing.png"))

        assert notifier.notify_limit_reached("chrome.exe", 60) is True
        assert "icon" not in fake_toast.instances[0]
