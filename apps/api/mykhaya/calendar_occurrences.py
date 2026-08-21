"""Recurrence expansion, shared between the calendar router and the reminder scanner.

Extracted (not duplicated) so both call sites agree exactly on what "this event's next
occurrence" means — see docs/architecture/notification-engine.md on why the reminder
scanner must reuse this rather than reimplementing occurrence math a second time.
"""

from __future__ import annotations

import calendar as month_calendar
from datetime import UTC, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import ColumnElement, and_, or_

from mykhaya.models import CalendarEvent, RecurrencePattern

MAX_RANGE_DAYS = 93


def recurrence_candidate_filter(range_start: datetime, range_end: datetime) -> ColumnElement[bool]:
    """The same SQL pre-filter routers/calendar.py::list_events uses: a non-recurring
    event matches only if its own window overlaps the range; a recurring event's *base*
    end_at only describes its first occurrence, so only recurrence_until (when set) can
    rule a series out at the SQL level — expand_occurrences remains the source of truth
    for exactly which occurrences fall in range. Shared so the briefing generator agrees
    exactly with the calendar API on what "today's events" means.
    """
    return and_(
        CalendarEvent.start_at < range_end,
        or_(
            and_(
                CalendarEvent.recurrence == RecurrencePattern.none,
                CalendarEvent.end_at > range_start,
            ),
            and_(
                CalendarEvent.recurrence != RecurrencePattern.none,
                or_(
                    CalendarEvent.recurrence_until.is_(None),
                    CalendarEvent.recurrence_until > range_start,
                ),
            ),
        ),
    )


def month_increment(value: datetime, step: int) -> datetime:
    target_month = value.month + step
    year = value.year + (target_month - 1) // 12
    month = ((target_month - 1) % 12) + 1
    day = min(value.day, month_calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def expand_occurrences(
    event: CalendarEvent, range_start: datetime, range_end: datetime
) -> list[tuple[datetime, datetime]]:
    occurrences: list[tuple[datetime, datetime]] = []
    duration = event.end_at - event.start_at
    limit_end = min(range_end, range_start + timedelta(days=MAX_RANGE_DAYS))

    if event.recurrence == RecurrencePattern.none:
        if event.start_at < limit_end and event.end_at > range_start:
            return [(event.start_at, event.end_at)]
        return []

    # Step recurrence in the event's own local timezone, not raw UTC. start_at
    # is stored as an absolute UTC instant, so naive UTC timedelta arithmetic
    # ("+7 days") silently drifts the displayed *local* time by an hour
    # whenever a DST transition falls inside the recurrence range — a weekly
    # 9am event would render as 8am or 10am local after the clocks change.
    # zoneinfo-aware datetimes add timedeltas to the wall-clock fields, so
    # stepping in local time and converting back to UTC per-occurrence keeps
    # the local wall-clock time stable across DST, matching how a person
    # actually expects "every Tuesday at 9am" to behave.
    tz: tzinfo
    try:
        tz = ZoneInfo(event.timezone)
    except ZoneInfoNotFoundError:
        tz = UTC
    current_start = event.start_at.astimezone(tz)
    limit_end_local = limit_end.astimezone(tz)
    range_start_local = range_start.astimezone(tz)
    recurrence_until_local = (
        event.recurrence_until.astimezone(tz) if event.recurrence_until else None
    )
    generated = 0
    while current_start < limit_end_local:
        if (
            event.recurrence_end_date is not None
            and current_start.date() > event.recurrence_end_date
        ):
            break
        current_end = current_start + duration
        if current_end > range_start_local and current_start < limit_end_local:
            occurrences.append((current_start.astimezone(UTC), current_end.astimezone(UTC)))
        generated += 1
        if event.recurrence_count and generated >= event.recurrence_count:
            break
        if recurrence_until_local and current_start > recurrence_until_local:
            break

        if event.recurrence == RecurrencePattern.daily:
            current_start = current_start + timedelta(days=event.recurrence_interval)
        elif event.recurrence == RecurrencePattern.weekly:
            current_start = current_start + timedelta(weeks=event.recurrence_interval)
        elif event.recurrence == RecurrencePattern.monthly:
            current_start = month_increment(current_start, event.recurrence_interval)
        elif event.recurrence == RecurrencePattern.yearly:
            current_start = month_increment(current_start, 12 * event.recurrence_interval)
        elif event.recurrence == RecurrencePattern.weekdays:
            next_day = current_start + timedelta(days=1)
            while next_day.weekday() > 4:
                next_day = next_day + timedelta(days=1)
            current_start = next_day
        else:
            break

    return occurrences
