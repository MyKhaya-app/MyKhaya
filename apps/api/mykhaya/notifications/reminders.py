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
from mykhaya.models import CalendarEvent, FeatureKey, OutboxEvent
from mykhaya.notifications.deep_links import target
from mykhaya.notifications.engine import notify
from mykhaya.notifications.visibility import can_view_event, viewer_ids_for_event

# Short look-ahead so an edit landing between scans has minimal opportunity to race a
# reminder that was already scanned — see docs/architecture/notification-engine.md.
LOOKAHEAD = timedelta(minutes=2)
# The largest supported reminder_minutes preset (1 day before) — bounds how far ahead
# the scan needs to expand occurrences to find one whose reminder could be due soon.
MAX_REMINDER_OFFSET_MINUTES = 1440
REMINDER_TOPIC = "notification.event_reminder"


def _format_reminder_body(
    event: CalendarEvent, occurrence_start: datetime, reminder_minutes: int
) -> str:
    tz: tzinfo
    try:
        tz = ZoneInfo(event.timezone)
    except ZoneInfoNotFoundError:
        tz = UTC
    local_start = occurrence_start.astimezone(tz)
    if reminder_minutes == 0:
        when = "now"
    elif event.is_all_day:
        when = "today"
    else:
        when = f"at {local_start.strftime('%H:%M')}"
    location = f" at {event.location_text}" if event.location_text else ""
    return f"{event.title} starts {when}{location}."


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
        for occurrence_start, _occurrence_end in expand_occurrences(event, now, search_end):
            due_at = occurrence_start - offset
            if not (now <= due_at < window_end):
                continue
            key = (str(event.id), occurrence_start.isoformat(), event.reminder_minutes)
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
    # Re-expand fresh: if the event was edited (time changed, reminder changed,
    # recurrence changed) since this reminder was scanned, the exact occurrence we were
    # about to fire for may no longer exist — skip rather than deliver stale content.
    if event.reminder_minutes != reminder_minutes:
        return
    still_valid = any(
        start == occurrence_start
        for start, _end in expand_occurrences(
            event, occurrence_start - timedelta(minutes=1), occurrence_start + timedelta(minutes=1)
        )
    )
    if not still_valid:
        return

    idempotency_key = f"reminder:{event_id}:{occurrence_start_iso}:{reminder_minutes}"
    body = _format_reminder_body(event, occurrence_start, reminder_minutes)
    for recipient_id in await viewer_ids_for_event(db, event):
        if not await can_view_event(db, event, recipient_id):
            continue  # membership/permissions changed since this reminder was scanned
        await notify(
            db,
            settings=settings,
            recipient_user_id=recipient_id,
            notification_type="event_reminder",
            title=event.title,
            body=body,
            idempotency_key=f"{idempotency_key}:{recipient_id}",
            group_id=event.group_id,
            related_entity_type="calendar_event",
            related_entity_id=event.id,
            deep_link=target("calendar_event", event.id),
        )
