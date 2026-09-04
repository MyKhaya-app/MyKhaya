"""Recurrence expansion, shared between the calendar router and the reminder scanner.

Extracted (not duplicated) so both call sites agree exactly on what "this event's next
occurrence" means — see docs/architecture/notification-engine.md on why the reminder
scanner must reuse this rather than reimplementing occurrence math a second time.

Occurrence-exception aware (Phase: per-occurrence recurring-event edit/delete): this is
the single place a CalendarEvent's generated recurrence sequence is combined with any
CalendarEventException rows for it to produce the *effective* occurrences every
consumer (month/week/day/schedule, Coming Up, Home, reminders, briefing, shared
calendars) actually sees. No consumer should re-implement exception application —
they all call expand_occurrences/next_occurrence_on_or_after and get overrides/
deletions for free.
"""

from __future__ import annotations

import calendar as month_calendar
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.models import CalendarEvent, CalendarEventException, RecurrencePattern

MAX_RANGE_DAYS = 93


@dataclass(frozen=True)
class EffectiveOccurrence:
    """One generated recurrence instance after any CalendarEventException has
    been applied. `occurrence_start` is always the CANONICAL original
    generated start — the stable identity key — even when `start_at` differs
    from it because the occurrence was moved. See CalendarEventException's
    own docstring (models.py) for why identity must key off the canonical
    slot, not the effective one.
    """

    occurrence_start: datetime
    start_at: datetime
    end_at: datetime
    title: str
    description: str | None
    is_all_day: bool
    location_text: str | None
    calendar_id: uuid.UUID
    label_id: uuid.UUID | None
    reminder_minutes: int | None
    # None = this occurrence has no participant override; use the base
    # event's own current CalendarEventMember rows. A (possibly empty) list
    # means this occurrence's effective participants were explicitly
    # overridden and that list is authoritative for it.
    member_ids_override: list[uuid.UUID] | None
    is_overridden: bool


async def load_exceptions(
    db: AsyncSession, event_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[datetime, CalendarEventException]]:
    """Every CalendarEventException for the given events, grouped by
    event_id then keyed by canonical occurrence_start — exactly the shape
    expand_occurrences/next_occurrence_on_or_after expect. The one shared
    query every consumer (calendar API, Home, reminders, briefing, shared
    calendars) uses to load exceptions before expanding occurrences — so
    none of them re-implement this lookup independently. One query for a
    whole page/range of events, never N+1 per event."""
    if not event_ids:
        return {}
    rows = (
        await db.scalars(
            select(CalendarEventException).where(CalendarEventException.event_id.in_(event_ids))
        )
    ).all()
    result: dict[uuid.UUID, dict[datetime, CalendarEventException]] = {}
    for row in rows:
        result.setdefault(row.event_id, {})[row.occurrence_start] = row
    return result


def _coalesce[T](override: T | None, base: T) -> T:
    """NULL-on-the-exception-row means "inherit the base event's current
    value" — see CalendarEventException's own docstring (models.py)."""
    return override if override is not None else base


def _effective(
    event: CalendarEvent,
    canonical_start: datetime,
    canonical_end: datetime,
    exception: CalendarEventException | None,
) -> EffectiveOccurrence:
    if exception is None:
        return EffectiveOccurrence(
            occurrence_start=canonical_start,
            start_at=canonical_start,
            end_at=canonical_end,
            title=event.title,
            description=event.description,
            is_all_day=event.is_all_day,
            location_text=event.location_text,
            calendar_id=event.calendar_id,
            label_id=event.label_id,
            reminder_minutes=event.reminder_minutes,
            member_ids_override=None,
            is_overridden=False,
        )
    return EffectiveOccurrence(
        occurrence_start=canonical_start,
        start_at=_coalesce(exception.start_at, canonical_start),
        end_at=_coalesce(exception.end_at, canonical_end),
        title=_coalesce(exception.title, event.title),
        description=_coalesce(exception.description, event.description),
        is_all_day=_coalesce(exception.is_all_day, event.is_all_day),
        location_text=_coalesce(exception.location_text, event.location_text),
        calendar_id=_coalesce(exception.calendar_id, event.calendar_id),
        label_id=_coalesce(exception.label_id, event.label_id),
        reminder_minutes=_coalesce(exception.reminder_minutes, event.reminder_minutes),
        member_ids_override=(
            [uuid.UUID(value) for value in exception.member_ids]
            if exception.member_ids is not None
            else None
        ),
        is_overridden=True,
    )


def recurrence_candidate_filter(range_start: datetime, range_end: datetime) -> ColumnElement[bool]:
    """The same SQL pre-filter routers/calendar.py::list_events uses: a non-recurring
    event matches only if its own window overlaps the range; a recurring event's *base*
    end_at only describes its first occurrence, so only recurrence_until (when set) can
    rule a series out at the SQL level — expand_occurrences remains the source of truth
    for exactly which occurrences fall in range. Shared so the briefing generator agrees
    exactly with the calendar API on what "today's events" means.

    Deliberately widened by one day on both sides relative to the naive
    range: an occurrence exception can move an occurrence's effective time
    outside its canonical window (e.g. the canonical slot is just before
    range_start but the override moves it into range) — the *canonical*
    recurrence definition must still be considered a candidate so
    expand_occurrences gets the chance to apply that override. One day is
    enough for any single move (moving further than that starts a fresh
    "is this occurrence still recognisably 'that' occurrence" question the
    product doesn't need to answer here).
    """
    widened_start = range_start - timedelta(days=1)
    widened_end = range_end + timedelta(days=1)
    return and_(
        CalendarEvent.start_at < widened_end,
        or_(
            and_(
                CalendarEvent.recurrence == RecurrencePattern.none,
                CalendarEvent.end_at > widened_start,
            ),
            and_(
                CalendarEvent.recurrence != RecurrencePattern.none,
                or_(
                    CalendarEvent.recurrence_until.is_(None),
                    CalendarEvent.recurrence_until > widened_start,
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
    event: CalendarEvent,
    range_start: datetime,
    range_end: datetime,
    exceptions: dict[datetime, CalendarEventException] | None = None,
) -> list[EffectiveOccurrence]:
    """Effective occurrences of `event` overlapping [range_start, range_end).

    `exceptions` is keyed by canonical occurrence_start (exact instant
    match — CalendarEventException.occurrence_start is always written as
    exactly the canonical generated start, never a rounded/truncated
    value, so this is a plain dict lookup, not a range/tolerance match).
    Pass the full set of this event's exceptions; this function decides
    which ones are relevant to the requested range itself (a moved
    occurrence can be relevant to a range its canonical slot never
    touches).
    """
    exceptions = exceptions or {}
    occurrences: list[EffectiveOccurrence] = []
    duration = event.end_at - event.start_at
    limit_end = min(range_end, range_start + timedelta(days=MAX_RANGE_DAYS))

    if event.recurrence == RecurrencePattern.none:
        exception = exceptions.get(event.start_at)
        if exception is not None and exception.is_deleted:
            return []
        effective = _effective(event, event.start_at, event.end_at, exception)
        if effective.start_at < limit_end and effective.end_at > range_start:
            return [effective]
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
    recurrence_until_local = (
        event.recurrence_until.astimezone(tz) if event.recurrence_until else None
    )
    generated = 0
    # Deliberately not bounded by range_start at the loop level (only the
    # append condition is) — an occurrence exception can move an occurrence
    # from well before the requested range into it, so every canonical
    # occurrence up to limit_end must be visited and checked against its
    # exception, exactly as before this feature (this loop always walked
    # from the series start; only what it *appended* was range-filtered).
    while current_start < limit_end_local:
        if (
            event.recurrence_end_date is not None
            and current_start.date() > event.recurrence_end_date
        ):
            break
        # Checked BEFORE this candidate is used, exactly like
        # recurrence_end_date above — recurrence_until is an inclusive
        # cutoff instant, and checking it only after already appending the
        # occurrence (as this used to) let exactly one occurrence past the
        # intended boundary through. See _truncate_series_after's docstring
        # in routers/calendar.py for the historical workaround this fix
        # supersedes.
        if recurrence_until_local and current_start > recurrence_until_local:
            break
        current_end = current_start + duration
        canonical_start_utc = current_start.astimezone(UTC)
        exception = exceptions.get(canonical_start_utc)
        if exception is None or not exception.is_deleted:
            canonical_end_utc = current_end.astimezone(UTC)
            effective = _effective(event, canonical_start_utc, canonical_end_utc, exception)
            if effective.end_at > range_start and effective.start_at < limit_end:
                occurrences.append(effective)
        generated += 1
        if event.recurrence_count and generated >= event.recurrence_count:
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


# Safety valve only, not a user-facing horizon: a pathological recurrence (e.g.
# daily with no end) stepping toward a cursor decades away still resolves in a
# handful of iterations for realistic cursors, so this cap is never expected to
# bite in practice — see next_occurrence_on_or_after.
_MAX_OCCURRENCE_STEPS = 10_000


def upcoming_candidate_filter(cursor: datetime) -> ColumnElement[bool]:
    """SQL pre-filter for "could this event's series ever produce an
    occurrence on/after `cursor`" — paired with next_occurrence_on_or_after,
    which computes the exact next occurrence per candidate in memory.
    Deliberately has no upper bound: the number of matching rows is bounded
    by how many event *definitions* a Home/share has, never by how far in
    the future the next occurrence of any one of them falls, which is what
    lets routers.calendar's upcoming_events endpoint (Home -> "Coming up")
    answer "next 3 occurrences" without an arbitrary future-date horizon.

    Widened by one day before `cursor` for the same reason
    recurrence_candidate_filter is — a canonical occurrence just before the
    cursor could have been moved to on/after it by an override."""
    widened_cursor = cursor - timedelta(days=1)
    return or_(
        and_(
            CalendarEvent.recurrence == RecurrencePattern.none,
            CalendarEvent.start_at >= widened_cursor,
        ),
        and_(
            CalendarEvent.recurrence != RecurrencePattern.none,
            or_(
                CalendarEvent.recurrence_until.is_(None),
                CalendarEvent.recurrence_until >= widened_cursor,
            ),
        ),
    )


def next_occurrence_on_or_after(
    event: CalendarEvent,
    cursor: datetime,
    exceptions: dict[datetime, CalendarEventException] | None = None,
) -> EffectiveOccurrence | None:
    """The single next EFFECTIVE occurrence of `event` whose effective start
    is on/after `cursor`, or None if the series never reaches it (a one-off
    event already in the past, or a recurring series that ends — via
    recurrence_count/recurrence_until/recurrence_end_date — before ever
    reaching `cursor`, or one whose only remaining occurrences are all
    individually deleted).

    Unlike expand_occurrences, this is not bounded by MAX_RANGE_DAYS: it
    steps forward occurrence-by-occurrence using the exact same recurrence
    math (kept in lockstep with expand_occurrences deliberately — see that
    function's docstring on why both call sites must agree), but the loop
    itself is pure in-memory arithmetic with no DB calls, so "next
    occurrence in 6 months" and "next occurrence tomorrow" cost the same
    small, bounded number of iterations. Paired with
    upcoming_candidate_filter to answer "next N occurrences" without ever
    expanding or reading an unbounded range of occurrences — see
    routers.calendar's upcoming_events endpoint (Home -> "Coming up")."""
    exceptions = exceptions or {}
    duration = event.end_at - event.start_at
    if event.recurrence == RecurrencePattern.none:
        exception = exceptions.get(event.start_at)
        if exception is not None and exception.is_deleted:
            return None
        effective = _effective(event, event.start_at, event.end_at, exception)
        if effective.start_at >= cursor:
            return effective
        return None

    tz: tzinfo
    try:
        tz = ZoneInfo(event.timezone)
    except ZoneInfoNotFoundError:
        tz = UTC
    current_start = event.start_at.astimezone(tz)
    recurrence_until_local = (
        event.recurrence_until.astimezone(tz) if event.recurrence_until else None
    )
    generated = 0
    for _ in range(_MAX_OCCURRENCE_STEPS):
        if (
            event.recurrence_end_date is not None
            and current_start.date() > event.recurrence_end_date
        ):
            return None
        # See expand_occurrences' matching comment: checked before this
        # candidate is used, not after.
        if recurrence_until_local and current_start > recurrence_until_local:
            return None
        generated += 1
        current_end = current_start + duration
        canonical_start_utc = current_start.astimezone(UTC)
        exception = exceptions.get(canonical_start_utc)
        if exception is None or not exception.is_deleted:
            canonical_end_utc = current_end.astimezone(UTC)
            effective = _effective(event, canonical_start_utc, canonical_end_utc, exception)
            if effective.start_at >= cursor:
                return effective
        if event.recurrence_count and generated >= event.recurrence_count:
            return None

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
            return None

    return None


def canonical_occurrences_up_to(
    event: CalendarEvent, occurrence_start: datetime
) -> list[datetime]:
    """Every CANONICAL (generated, pre-exception) occurrence start of
    `event`'s series from its beginning up to and including
    `occurrence_start`, in order, as UTC instants — never range-bounded
    the way expand_occurrences is, but still bounded by
    _MAX_OCCURRENCE_STEPS as a safety valve (matching
    next_occurrence_on_or_after's own bound) and by
    count/until/end_date/`occurrence_start` itself in the normal case.

    This is the one shared walk behind three small, related operations
    that all need "where does this occurrence sit in its own series":
    - is_canonical_occurrence: was the last collected start exactly
      `occurrence_start`?
    - occurrence_index_before / occurrence_immediately_before (used by the
      "this and future" split): how many occurrences precede it, and what
      was the last one before it?

    Deliberately NOT exception-aware — this walks the base recurrence
    definition only. Exceptions describe divergences from the canonical
    series; the canonical series itself is what this answers questions
    about (e.g. "is this occurrence_start actually one this recurrence
    rule would generate" has to be checked before an exception can even be
    created against it).
    """
    if event.recurrence == RecurrencePattern.none:
        return [event.start_at] if event.start_at <= occurrence_start else []

    tz: tzinfo
    try:
        tz = ZoneInfo(event.timezone)
    except ZoneInfoNotFoundError:
        tz = UTC
    current_start = event.start_at.astimezone(tz)
    target_local = occurrence_start.astimezone(tz)
    recurrence_until_local = (
        event.recurrence_until.astimezone(tz) if event.recurrence_until else None
    )
    collected: list[datetime] = []
    generated = 0
    for _ in range(_MAX_OCCURRENCE_STEPS):
        if (
            event.recurrence_end_date is not None
            and current_start.date() > event.recurrence_end_date
        ):
            break
        # See expand_occurrences' matching comment: checked before this
        # candidate is used, not after.
        if recurrence_until_local and current_start > recurrence_until_local:
            break
        if current_start > target_local:
            break
        collected.append(current_start.astimezone(UTC))
        generated += 1
        if current_start == target_local:
            break
        if event.recurrence_count and generated >= event.recurrence_count:
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

    return collected


def is_canonical_occurrence(event: CalendarEvent, occurrence_start: datetime) -> bool:
    """Does `event`'s own recurrence rule actually generate an occurrence
    at exactly `occurrence_start`? The mandatory server-side check before
    ever creating/looking up a CalendarEventException — never trust a
    client-supplied occurrence_start blindly (see routers.calendar's
    security requirements: this is what stops a caller passing an
    arbitrary timestamp, or another event's occurrence_start, and having
    it accepted)."""
    collected = canonical_occurrences_up_to(event, occurrence_start)
    return bool(collected) and collected[-1] == occurrence_start
