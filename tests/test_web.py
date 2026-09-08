"""
test_web.py - Webサーバーの起動時チェックのテスト
"""

from __future__ import annotations

import socket

import pytest

from app.web import check_port_available


def _free_port() -> int:
    """使用されていないポート番号を取得する"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestCheckPortAvailable:
    """ポート重複の検出"""

    def test_free_port_passes(self):
        check_port_available("127.0.0.1", _free_port())

    def test_used_port_raises(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # 二重起動時のサーバーと同じ条件（SO_REUSEADDR）で占有する
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        try:
            with pytest.raises(OSError, match="既に使用されています"):
                check_port_available("127.0.0.1", port)
        finally:
            listener.close()
