"""Occurrence math for standalone Reminders — deliberately simpler than
mykhaya.notifications.routine_occurrences: no interval_weeks/week_anchor_date/
end_date, since a Reminder only ever repeats never/daily/weekly from due_date
indefinitely (see mykhaya.models.ReminderRepeat). Kept as its own module, not
merged into routine_occurrences, so the two domains can evolve independently —
see docs/architecture/notification-engine.md on why Reminders and Routines stay
separate concepts even where the occurrence shape looks similar.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from mykhaya.models import Reminder, ReminderRepeat

MAX_LOOKAHEAD_DAYS = 60
HOME_LOOKBACK_DAYS = 400
HOME_VISIBILITY_WINDOW_DAYS = 2


def is_occurrence_date(reminder: Reminder, day: date) -> bool:
    if not reminder.enabled:
        return False
    if day < reminder.due_date:
        return False
    if reminder.repeat == ReminderRepeat.never:
        return day == reminder.due_date
    if reminder.repeat == ReminderRepeat.daily:
        return True
    return (day - reminder.due_date).days % 7 == 0


def next_occurrence_date(reminder: Reminder, on_or_after: date) -> date | None:
    for offset in range(MAX_LOOKAHEAD_DAYS + 1):
        candidate = on_or_after + timedelta(days=offset)
        if is_occurrence_date(reminder, candidate):
            return candidate
        if reminder.repeat == ReminderRepeat.never and candidate > reminder.due_date:
            return None
    return None


def last_occurrence_on_or_before(
    reminder: Reminder, day: date, *, max_lookback: int = HOME_LOOKBACK_DAYS
) -> date | None:
    for offset in range(max_lookback + 1):
        candidate = day - timedelta(days=offset)
        if candidate < reminder.due_date:
            return None
        if is_occurrence_date(reminder, candidate):
            return candidate
    return None


@dataclass(frozen=True)
class HomeOccurrenceSelection:
    occurrence_date: date
    is_completed: bool
    # 0 = overdue, 1 = due today, 2 = upcoming (within the visibility window),
    # 3 = completed today — matches routine_occurrences.HomeOccurrenceSelection's
    # Home "To do" priority ordering exactly, so the two resource types interleave
    # sensibly on one combined list.
    priority: int


def select_home_occurrence(
    reminder: Reminder,
    today: date,
    is_completed: Callable[[date], bool],
) -> HomeOccurrenceSelection | None:
    last_due = last_occurrence_on_or_before(reminder, today)
    if last_due is not None:
        if is_completed(last_due):
            if last_due == today:
                return HomeOccurrenceSelection(last_due, True, priority=3)
        else:
            priority = 0 if last_due < today else 1
            return HomeOccurrenceSelection(last_due, False, priority=priority)
    upcoming = next_occurrence_date(reminder, today + timedelta(days=1))
    if upcoming is not None and (upcoming - today).days <= HOME_VISIBILITY_WINDOW_DAYS:
        return HomeOccurrenceSelection(upcoming, False, priority=2)
    return None
