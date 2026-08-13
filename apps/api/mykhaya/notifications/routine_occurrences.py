"""Occurrence math for household routines: `interval_weeks` + `week_anchor_date`
rather than the calendar's RecurrencePattern, since alternating-week bins (and similar
every-other-week chores) don't fit that enum cleanly. `week_anchor_date` is any date
known to be a real occurrence (e.g. "bins go out this Tuesday") — every date exactly
`interval_weeks` whole weeks after or before it is also an occurrence, bounded by
`start_date`/`end_date`. Deliberately date-only, not datetime — DST-safe by
construction, since it never crosses a timezone conversion.
"""

from __future__ import annotations

from datetime import date, timedelta

from mykhaya.models import HouseholdRoutine

MAX_LOOKAHEAD_DAYS = 60


def is_occurrence_date(routine: HouseholdRoutine, day: date) -> bool:
    if not routine.enabled:
        return False
    if day < routine.start_date:
        return False
    if routine.end_date is not None and day > routine.end_date:
        return False
    offset_days = (day - routine.week_anchor_date).days
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
