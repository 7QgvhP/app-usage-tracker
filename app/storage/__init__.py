"""
storage - SQLiteによるデータ永続化

外から使う名前はここへ集めている。分割前と同じく `from app.storage import ...`
で参照できるため、利用側は中の構成を知らなくてよい。

- constants  : 共有する定数
- dates      : 期間の計算（データベースに触れない）
- migrations : スキーマの定義と移行
- store      : 使用時間・区間・端末・制限時間の読み書き
"""

from app.storage.constants import LOCAL_DEVICE
from app.storage.dates import VALID_PERIODS, get_period_dates, now_str, today_str
from app.storage.migrations import SCHEMA_VERSION
from app.storage.store import StorageError, UsageStore

__all__ = [
    "LOCAL_DEVICE",
    "SCHEMA_VERSION",
    "StorageError",
    "UsageStore",
    "VALID_PERIODS",
    "get_period_dates",
    "now_str",
    "today_str",
]
