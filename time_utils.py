from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


SEOUL_TZ = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    """Return the current timezone-aware timestamp in Korea."""
    return datetime.now(SEOUL_TZ)


def today_kst() -> date:
    """Return today's calendar date in Korea, independent of server timezone."""
    return now_kst().date()


def iso_now_kst() -> str:
    return now_kst().isoformat(timespec="seconds")
