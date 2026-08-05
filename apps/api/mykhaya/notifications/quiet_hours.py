"""Quiet hours: suppress push during a user's chosen window, unless the notification is
flagged critical (e.g. medication). Non-critical notifications are still written in-app —
quiet hours affects push delivery only, nothing is silently lost.
"""

from datetime import time
from zoneinfo import ZoneInfo

from mykhaya.models import NotificationPreferences


def is_within_quiet_hours(prefs: NotificationPreferences, now_local: time) -> bool:
    start, end = prefs.quiet_hours_start, prefs.quiet_hours_end
    if start is None or end is None:
        return False
    if start <= end:
        return start <= now_local < end
    # Wraps past midnight, e.g. 22:00 -> 07:00.
    return now_local >= start or now_local < end


def effective_timezone(user_timezone: str | None, fallback: str) -> ZoneInfo:
    try:
        return ZoneInfo(user_timezone) if user_timezone else ZoneInfo(fallback)
    except Exception:
        # A bad stored/config timezone name must never crash delivery.
        return ZoneInfo("UTC")
