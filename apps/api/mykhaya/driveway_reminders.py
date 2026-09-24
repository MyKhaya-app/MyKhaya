"""Driveway → Nudges integration (Phase 4).

Driveway never builds a parallel reminder system — every Driveway-generated
reminder is an ordinary `Reminder` row (see routers.reminders), made
findable/updatable later via three additive nullable columns
(`source_type`/`source_id`/`source_event`) that every other caller (the
generic Reminder CRUD, the notification scheduler, the Nudges UI) simply
never looks at. See models.Reminder's docstring and migration
0093_driveway_reminder_links.

This module is the one place that creates/updates/queries those links, so
future structured sources (DVLA/DVSA-driven, Phase 5+) call the same
`upsert_driveway_reminder` helper Phase 4's manual "Add reminder" form uses
today, rather than duplicating this logic.
"""

from __future__ import annotations

import uuid
from datetime import date, time
from enum import StrEnum

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.models import Reminder, ReminderCadence, ReminderRepeat, RoutineScope, TodoCategory, Vehicle

# The only source_type Phase 4 writes. Kept as a plain constant (not a
# Postgres enum) because source_type is polymorphic — a future module could
# add its own value without an ALTER TYPE migration touching Driveway's.
DRIVEWAY_SOURCE_TYPE = "driveway"

VEHICLES_CATEGORY_NAME = "Vehicles"


class DrivewayReminderEventType(StrEnum):
    """A small, deliberately international controlled set — never
    country-specific terms like "mot"/"road_tax" (those are presentation-
    layer labels only, chosen by the frontend from country_code)."""

    manual = "manual"
    inspection = "inspection"
    registration = "registration"
    insurance = "insurance"
    service = "service"
    other = "other"


async def ensure_vehicles_category(
    db: AsyncSession, group_id: uuid.UUID, created_by: uuid.UUID
) -> TodoCategory:
    """Idempotent get-or-create of the Home's Driveway-managed "Vehicles"
    category. Case-insensitive lookup so it's never duplicated by a
    differently-cased existing category (Driveway's own, or a user's).
    Safe under concurrent first-reminder races via ON CONFLICT DO NOTHING
    against the existing (group_id, name) uniqueness constraint."""
    existing = await db.scalar(
        select(TodoCategory).where(
            TodoCategory.group_id == group_id,
            TodoCategory.name.ilike(VEHICLES_CATEGORY_NAME),
        )
    )
    if existing is not None:
        return existing
    await db.execute(
        pg_insert(TodoCategory)
        .values(
            group_id=group_id,
            name=VEHICLES_CATEGORY_NAME,
            created_by=created_by,
            managed_source=DRIVEWAY_SOURCE_TYPE,
        )
        .on_conflict_do_nothing(constraint="uq_todo_category_home_name")
    )
    category = await db.scalar(
        select(TodoCategory).where(
            TodoCategory.group_id == group_id,
            TodoCategory.name.ilike(VEHICLES_CATEGORY_NAME),
        )
    )
    assert category is not None  # either we just inserted it, or the race winner did
    return category


def _reminder_owner(vehicle: Vehicle) -> uuid.UUID | None:
    return vehicle.owner_user_id if vehicle.scope == RoutineScope.personal else None


async def upsert_driveway_reminder(
    db: AsyncSession,
    *,
    group_id: uuid.UUID,
    vehicle: Vehicle,
    event_type: DrivewayReminderEventType,
    due_date: date,
    title: str,
    due_time: time = time(9, 0),
    description: str | None = None,
    repeat: ReminderRepeat = ReminderRepeat.never,
    cadence: ReminderCadence = ReminderCadence.once,
    created_by: uuid.UUID,
) -> tuple[Reminder, bool]:
    """Ensures the Vehicles category exists, then creates or updates the
    linked managed reminder. Returns (reminder, created).

    `event_type=manual` always creates a new row — a vehicle may carry any
    number of independent manual reminders ("MOT due", "insurance renewal",
    "tyre replacement", ...), so there is no natural (vehicle, event) key to
    upsert against for them (mirrors uq_reminder_source_event_active's
    'manual' exception).

    Every other event_type upserts against the existing active managed
    reminder for (source_type=driveway, vehicle.id, event_type) if one
    exists — at most one, matching uq_reminder_source_event_active — so a
    future structured resync (Phase 5+) can call this repeatedly as its
    source data changes without ever creating duplicates.

    Scope/owner are always derived from the vehicle, never client-supplied
    — see sync_reminder_scope_to_vehicle for what happens when a vehicle's
    own scope later changes.
    """
    category = await ensure_vehicles_category(db, group_id, created_by)

    if event_type != DrivewayReminderEventType.manual:
        existing = await db.scalar(
            select(Reminder)
            .where(
                Reminder.group_id == group_id,
                Reminder.source_type == DRIVEWAY_SOURCE_TYPE,
                Reminder.source_id == vehicle.id,
                Reminder.source_event == event_type.value,
                Reminder.enabled.is_(True),
            )
            .with_for_update()
        )
        if existing is not None:
            existing.title = title
            existing.description = description
            existing.due_date = due_date
            existing.due_time = due_time
            existing.scope = vehicle.scope
            existing.owner_user_id = _reminder_owner(vehicle)
            existing.category_id = category.id
            await db.flush()
            return existing, False

    reminder = Reminder(
        group_id=group_id,
        title=title,
        description=description,
        category_id=category.id,
        scope=vehicle.scope,
        owner_user_id=_reminder_owner(vehicle),
        due_date=due_date,
        due_time=due_time,
        repeat=repeat,
        cadence=cadence,
        created_by=created_by,
        source_type=DRIVEWAY_SOURCE_TYPE,
        source_id=vehicle.id,
        source_event=event_type.value,
    )
    db.add(reminder)
    await db.flush()
    return reminder, True


async def reminders_for_vehicle(
    db: AsyncSession, group_id: uuid.UUID, vehicle_id: uuid.UUID
) -> list[Reminder]:
    """Every managed reminder linked to this vehicle — used by the Driveway
    vehicle Reminders list. Never fetches every Home reminder and filters
    client-side; this is its own indexed query
    (ix_reminder_source_type_id)."""
    return list(
        (
            await db.scalars(
                select(Reminder)
                .where(
                    Reminder.group_id == group_id,
                    Reminder.source_type == DRIVEWAY_SOURCE_TYPE,
                    Reminder.source_id == vehicle_id,
                )
                .order_by(Reminder.due_date, Reminder.due_time)
            )
        ).all()
    )


async def sync_reminder_scope_to_vehicle(db: AsyncSession, vehicle: Vehicle) -> None:
    """Called after a vehicle's own scope changes (routers.driveway.
    update_vehicle) — every linked managed reminder follows the vehicle's
    new scope, per the Phase 4 spec. Standalone reminders are never
    touched; the source_type filter is what keeps this scoped to Driveway-
    managed rows only."""
    rows = (
        await db.scalars(
            select(Reminder).where(
                Reminder.group_id == vehicle.group_id,
                Reminder.source_type == DRIVEWAY_SOURCE_TYPE,
                Reminder.source_id == vehicle.id,
            )
        )
    ).all()
    for reminder in rows:
        reminder.scope = vehicle.scope
        reminder.owner_user_id = _reminder_owner(vehicle)


async def delete_reminders_for_vehicle(
    db: AsyncSession, group_id: uuid.UUID, vehicle_id: uuid.UUID
) -> None:
    """Hard-deletes every managed reminder linked to a vehicle being
    deleted, in the same transaction as the vehicle delete — Reminder has
    no soft-delete concept of its own (see routers.reminders.delete_reminder,
    the same hard-delete every standalone reminder uses), so a Driveway-
    managed reminder must not be left pointing at a vehicle that no longer
    exists. ReminderMember/ReminderCompletion rows cascade automatically
    (ondelete=CASCADE on reminder_id)."""
    await db.execute(
        delete(Reminder).where(
            Reminder.group_id == group_id,
            Reminder.source_type == DRIVEWAY_SOURCE_TYPE,
            Reminder.source_id == vehicle_id,
        )
    )
