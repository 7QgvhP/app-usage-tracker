"""
dates.py - 日付と期間の取り扱い

「今日」「今週」といった期間を YYYY-MM-DD の組へ変換する。
データベースには触れないため、単体で試せる。
"""

from __future__ import annotations

import calendar
from datetime import date as date_type
from datetime import datetime, timedelta

# 画面とAPIで扱う期間の種類
VALID_PERIODS = ("day", "week", "month")


def today_str() -> str:
    """今日の日付を YYYY-MM-DD 形式で返す"""
    return datetime.now().strftime("%Y-%m-%d")


def now_str() -> str:
    """現在時刻を YYYY-MM-DD HH:MM:SS 形式で返す"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_period_dates(
    period: str,
    base: date_type | None = None,
    limit: date_type | None = None,
) -> tuple[str, str]:
    """期間（day/week/month）に対応する開始日・終了日を返す

    base を含む期間の全体を返す。week は月曜〜日曜、month は1日〜末日。
    未知の期間が渡された場合は day と同じ扱いにする。

    limit を渡すとその日までで打ち切る。今日を渡せば、まだ来ていない
    日付を期間に含めずに済む（今週の表示が「月曜〜今日」になる）。
    """
    target = base or datetime.now().date()

    if period == "week":
        start = target - timedelta(days=target.weekday())
        end = start + timedelta(days=6)
    elif period == "month":
        start = target.replace(day=1)
        last_day = calendar.monthrange(target.year, target.month)[1]
        end = target.replace(day=last_day)
    else:
        start = end = target

    if limit is not None and end > limit:
        end = max(start, limit)

    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
