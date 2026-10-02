"""Occurrence math for household routines: `interval_weeks` + `week_anchor_date`
rather than the calendar's RecurrencePattern, since alternating-week bins (and similar
every-other-week chores) don't fit that enum cleanly. `week_anchor_date` is any date
known to be a real occurrence (e.g. "bins go out this Tuesday") — every date exactly
`interval_weeks` whole weeks after or before it is also an occurrence, bounded by
`start_date`/`end_date`. Deliberately date-only, not datetime — DST-safe by
construction, since it never crosses a timezone conversion.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from mykhaya.models import HouseholdRoutine

MAX_LOOKAHEAD_DAYS = 60

# How far back to search for a routine's most recent due-or-overdue
# occurrence. Generous enough to cover not just weekly/bi-weekly cadences but
# also a routine using a large interval_weeks to approximate a monthly
# (~4 weeks) or yearly (~52 weeks) cadence — the only "monthly"/"yearly"
# recurrence this interval_weeks-based engine can express (see module
# docstring) — without needing a second occurrence-math system.
HOME_LOOKBACK_DAYS = 400

# The Home "To do" card only surfaces an occurrence once it is this many
# days (or fewer) from its due date — see
# household_routines.list_routines's `home=true` branch.
HOME_VISIBILITY_WINDOW_DAYS = 2


def is_occurrence_date(routine: HouseholdRoutine, day: date) -> bool:
    if not routine.enabled:
        return False
    if day < routine.start_date:
        return False
    if routine.end_date is not None and day > routine.end_date:
        return False
    offset_days = (day - routine.week_anchor_date).days
    if routine.repeat_unit == "daily":
        return True
    if offset_days % 7 != 0:
        return False
    weeks_since_anchor = offset_days // 7
    return weeks_since_anchor % routine.interval_weeks == 0


def next_occurrence_date(routine: HouseholdRoutine, on_or_after: date) -> date | None:
    """The soonest occurrence on or after `on_or_after`, or None if none falls within
    MAX_LOOKAHEAD_DAYS (e.g. the routine's end_date is sooner, or is not enabled)."""
    for offset in range(MAX_LOOKAHEAD_DAYS + 1):
        candidate = on_or_after + timedelta(days=offset)
        if routine.end_date is not None and candidate > routine.end_date:
            return None
        if is_occurrence_date(routine, candidate):
            return candidate
    return None


def last_occurrence_on_or_before(
    routine: HouseholdRoutine, day: date, *, max_lookback: int = HOME_LOOKBACK_DAYS
) -> date | None:
    """The most recent occurrence on or before `day`, or None if none falls within
    `max_lookback` days (e.g. the routine starts later than `day`, or is not
    enabled). The counterpart to next_occurrence_date, looking backwards —
    this is what lets a missed occurrence be identified as "the" current
    overdue occurrence rather than silently skipped."""
    for offset in range(max_lookback + 1):
        candidate = day - timedelta(days=offset)
        if candidate < routine.start_date:
            return None
        if is_occurrence_date(routine, candidate):
            return candidate
    return None


@dataclass(frozen=True)
class HomeOccurrenceSelection:
    occurrence_date: date
    is_completed: bool
    # 0 = overdue, 1 = due today, 2 = upcoming (within the visibility
    # window), 3 = completed today — the Home "To do" card's display order.
    priority: int


def select_home_occurrence(
    routine: HouseholdRoutine,
    today: date,
    is_completed: Callable[[date], bool],
) -> HomeOccurrenceSelection | None:
    """The single occurrence (if any) this routine should surface on the Home
    "To do" card for `today`.

    - A routine's most recent due-or-overdue occurrence stays visible,
      uncompleted, until it is actually completed — a missed occurrence never
      silently rolls forward to the next one.
    - Completing today's occurrence keeps it visible for the rest of that
      due date; once the due date has passed it drops off, and the *next*
      occurrence does not appear early just because the current one is done.
    - Only once there is no live/completed current occurrence does the next
      upcoming occurrence appear, and only once it is within
      HOME_VISIBILITY_WINDOW_DAYS days of its own due date.
    """
    last_due = last_occurrence_on_or_before(routine, today)
    if last_due is not None:
        if is_completed(last_due):
            if last_due == today:
                return HomeOccurrenceSelection(last_due, True, priority=3)
            # The due date has already passed (even though it was eventually
            # completed) — fall through to the next occurrence's own window
            # rather than lingering on Home.
        else:
            priority = 0 if last_due < today else 1
            return HomeOccurrenceSelection(last_due, False, priority=priority)
    upcoming = next_occurrence_date(routine, today + timedelta(days=1))
    if upcoming is not None and (upcoming - today).days <= HOME_VISIBILITY_WINDOW_DAYS:
        return HomeOccurrenceSelection(upcoming, False, priority=2)
    return None
