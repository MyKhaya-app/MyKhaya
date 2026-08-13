"""Annual, date-anchored occurrence math for birthdays. Deliberately month/day only —
`mykhaya.models.ChildProfile`/`User` also store an optional `birth_year`, but this
module never reads it: children get an age band, never a computed age, by design (see
docs/architecture/data-model.md), and the same "no computed age" rule is applied
uniformly to adult birthdays too rather than drawing an inconsistent line.
"""

from __future__ import annotations

import calendar as month_calendar
from datetime import date


def is_birthday_date(birth_month: int, birth_day: int, day: date) -> bool:
    if day.month == birth_month and day.day == birth_day:
        return True
    # A Feb 29 birthday is observed on Feb 28 in non-leap years, rather than silently
    # skipping the reminder for three years out of four.
    if birth_month == 2 and birth_day == 29 and day.month == 2 and day.day == 28:
        return not month_calendar.isleap(day.year)
    return False


def next_birthday_date(birth_month: int, birth_day: int, on_or_after: date) -> date:
    for year in (on_or_after.year, on_or_after.year + 1):
        day_in_month = min(birth_day, month_calendar.monthrange(year, birth_month)[1])
        candidate = date(year, birth_month, day_in_month)
        if candidate >= on_or_after:
            return candidate
    # Unreachable: the loop always finds a match by the second year.
    raise AssertionError("no upcoming birthday date found")
