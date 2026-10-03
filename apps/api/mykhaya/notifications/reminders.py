"""Calendar event reminders: a durable due-reminder scan (no in-memory timers) plus the
worker-side delivery that re-validates everything at send time.

There is no persisted per-occurrence row (see mykhaya.calendar_occurrences) — recurrence
is expanded fresh on every scan, and the worker re-expands and re-checks the event again
at delivery time, so an edit or delete that lands after a reminder was scanned but before
it fires is caught rather than delivered stale.

Three ways an occurrence can produce a reminder, mutually exclusive per event:

* **Explicit** — the event itself has ``reminder_minutes``. One event-level outbox row per
  occurrence; every accepted attendee is notified. This applies to timed *and* all-day
  events, and always takes precedence over the defaults below.
* **Default timed** — a timed event with no ``reminder_minutes``: each accepted attendee
  who has ``default_event_reminder_enabled`` is reminded ``default_event_reminder_minutes``
  before the start. One outbox row per attendee.
* **Default all-day** — an all-day event with no ``reminder_minutes``: each accepted
  attendee who has ``all_day_reminder_enabled`` is reminded at their own
  ``all_day_reminder_time`` (in their own time zone) on the event's date.

The scan runs on every scheduler cycle (a couple of seconds apart). LOOKAHEAD is the width
of the "due soon" window, not the scan interval, so every reminder is found many times
before it fires; the outbox ``dedupe_key`` is what makes that harmless.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import DateTime, Interval, and_, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from mykhaya.calendar_occurrences import EffectiveOccurrence, expand_occurrences
from mykhaya.config import Settings
from mykhaya.features import is_feature_enabled
from mykhaya.models import (
    CalendarEvent,
    CalendarEventException,
    CalendarEventMember,
    FeatureKey,
    Group,
    NotificationPreferences,
    OutboxEvent,
    RecurrencePattern,
    User,
)
from mykhaya.notifications.deep_links import target
from mykhaya.notifications.engine import notify
from mykhaya.notifications.templates import render_notification
from mykhaya.notifications.visibility import can_view_event

# Short look-ahead so an edit landing between scans has minimal opportunity to race a
# reminder that was already scanned — see docs/architecture/notification-engine.md.
LOOKAHEAD = timedelta(minutes=2)
REMINDER_TOPIC = "notification.event_reminder"

# Outbox ``reminder_minutes`` value that marks a per-user all-day-preference reminder
# (there is no "minutes before" for those: they fire at a time of day).
ALL_DAY_PREFERENCE_REMINDER = -1

# The bounds below keep the scan's candidate query narrow. Each mirrors a validation limit
# elsewhere, and tests/test_calendar_reminder_defaults.py checks them so they cannot
# silently drift apart.
#
# Largest per-event reminder the API accepts (EventCreate/EventUpdate.reminder_minutes). The
# candidate query also applies each event's own, exact reminder_minutes; this constant
# bound exists so every branch has a selective range on start_at that Postgres can use the
# ix_calendar_events_start_at index for (a bound that depends on the row's own column
# cannot drive an index, and one such branch makes the planner abandon it for the whole OR).
MAX_EVENT_REMINDER_MINUTES = 10080
# Largest default timed reminder a user can choose
# (NotificationPreferencesUpdate.default_event_reminder_minutes).
MAX_DEFAULT_REMINDER_MINUTES = 120
# An all-day event is stored as a pure date at UTC midnight. Its reminder is due at the
# user's chosen *local* time on that date, which in UTC falls anywhere from 14 hours before
# that midnight (UTC+14, 00:00) to 36 hours after it (UTC-12, 23:59). Two days either side
# of "now" therefore covers every user without needing to know their zone in SQL.
ALL_DAY_DUE_SPREAD = timedelta(days=2)
# One day of slack for the moved-occurrence case, matching
# calendar_occurrences.recurrence_candidate_filter: a series whose recurrence_until or
# recurrence_end_date has just passed may still own an occurrence that an exception moved
# to a later time.
EXCEPTION_MOVE_SLACK = timedelta(days=1)

# The only part of the scan whose cost grows with every active recurring series — each one
# is walked from its first occurrence on every expansion — is the *default* reminders for
# recurring events without an explicit reminder. Those are swept at most this often by the
# scheduler (a "due soon" window is LOOKAHEAD wide, so a sweep every 30 s still sees every
# reminder several times before it fires). Everything else is scanned on every call.
DEFAULT_RECURRING_SWEEP_INTERVAL = timedelta(seconds=30)
_last_default_recurring_sweep: float | None = None


async def _calendar_notification_eligible(db: AsyncSession, group_id: uuid.UUID) -> bool:
    """Whether a Home is currently eligible to receive a Calendar-owned
    scheduled notification (Phase 3A) — checked both at scan time (so a
    platform/Home-disabled Calendar never gets an OutboxEvent enqueued) and
    again at delivery (so a module change in the gap between scan and
    delivery is still caught, matching this file's existing "re-validate
    fresh" pattern for occurrence/edit races).

    Calendar carries no boolean commercial entitlement of its own (see
    mykhaya.entitlements.PLAN_DEFINITIONS — Free vs Family only differ in
    per-resource numeric limits, enforced at mutation time in
    routers.calendar, never at reminder delivery time), so this never checks
    one: a reminder for an existing, preserved event must still fire even if
    that event's calendar is currently read_only_due_to_plan after a
    downgrade — restriction blocks new writes, never awareness of a real,
    already-existing appointment."""
    return await is_feature_enabled(db, FeatureKey.calendar, group_id) and await is_feature_enabled(
        db, FeatureKey.notifications, group_id
    )


def _reminder_when_and_location(
    event: CalendarEvent,
    occurrence_start: datetime,
    reminder_minutes: int,
    *,
    is_all_day: bool,
    location_text: str | None,
) -> tuple[str, str]:
    """Pre-formats the two dynamic fragments (when the event starts, and an
    optional location suffix) that calendar.event.reminder's template
    interpolates — all the actual time-zone/wording logic stays here in
    Python; the template itself only ever does plain text substitution.
    `is_all_day`/`location_text` are the EFFECTIVE (possibly occurrence-
    overridden) values — the caller passes the base event's own when there
    is no override, so this function never has to know the difference."""
    tz: tzinfo
    try:
        tz = ZoneInfo(event.timezone)
    except ZoneInfoNotFoundError:
        tz = UTC
    local_start = occurrence_start.astimezone(tz)
    if reminder_minutes == 0:
        when = "now"
    elif is_all_day:
        when = "today"
    else:
        when = f"at {local_start.strftime('%H:%M')}"
    location = f" at {location_text}" if location_text else ""
    return when, location


def _minutes(value: Any) -> ColumnElement[timedelta]:
    """A SQL interval of ``value`` minutes (a column or a plain int)."""
    return func.make_interval(0, 0, 0, 0, 0, value, type_=Interval())


def _timestamp(value: datetime) -> ColumnElement[datetime]:
    return literal(value, DateTime(timezone=True))


def _series_still_open(now: datetime, slack: timedelta) -> ColumnElement[bool]:
    """A recurring series that has not ended before ``now - slack``. Mirrors the two ways
    expand_occurrences stops generating occurrences (recurrence_until / recurrence_end_date);
    recurrence_count cannot be evaluated in SQL and is left to the expansion."""
    cutoff = now - slack
    return and_(
        or_(CalendarEvent.recurrence_until.is_(None), CalendarEvent.recurrence_until >= cutoff),
        or_(
            CalendarEvent.recurrence_end_date.is_(None),
            CalendarEvent.recurrence_end_date >= cutoff.date(),
        ),
    )


async def due_reminder_candidates(
    db: AsyncSession, now: datetime, *, include_default_recurring: bool = True
) -> list[CalendarEvent]:
    """Events that could plausibly produce a due reminder inside ``[now, now + LOOKAHEAD)``.

    This is only a pre-filter — the exact due calculation (per attendee preference, per
    occurrence, per time zone) happens in Python — but it is deliberately narrow, because
    the scan runs on every scheduler cycle:

    * One-off events are matched on their own ``start_at`` within the horizon that kind of
      reminder can reach, so Postgres can use ``ix_calendar_events_start_at`` and the result
      does not grow with the number of events in the past or far future. Events of Disabled
      or Archived Homes are excluded.
    * Recurring events cannot be bounded by ``start_at`` (it is the first occurrence), so
      they are bounded by "has started" / "has not ended" instead. Explicit-reminder series
      are always included, exactly as before. Default-reminder series — the new, much larger
      set — are included only when ``include_default_recurring`` is true (see
      DEFAULT_RECURRING_SWEEP_INTERVAL).
    """
    window_end = now + LOOKAHEAD
    window_end_sql = _timestamp(window_end)

    one_off = and_(
        CalendarEvent.recurrence == RecurrencePattern.none,
        or_(
            # Explicit reminder: due when start - reminder_minutes is inside the window.
            and_(
                CalendarEvent.reminder_minutes.isnot(None),
                CalendarEvent.start_at >= now,
                CalendarEvent.start_at < window_end + timedelta(minutes=MAX_EVENT_REMINDER_MINUTES),
                CalendarEvent.start_at < window_end_sql + _minutes(CalendarEvent.reminder_minutes),
            ),
            # Default timed reminder: at most MAX_DEFAULT_REMINDER_MINUTES before the start.
            and_(
                CalendarEvent.reminder_minutes.is_(None),
                CalendarEvent.is_all_day.is_(False),
                CalendarEvent.start_at >= now,
                CalendarEvent.start_at
                < window_end + timedelta(minutes=MAX_DEFAULT_REMINDER_MINUTES),
            ),
            # Default all-day reminder: a time of day on the event's date, in the user's zone.
            and_(
                CalendarEvent.reminder_minutes.is_(None),
                CalendarEvent.is_all_day.is_(True),
                CalendarEvent.start_at > now - ALL_DAY_DUE_SPREAD,
                CalendarEvent.start_at < window_end + ALL_DAY_DUE_SPREAD,
            ),
        ),
    )
    rows = await db.scalars(
        select(CalendarEvent).where(CalendarEvent.deleted_at.is_(None), one_off)
    )
    candidates = list(rows.all())

    series_with_explicit_reminder = and_(
        CalendarEvent.reminder_minutes.isnot(None),
        CalendarEvent.start_at < window_end_sql + _minutes(CalendarEvent.reminder_minutes),
        _series_still_open(now, EXCEPTION_MOVE_SLACK),
    )
    recurring_branches = [series_with_explicit_reminder]
    if include_default_recurring:
        recurring_branches.append(
            and_(
                CalendarEvent.reminder_minutes.is_(None),
                CalendarEvent.start_at < window_end + ALL_DAY_DUE_SPREAD,
                _series_still_open(now, ALL_DAY_DUE_SPREAD + EXCEPTION_MOVE_SLACK),
            )
        )
    rows = await db.scalars(
        select(CalendarEvent).where(
            CalendarEvent.deleted_at.is_(None),
            CalendarEvent.recurrence != RecurrencePattern.none,
            or_(*recurring_branches),
        )
    )
    candidates.extend(rows.all())
    return await _in_active_homes(db, candidates)


async def _in_active_homes(db: AsyncSession, events: list[CalendarEvent]) -> list[CalendarEvent]:
    """Drop events of Disabled/Archived Homes. Done here, in one batched query, rather than
    by joining ``groups`` in the candidate SQL: that join makes Postgres drive the plan from
    ``groups`` and probe every Home, instead of using the narrow ``start_at`` range."""
    group_ids = list({event.group_id for event in events})
    active: set[uuid.UUID] = set()
    for start in range(0, len(group_ids), 1000):
        chunk = group_ids[start : start + 1000]
        active.update(
            await db.scalars(select(Group.id).where(Group.id.in_(chunk), Group.is_active.is_(True)))
        )
    return [event for event in events if event.group_id in active]


def _default_recurring_sweep_due() -> bool:
    """Whether this production scan should include the default-reminder recurring series.
    Process-local and purely an optimisation: a restart just sweeps sooner, and the outbox
    rows themselves are the durable record."""
    global _last_default_recurring_sweep
    current = monotonic()
    if (
        _last_default_recurring_sweep is not None
        and current - _last_default_recurring_sweep
        < DEFAULT_RECURRING_SWEEP_INTERVAL.total_seconds()
    ):
        return False
    _last_default_recurring_sweep = current
    return True


async def _enqueue_reminder(db: AsyncSession, payload: dict[str, object], dedupe_key: str) -> None:
    await db.execute(
        pg_insert(OutboxEvent)
        .values(topic=REMINDER_TOPIC, payload=payload, dedupe_key=dedupe_key)
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
    )


async def _exceptions_by_event(
    db: AsyncSession, event_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[datetime, CalendarEventException]]:
    grouped: dict[uuid.UUID, dict[datetime, CalendarEventException]] = {}
    for start in range(0, len(event_ids), 1000):
        chunk = event_ids[start : start + 1000]
        for row in await db.scalars(
            select(CalendarEventException).where(CalendarEventException.event_id.in_(chunk))
        ):
            grouped.setdefault(row.event_id, {})[row.occurrence_start] = row
    return grouped


async def _accepted_members_by_event(
    db: AsyncSession, event_ids: list[uuid.UUID]
) -> dict[uuid.UUID, set[uuid.UUID]]:
    grouped: dict[uuid.UUID, set[uuid.UUID]] = {}
    for start in range(0, len(event_ids), 1000):
        chunk = event_ids[start : start + 1000]
        result = await db.execute(
            select(CalendarEventMember.event_id, CalendarEventMember.user_id).where(
                CalendarEventMember.event_id.in_(chunk),
                CalendarEventMember.attendance_status == "accepted",
            )
        )
        for event_id, user_id in result.all():
            grouped.setdefault(event_id, set()).add(user_id)
    return grouped


async def _preferences_with_users(
    db: AsyncSession, user_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, tuple[NotificationPreferences, User]]:
    ids = list(user_ids)
    found: dict[uuid.UUID, tuple[NotificationPreferences, User]] = {}
    for start in range(0, len(ids), 1000):
        chunk = ids[start : start + 1000]
        result = await db.execute(
            select(NotificationPreferences, User)
            .join(User, User.id == NotificationPreferences.user_id)
            .where(NotificationPreferences.user_id.in_(chunk))
        )
        for preferences, user in result.all():
            found[user.id] = (preferences, user)
    return found


async def _accepted_attendee_ids(
    db: AsyncSession, event: CalendarEvent, member_ids_override: list[uuid.UUID] | None
) -> set[uuid.UUID]:
    """Who a reminder is for: an occurrence-level participant override is authoritative;
    otherwise the event's own accepted participants. A reminder is an attendee notification,
    not a visibility one — Home admins and calendar-share viewers only get one if they are
    an explicit participant."""
    if member_ids_override is not None:
        return set(member_ids_override)
    return (await _accepted_members_by_event(db, [event.id])).get(event.id, set())


def _user_zone(user: User, event: CalendarEvent) -> tzinfo:
    for name in (user.timezone, event.timezone):
        if name:
            try:
                return ZoneInfo(name)
            except ZoneInfoNotFoundError:
                continue
    return UTC


async def scan_due_reminders(
    db: AsyncSession, settings: Settings, now: datetime | None = None
) -> None:
    """Enqueue an idempotent outbox row for every reminder due inside the next LOOKAHEAD.

    ``now`` exists so tests can place the scan at an exact instant. A production call
    (``now=None``) additionally throttles the default-reminder sweep of recurring series to
    DEFAULT_RECURRING_SWEEP_INTERVAL; an explicit ``now`` always does the complete scan."""
    include_default_recurring = True if now is not None else _default_recurring_sweep_due()
    now = now or datetime.now(UTC)
    window_end = now + LOOKAHEAD

    eligible: dict[uuid.UUID, bool] = {}
    candidates: list[CalendarEvent] = []
    for event in await due_reminder_candidates(
        db, now, include_default_recurring=include_default_recurring
    ):
        if event.group_id not in eligible:
            eligible[event.group_id] = await _calendar_notification_eligible(db, event.group_id)
        if eligible[event.group_id]:
            candidates.append(event)
    if not candidates:
        return

    exceptions = await _exceptions_by_event(db, [event.id for event in candidates])
    members = await _accepted_members_by_event(
        db, [event.id for event in candidates if event.reminder_minutes is None]
    )

    # Events with no explicit reminder, collected so every attendee's preferences can be
    # loaded in one query rather than one per event.
    default_occurrences: list[tuple[CalendarEvent, EffectiveOccurrence, set[uuid.UUID]]] = []
    for event in candidates:
        event_exceptions = exceptions.get(event.id, {})
        if event.reminder_minutes is not None:
            await _scan_explicit(db, event, event_exceptions, now, window_end)
            continue
        if event.is_all_day:
            occurrences = expand_occurrences(
                event, now - ALL_DAY_DUE_SPREAD, window_end + ALL_DAY_DUE_SPREAD, event_exceptions
            )
        else:
            occurrences = expand_occurrences(
                event,
                now,
                window_end + timedelta(minutes=MAX_DEFAULT_REMINDER_MINUTES),
                event_exceptions,
            )
        for effective in occurrences:
            attendees = (
                set(effective.member_ids_override)
                if effective.member_ids_override is not None
                else members.get(event.id, set())
            )
            if attendees:
                default_occurrences.append((event, effective, attendees))

    if default_occurrences:
        # A user with no preferences row yet has not been through any notification or
        # settings flow, so they have nothing opted in: they receive explicit reminders
        # only, until a row exists.
        attendee_ids: set[uuid.UUID] = set()
        for _event, _occurrence, attendees in default_occurrences:
            attendee_ids |= attendees
        preferences = await _preferences_with_users(db, attendee_ids)
        for event, effective, attendees in default_occurrences:
            for user_id in sorted(attendees):
                if user_id in preferences:
                    await _scan_default_for_user(
                        db, event, effective, *preferences[user_id], now, window_end
                    )
    await db.commit()


async def _scan_explicit(
    db: AsyncSession,
    event: CalendarEvent,
    event_exceptions: dict[datetime, CalendarEventException],
    now: datetime,
    window_end: datetime,
) -> None:
    """An event with its own reminder_minutes: one event-level row per due occurrence.

    An occurrence-level reminder_minutes override changes *when* this specific
    occurrence's reminder is due; it never invents a reminder the base event doesn't have
    (an event with no reminder of its own uses the defaults instead)."""
    assert event.reminder_minutes is not None
    search_end = window_end + timedelta(minutes=event.reminder_minutes)
    for effective in expand_occurrences(event, now, search_end, event_exceptions):
        effective_minutes = (
            effective.reminder_minutes
            if effective.reminder_minutes is not None
            else event.reminder_minutes
        )
        due_at = effective.start_at - timedelta(minutes=effective_minutes)
        if not (now <= due_at < window_end):
            continue
        # Keyed by the CANONICAL occurrence_start (stable identity), never the
        # effective/possibly-moved start — deliver_event_reminder re-validates by looking
        # this same canonical key back up, exactly the way editing/re-opening an
        # occurrence does.
        key = f"reminder:{event.id}:{effective.occurrence_start.isoformat()}:{effective_minutes}"
        await _enqueue_reminder(
            db,
            {
                "event_id": str(event.id),
                "occurrence_start": effective.occurrence_start.isoformat(),
                "reminder_minutes": effective_minutes,
            },
            key,
        )


async def _scan_default_for_user(
    db: AsyncSession,
    event: CalendarEvent,
    effective: EffectiveOccurrence,
    preferences: NotificationPreferences,
    user: User,
    now: datetime,
    window_end: datetime,
) -> None:
    occurrence = effective.occurrence_start.isoformat()
    if event.is_all_day:
        if not preferences.all_day_reminder_enabled:
            return
        # An all-day event names a calendar date, stored at UTC midnight (see
        # routers.calendar._all_day_midnight) — so the date is the UTC date. Converting to
        # the event's own zone first would shift it back a day for any zone behind UTC.
        event_date: date = effective.start_at.astimezone(UTC).date()
        due_at = datetime.combine(
            event_date, preferences.all_day_reminder_time, tzinfo=_user_zone(user, event)
        ).astimezone(UTC)
        if not (now <= due_at < window_end):
            return
        await _enqueue_reminder(
            db,
            {
                "event_id": str(event.id),
                "occurrence_start": occurrence,
                "reminder_minutes": ALL_DAY_PREFERENCE_REMINDER,
                "recipient_user_id": str(user.id),
                # Full precision, so a time with seconds still matches at delivery.
                "all_day_reminder_time": preferences.all_day_reminder_time.isoformat(),
            },
            f"reminder:{event.id}:{occurrence}:{user.id}:all-day",
        )
        return

    if not preferences.default_event_reminder_enabled:
        return
    minutes = preferences.default_event_reminder_minutes
    due_at = effective.start_at - timedelta(minutes=minutes)
    if not (now <= due_at < window_end):
        return
    await _enqueue_reminder(
        db,
        {
            "event_id": str(event.id),
            "occurrence_start": occurrence,
            "reminder_minutes": minutes,
            "recipient_user_id": str(user.id),
        },
        f"reminder:{event.id}:{occurrence}:{user.id}:{minutes}",
    )


async def deliver_event_reminder(
    db: AsyncSession,
    settings: Settings,
    event_id: str,
    occurrence_start_iso: str,
    reminder_minutes: int,
    recipient_user_id: str | None = None,
    all_day_reminder_time: str | None = None,
) -> None:
    event = await db.get(CalendarEvent, uuid.UUID(event_id))
    if event is None or event.deleted_at is not None:
        return  # deleted since it was scanned — nothing to deliver
    if not await _calendar_notification_eligible(db, event.group_id):
        return  # Calendar module/platform state changed since this was scanned

    occurrence_start = datetime.fromisoformat(occurrence_start_iso)
    # Re-expand fresh, keyed on the CANONICAL occurrence_start scan_due_
    # reminders stored: if the event (or just this one occurrence, via an
    # exception) was edited/deleted/moved since this reminder was scanned,
    # the exact occurrence we were about to fire for may no longer exist,
    # or may now be due at a different effective time — skip rather than
    # deliver stale content; a fresh scan picks up any still-valid reminder
    # under its own new due time.
    exceptions = {
        row.occurrence_start: row
        for row in (
            await db.scalars(
                select(CalendarEventException).where(CalendarEventException.event_id == event.id)
            )
        ).all()
    }
    matching = next(
        (
            effective
            for effective in expand_occurrences(
                event,
                occurrence_start - timedelta(minutes=1),
                occurrence_start + timedelta(minutes=1),
                exceptions,
            )
            if effective.occurrence_start == occurrence_start
        ),
        None,
    )
    if matching is None:
        return

    attendees = await _accepted_attendee_ids(db, event, matching.member_ids_override)
    if recipient_user_id is None:
        # Event-level reminder from the event's own reminder_minutes.
        effective_minutes = (
            matching.reminder_minutes
            if matching.reminder_minutes is not None
            else event.reminder_minutes
        )
        if effective_minutes != reminder_minutes:
            return
        recipient_ids = attendees
    else:
        # A per-user reminder from the defaults. Everything the scan decided is checked
        # again here, so a change in the gap between scan and delivery wins.
        if event.reminder_minutes is not None:
            return  # the event now has its own reminder, which takes precedence
        try:
            recipient_uuid = uuid.UUID(recipient_user_id)
        except ValueError:
            return
        if recipient_uuid not in attendees:
            return  # declined or removed since the scan
        if reminder_minutes == ALL_DAY_PREFERENCE_REMINDER:
            if not matching.is_all_day or all_day_reminder_time is None:
                return
            try:
                selected_time = time.fromisoformat(all_day_reminder_time)
            except ValueError:
                return
            preference = await db.scalar(
                select(NotificationPreferences).where(
                    NotificationPreferences.user_id == recipient_uuid,
                    NotificationPreferences.all_day_reminder_enabled.is_(True),
                    NotificationPreferences.all_day_reminder_time == selected_time,
                )
            )
        else:
            if matching.is_all_day:
                return
            preference = await db.scalar(
                select(NotificationPreferences).where(
                    NotificationPreferences.user_id == recipient_uuid,
                    NotificationPreferences.default_event_reminder_enabled.is_(True),
                    NotificationPreferences.default_event_reminder_minutes == reminder_minutes,
                )
            )
        if preference is None:
            return  # switched off, or changed to a different time, since the scan
        recipient_ids = {recipient_uuid}

    idempotency_key = f"reminder:{event_id}:{occurrence_start_iso}:{reminder_minutes}"
    when, location = _reminder_when_and_location(
        event,
        matching.start_at,
        reminder_minutes,
        is_all_day=matching.is_all_day,
        location_text=matching.location_text,
    )
    _subject, body = await render_notification(
        db,
        "calendar.event.reminder",
        {"event_title": matching.title, "event_when": when, "event_location": location},
    )
    # The category toggle every reminder shares (NotificationPreferences.event_reminders_
    # enabled) and the channel toggles are applied by notify() itself.
    for recipient_id in sorted(recipient_ids):
        if not await can_view_event(
            db, event, recipient_id, member_ids_override=matching.member_ids_override
        ):
            continue  # membership/permissions changed since this reminder was scanned
        await notify(
            db,
            settings=settings,
            recipient_user_id=recipient_id,
            notification_type="event_reminder",
            title=matching.title,
            body=body,
            idempotency_key=f"{idempotency_key}:{recipient_id}",
            group_id=event.group_id,
            related_entity_type="calendar_event",
            related_entity_id=event.id,
            deep_link=target("calendar_event", event.id),
        )
