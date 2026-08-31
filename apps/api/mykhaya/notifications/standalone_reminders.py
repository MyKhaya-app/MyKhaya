"""Standalone reminders: a durable due+cadence scan mirroring
mykhaya.notifications.reminders (calendar event reminders) and
mykhaya.notifications.routines (household routines) — same outbox/worker/notify()
pipeline, same idempotent-dedupe-key approach — but with its own "until completed"
nag cadence, a concept neither of those needs.

Cadence design: rather than storing "when was this last sent" anywhere, every scan
computes which cadence *slot* is currently due from `due_at` and `now` alone —
slot 0 for `once` (always), and `floor((now - due_at) / interval)` for
hourly/daily/weekly. This is what makes a scheduler outage safe: on restart the
scan recomputes the CURRENT slot directly rather than replaying every slot that
elapsed while it was down, and the OutboxEvent.dedupe_key (which embeds the slot
number) means a slot can only ever be enqueued once, however many scan cycles
observe it before the next slot begins.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.features import is_feature_enabled
from mykhaya.models import (
    FeatureKey,
    Membership,
    OutboxEvent,
    Reminder,
    ReminderCadence,
    ReminderCompletion,
    ReminderMember,
    RoutineScope,
)
from mykhaya.notifications.deep_links import target
from mykhaya.notifications.engine import notify
from mykhaya.notifications.quiet_hours import home_timezone
from mykhaya.notifications.reminder_occurrences import (
    is_occurrence_date,
    last_occurrence_on_or_before,
)
from mykhaya.notifications.templates import render_notification
from mykhaya.notifications.visibility import active_membership

REMINDER_TOPIC = "notification.standalone_reminder"

CADENCE_INTERVALS = {
    ReminderCadence.hourly: timedelta(hours=1),
    ReminderCadence.daily: timedelta(days=1),
    ReminderCadence.weekly: timedelta(weeks=1),
}


async def _is_completed(db: AsyncSession, reminder_id: uuid.UUID, occurrence_date: date) -> bool:
    return (
        await db.scalar(
            select(ReminderCompletion.id).where(
                ReminderCompletion.reminder_id == reminder_id,
                ReminderCompletion.occurrence_date == occurrence_date,
            )
        )
    ) is not None


def _current_slot(reminder: Reminder, due_at_utc: datetime, now_utc: datetime) -> int | None:
    """The cadence slot due right now, or None if not due yet at all."""
    if now_utc < due_at_utc:
        return None
    if reminder.cadence == ReminderCadence.once:
        return 0
    interval = CADENCE_INTERVALS[reminder.cadence]
    return int((now_utc - due_at_utc) // interval)


async def scan_due_reminders(db: AsyncSession, settings: Settings) -> None:
    now_utc = datetime.now(UTC)

    reminders = (await db.scalars(select(Reminder).where(Reminder.enabled.is_(True)))).all()
    for reminder in reminders:
        if not await is_feature_enabled(db, FeatureKey.notifications, reminder.group_id):
            continue
        tz = await home_timezone(db, reminder.group_id, settings.default_timezone)
        today_local = now_utc.astimezone(tz).date()

        occurrence_date = last_occurrence_on_or_before(reminder, today_local)
        if occurrence_date is None:
            continue
        if await _is_completed(db, reminder.id, occurrence_date):
            continue

        due_at_utc = datetime.combine(occurrence_date, reminder.due_time, tzinfo=tz).astimezone(UTC)
        slot = _current_slot(reminder, due_at_utc, now_utc)
        if slot is None:
            continue

        dedupe_key = (
            f"reminder:{reminder.id}:{occurrence_date.isoformat()}:{reminder.cadence.value}:{slot}"
        )
        await db.execute(
            pg_insert(OutboxEvent)
            .values(
                topic=REMINDER_TOPIC,
                payload={
                    "reminder_id": str(reminder.id),
                    "occurrence_date": occurrence_date.isoformat(),
                    "cadence": reminder.cadence.value,
                    "slot": slot,
                },
                dedupe_key=dedupe_key,
            )
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
        )
    await db.commit()


async def _recipients_for(db: AsyncSession, reminder: Reminder) -> set[uuid.UUID]:
    if reminder.scope == RoutineScope.personal:
        return {reminder.owner_user_id} if reminder.owner_user_id else set()
    explicit = (
        await db.scalars(
            select(ReminderMember.user_id).where(ReminderMember.reminder_id == reminder.id)
        )
    ).all()
    if explicit:
        return set(explicit)
    household_wide = (
        await db.scalars(
            select(Membership.user_id).where(
                Membership.group_id == reminder.group_id, Membership.removed_at.is_(None)
            )
        )
    ).all()
    return set(household_wide)


async def deliver_standalone_reminder(
    db: AsyncSession,
    settings: Settings,
    reminder_id: str,
    occurrence_date_iso: str,
    cadence: str,
    slot: int,
) -> None:
    reminder = await db.get(Reminder, uuid.UUID(reminder_id))
    if reminder is None or not reminder.enabled:
        return  # disabled or deleted since it was scanned

    occurrence_date = date.fromisoformat(occurrence_date_iso)
    # Re-validate fresh: an edit to due_date/repeat/cadence, or a completion that
    # landed since this was scanned, may mean this slot is no longer valid — skip
    # rather than deliver a stale or already-actioned nag.
    if not is_occurrence_date(reminder, occurrence_date):
        return
    if reminder.cadence.value != cadence:
        return
    if await _is_completed(db, reminder.id, occurrence_date):
        return

    idempotency_key = f"reminder:{reminder_id}:{occurrence_date_iso}:{cadence}:{slot}"
    _subject, body = await render_notification(
        db, "reminder.due", {"reminder_title": reminder.title}
    )
    for recipient_id in await _recipients_for(db, reminder):
        if await active_membership(db, reminder.group_id, recipient_id) is None:
            continue  # membership removed since this reminder was scanned
        await notify(
            db,
            settings=settings,
            recipient_user_id=recipient_id,
            notification_type="standalone_reminder",
            title=reminder.title,
            body=body,
            idempotency_key=f"{idempotency_key}:{recipient_id}",
            group_id=reminder.group_id,
            related_entity_type="reminder",
            related_entity_id=reminder.id,
            deep_link=target("reminder", reminder.id),
        )
