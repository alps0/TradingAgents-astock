from __future__ import annotations

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def get_report_now() -> datetime:
    """Return the current time in the configured report timezone.

    The timezone is controlled by REPORT_TIMEZONE in the environment, defaulting
    to Asia/Shanghai for Chinese users. If the timezone is invalid, it falls
    back to UTC.
    """
    return datetime.now(get_report_timezone())


def format_report_time(value: datetime | None = None) -> str:
    """Format a datetime using the configured report timezone."""
    dt = value or get_report_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(get_report_timezone()).strftime("%Y-%m-%d %H:%M:%S")


def get_report_timezone():
    tz_name = os.getenv("REPORT_TIMEZONE", "Asia/Shanghai").strip() or "Asia/Shanghai"
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return timezone.utc
