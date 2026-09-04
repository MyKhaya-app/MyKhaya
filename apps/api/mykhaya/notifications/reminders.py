"""Calendar event reminders: a durable due-reminder scan (no in-memory timers) plus the
worker-side delivery that re-validates everything at send time.

There is no persisted per-occurrence row (see mykhaya.calendar_occurrences) — recurrence
is expanded fresh on every scan, and the worker re-expands and re-checks the event again
at delivery time, so an edit or delete that lands after a reminder was scanned but before
it fires is caught rather than delivered stale.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.calendar_occurrences import expand_occurrences
from mykhaya.config import Settings
from mykhaya.features import is_feature_enabled
from mykhaya.models import CalendarEvent, CalendarEventException, FeatureKey, OutboxEvent
from mykhaya.notifications.deep_links import target
from mykhaya.notifications.engine import notify
from mykhaya.notifications.templates import render_notification
from mykhaya.notifications.visibility import can_view_event, viewer_ids_for_event

# Short look-ahead so an edit landing between scans has minimal opportunity to race a
# reminder that was already scanned — see docs/architecture/notification-engine.md.
LOOKAHEAD = timedelta(minutes=2)
# The largest supported reminder_minutes preset (1 day before) — bounds how far ahead
# the scan needs to expand occurrences to find one whose reminder could be due soon.
MAX_REMINDER_OFFSET_MINUTES = 1440
REMINDER_TOPIC = "notification.event_reminder"


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


async def scan_due_reminders(db: AsyncSession, settings: Settings) -> None:
    now = datetime.now(UTC)
    window_end = now + LOOKAHEAD

    events = (
        await db.scalars(
            select(CalendarEvent).where(
                CalendarEvent.deleted_at.is_(None),
                CalendarEvent.reminder_minutes.isnot(None),
            )
        )
    ).all()
    for event in events:
        if event.reminder_minutes is None:
            continue  # narrows for mypy; the query above already filters this
        if not await is_feature_enabled(db, FeatureKey.notifications, event.group_id):
            continue
        offset = timedelta(minutes=event.reminder_minutes)
        search_end = window_end + offset
        exceptions = {
            row.occurrence_start: row
            for row in (
                await db.scalars(
                    select(CalendarEventException).where(
                        CalendarEventException.event_id == event.id
                    )
                )
            ).all()
        }
        for effective in expand_occurrences(event, now, search_end, exceptions):
            # An occurrence-level reminder_minutes override changes *when*
            # this specific occurrence's reminder is due; a deliberately
            # cleared one (reminder_minutes explicitly None on the base
            # event with no override) never reaches this loop at all — the
            # query above already requires the base event's own
            # reminder_minutes to be set, and an override only ever
            # narrows/shifts timing, never invents a reminder the base
            # event doesn't have.
            effective_minutes = (
                effective.reminder_minutes
                if effective.reminder_minutes is not None
                else event.reminder_minutes
            )
            effective_offset = timedelta(minutes=effective_minutes)
            due_at = effective.start_at - effective_offset
            if not (now <= due_at < window_end):
                continue
            # Keyed by the CANONICAL occurrence_start (stable identity),
            # never the effective/possibly-moved start — deliver_event_
            # reminder re-validates by looking this same canonical key back
            # up, exactly the way editing/re-opening an occurrence does.
            key = (str(event.id), effective.occurrence_start.isoformat(), effective_minutes)
            await db.execute(
                pg_insert(OutboxEvent)
                .values(
                    topic=REMINDER_TOPIC,
                    payload={
                        "event_id": key[0],
                        "occurrence_start": key[1],
                        "reminder_minutes": key[2],
                    },
                    dedupe_key=f"reminder:{key[0]}:{key[1]}:{key[2]}",
                )
                .on_conflict_do_nothing(index_elements=["dedupe_key"])
            )
    await db.commit()


async def deliver_event_reminder(
    db: AsyncSession,
    settings: Settings,
    event_id: str,
    occurrence_start_iso: str,
    reminder_minutes: int,
) -> None:
    event = await db.get(CalendarEvent, uuid.UUID(event_id))
    if event is None or event.deleted_at is not None:
        return  # deleted since it was scanned — nothing to deliver

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
    effective_minutes = (
        matching.reminder_minutes
        if matching.reminder_minutes is not None
        else event.reminder_minutes
    )
    if effective_minutes != reminder_minutes:
        return

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
    for recipient_id in await viewer_ids_for_event(
        db, event, member_ids_override=matching.member_ids_override
    ):
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
