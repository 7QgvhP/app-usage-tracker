"""
api - REST API のルーティング

ルートは扱う対象ごとにモジュールを分けている。
読み込むだけで api_bp へ登録されるため、ここでまとめて取り込む。

例外処理は create_app() 側のエラーハンドラへ集約しているため、
各ハンドラでは正常系の処理と入力値の検証のみを行う。
"""

from app.web.api.blueprint import api_bp
from app.web.api.helpers import HISTORY_DAYS, MAX_HISTORY_DAYS

# 取り込むことでルートが登録される（順序は問わない）
from app.web.api import limits, status, sync, timeline, usage  # noqa: E402,F401

__all__ = ["HISTORY_DAYS", "MAX_HISTORY_DAYS", "api_bp"]
