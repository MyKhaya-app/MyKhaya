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
from dataclasses import dataclass
from datetime import date, time
from enum import StrEnum

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.driveway_sensitive import (
    DrivewayFieldEncryptionUnavailable,
    DrivewaySensitiveReadError,
    get_vehicle_registration,
)
from mykhaya.models import (
    Reminder,
    ReminderCadence,
    ReminderRepeat,
    RoutineScope,
    TodoCategory,
    Vehicle,
)

# The only source_type Phase 4 writes. Kept as a plain constant (not a
# Postgres enum) because source_type is polymorphic — a future module could
# add its own value without an ALTER TYPE migration touching Driveway's.
DRIVEWAY_SOURCE_TYPE = "driveway"


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


# Source events of the MOT nudge plan's per-lead-day reminders
# ("inspection_lead_30" etc.) — see mykhaya.driveway_mot_nudges.
LEAD_EVENT_PREFIX = "inspection_lead_"


def lead_days_of(reminder: Reminder) -> int | None:
    """Days before the MOT for a reminder that belongs to an MOT nudge plan."""
    event = reminder.source_event or ""
    if reminder.source_type != DRIVEWAY_SOURCE_TYPE or not event.startswith(LEAD_EVENT_PREFIX):
        return None
    try:
        return int(event[len(LEAD_EVENT_PREFIX) :])
    except ValueError:
        return None


@dataclass(frozen=True)
class ReminderVehicleLink:
    vehicle_id: uuid.UUID
    nickname: str
    make: str | None
    model: str | None
    registration: str | None
    mot_plan_lead_days: int | None


async def vehicle_link(
    db: AsyncSession, reminder: Reminder, settings: Settings
) -> ReminderVehicleLink | None:
    """The vehicle a Driveway-sourced reminder belongs to, for the Nudges card.
    Only ever called for a reminder the viewer can already see (Driveway
    reminders are personal to the vehicle owner). The registration is read
    through the sensitive-field path; if it can't be read it is omitted."""
    if reminder.source_type != DRIVEWAY_SOURCE_TYPE or reminder.source_id is None:
        return None
    vehicle = await db.get(Vehicle, reminder.source_id)
    if vehicle is None or vehicle.group_id != reminder.group_id:
        return None
    try:
        registration = get_vehicle_registration(vehicle, settings)
    except (DrivewaySensitiveReadError, DrivewayFieldEncryptionUnavailable):
        registration = None
    return ReminderVehicleLink(
        vehicle_id=vehicle.id,
        nickname=vehicle.nickname,
        make=vehicle.make,
        model=vehicle.model,
        registration=registration,
        mot_plan_lead_days=lead_days_of(reminder),
    )


# The fixed system category every Driveway-sourced reminder belongs to. It is
# identified by TodoCategory.managed_source == "driveway", never by its label;
# routers.todos refuses to rename or delete it.
DRIVEWAY_CATEGORY_NAME = "Driveway"


async def ensure_driveway_category(
    db: AsyncSession, group_id: uuid.UUID, created_by: uuid.UUID
) -> TodoCategory:
    """Idempotent get-or-create of the Home's system "Driveway" category.

    Order: the existing managed category; else a user category already named
    "Driveway" (any case) is adopted as the system one, so the Home never ends
    up with two; else a new one is inserted. Safe under concurrent first
    calls via ON CONFLICT DO NOTHING on (group_id, name)."""
    managed = await db.scalar(
        select(TodoCategory).where(
            TodoCategory.group_id == group_id,
            TodoCategory.managed_source == DRIVEWAY_SOURCE_TYPE,
        )
    )
    if managed is not None:
        return managed
    await db.execute(
        pg_insert(TodoCategory)
        .values(
            group_id=group_id,
            name=DRIVEWAY_CATEGORY_NAME,
            created_by=created_by,
            managed_source=DRIVEWAY_SOURCE_TYPE,
        )
        .on_conflict_do_nothing(constraint="uq_todo_category_home_name")
    )
    category = await db.scalar(
        select(TodoCategory).where(
            TodoCategory.group_id == group_id,
            TodoCategory.name.ilike(DRIVEWAY_CATEGORY_NAME),
        )
    )
    assert category is not None  # inserted, the race winner's, or the user's own
    category.managed_source = DRIVEWAY_SOURCE_TYPE
    return category


def _reminder_owner(vehicle: Vehicle) -> uuid.UUID | None:
    # Driveway ownership is explicit on Vehicle. Reminder.scope remains a
    # Reminder-domain visibility field, not a vehicle ownership selector.
    return vehicle.owner_user_id


async def upsert_driveway_reminder(
    db: AsyncSession,
    *,
    group_id: uuid.UUID,
    vehicle: Vehicle,
    event_type: DrivewayReminderEventType | str,
    due_date: date,
    title: str,
    due_time: time = time(9, 0),
    description: str | None = None,
    repeat: ReminderRepeat = ReminderRepeat.never,
    cadence: ReminderCadence = ReminderCadence.once,
    created_by: uuid.UUID,
) -> tuple[Reminder, bool]:
    """Ensures the Driveway category exists, then creates or updates the
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
    source data changes without ever creating duplicates. A plain string
    event is accepted for structured sub-events that need their own key,
    such as the MOT nudge plan's per-lead-day reminders
    (mykhaya.driveway_mot_nudges); it follows the same upsert rules.

    Reminder visibility/owner are derived from the vehicle owner, never client-supplied
    — see sync_reminder_scope_to_vehicle for what happens when a vehicle's
    own scope later changes.
    """
    category = await ensure_driveway_category(db, group_id, created_by)
    source_event = (
        event_type.value if isinstance(event_type, DrivewayReminderEventType) else event_type
    )

    if source_event != DrivewayReminderEventType.manual.value:
        existing = await db.scalar(
            select(Reminder)
            .where(
                Reminder.group_id == group_id,
                Reminder.source_type == DRIVEWAY_SOURCE_TYPE,
                Reminder.source_id == vehicle.id,
                Reminder.source_event == source_event,
                Reminder.enabled.is_(True),
            )
            .with_for_update()
        )
        if existing is not None:
            existing.title = title
            existing.description = description
            existing.due_date = due_date
            existing.due_time = due_time
            existing.scope = RoutineScope.personal
            existing.owner_user_id = _reminder_owner(vehicle)
            existing.category_id = category.id
            await db.flush()
            return existing, False

    reminder = Reminder(
        group_id=group_id,
        title=title,
        description=description,
        category_id=category.id,
        scope=RoutineScope.personal,
        owner_user_id=_reminder_owner(vehicle),
        due_date=due_date,
        due_time=due_time,
        repeat=repeat,
        cadence=cadence,
        created_by=created_by,
        source_type=DRIVEWAY_SOURCE_TYPE,
        source_id=vehicle.id,
        source_event=source_event,
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
        reminder.scope = RoutineScope.personal
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
