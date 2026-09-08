"""
constants.py - storage の各モジュールが共有する定数

migrations と store の双方が使うため、どちらかに置くと循環参照になる。
"""

from __future__ import annotations

# このPC自身の記録に付ける端末名。スマホなど外部から取り込んだ記録と区別する。
# usage_log.device / usage_session.device の既定値と一致させること。
LOCAL_DEVICE = "pc"
