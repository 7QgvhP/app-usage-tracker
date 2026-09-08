"""
notifier.py - Windows トースト通知

制限時間への到達および到達前の予告を通知する。
winotify が利用できない環境や通知の送信に失敗した場合でも、
計測処理を止めないよう例外は内部で処理する。
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# 通知に表示するアイコン（Windowsのトーストは png を想定）
DEFAULT_ICON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "icon.png"
)

try:
    from winotify import Notification

    _WINOTIFY_AVAILABLE = True
except ImportError:  # pragma: no cover - 実行環境に依存するため
    Notification = None
    _WINOTIFY_AVAILABLE = False
    logger.warning("winotify が見つからないため、通知は無効になります")


class Notifier:
    """トースト通知の送信を担当するクラス"""

    def __init__(self, app_id: str = "App Usage Tracker", icon_path: str | None = None):
        self.app_id = app_id
        self.icon_path = DEFAULT_ICON_PATH if icon_path is None else icon_path
        self.available = _WINOTIFY_AVAILABLE

    def _send(self, title: str, message: str) -> bool:
        """トースト通知を送信する

        Returns:
            送信できた場合は True、利用不可・失敗時は False。
        """
        if not self.available:
            logger.debug(f"通知を送信できません（winotify 未導入）: {title} / {message}")
            return False

        options = {"app_id": self.app_id, "title": title, "msg": message}
        # アイコンが見つからない場合は指定せず、通知自体は表示させる
        if self.icon_path and os.path.exists(self.icon_path):
            options["icon"] = self.icon_path

        try:
            toast = Notification(**options)
            toast.show()
            return True
        except Exception as e:
            # 通知の失敗で計測が止まらないよう、ここで握りつぶしてログに残す
            logger.error(f"通知の送信に失敗しました: {e}")
            return False

    def notify_limit_reached(self, app_name: str, limit_minutes: int) -> bool:
        """制限時間への到達を通知する"""
        return self._send(
            title="⏰ 制限時間に到達しました",
            message=f"{app_name} の使用時間が {limit_minutes} 分に達しました。",
        )

    def notify_limit_approaching(
        self, app_name: str, limit_minutes: int, remaining_minutes: int
    ) -> bool:
        """制限時間が近づいていることを通知する"""
        return self._send(
            title="⚠ まもなく制限時間です",
            message=f"{app_name} の残り時間: あと {remaining_minutes} 分（制限: {limit_minutes} 分）",
        )
