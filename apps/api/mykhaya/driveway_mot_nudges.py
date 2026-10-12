"""Driveway MOT nudges: the owner's plan for being reminded before an MOT.

A plan is stored on the vehicle (``Vehicle.mot_nudge_plan``) and turned into
ordinary Driveway-linked ``Reminder`` rows — one per chosen lead day — through
the shared ``upsert_driveway_reminder`` helper, so they appear in Nudges like
any other reminder and follow every existing Driveway reminder rule:

- recipients: always the vehicle owner (personal scope), never client-chosen.
  A vehicle's reminders are as private as the vehicle's sensitive fields;
- each lead day has its own source event (``inspection_lead_<days>``), so a
  re-save or a re-date updates the same rows instead of duplicating them;
- a plan replaces the single automatic "MOT due" reminder
  (``source_event=inspection``) while it exists;
- after a refresh moves the MOT expiry (the next pass), a repeating plan is
  re-dated to the new expiry; a one-off plan is used up, and the automatic
  "MOT due" reminder applies again.

Lead days that would fall before today are skipped rather than creating an
already-overdue reminder.

Deleting from Nudges keeps the plan honest, so an MOT refresh never brings a
deleted nudge back:
- deleting one plan nudge drops that lead day from the plan
  (``drop_lead_day``, called by the generic reminder delete);
- removing the plan deletes every MOT reminder for the vehicle and stores
  ``{"off": true}`` (``remove_plan``): the owner has said no MOT nudges, so
  the automatic "MOT due" reminder is not recreated either, until a new plan
  is saved.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.driveway_reminders import (
    DRIVEWAY_SOURCE_TYPE,
    LEAD_EVENT_PREFIX,
    DrivewayReminderEventType,
    upsert_driveway_reminder,
)
from mykhaya.models import Reminder, Vehicle

# The lead days the UI offers: 30, 14 and 7 days before, and on the day.
NUDGE_OFFSETS: tuple[int, ...] = (30, 14, 7, 0)


def lead_event(offset: int) -> str:
    return f"{LEAD_EVENT_PREFIX}{offset}"


@dataclass(frozen=True)
class MotNudgePlan:
    title: str
    offsets: tuple[int, ...]
    repeat: bool
    due_date: date

    def as_json(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "offsets": list(self.offsets),
            "repeat": self.repeat,
            "due_date": self.due_date.isoformat(),
        }

    def scheduled_dates(self, today: date) -> list[date]:
        """The reminder dates this plan actually creates, earliest first."""
        dates = {self.due_date - timedelta(days=offset) for offset in self.offsets}
        return sorted(day for day in dates if day >= today)


OFF_MARKER: dict[str, Any] = {"off": True}


def plan_is_off(vehicle: Vehicle) -> bool:
    raw = vehicle.mot_nudge_plan
    return isinstance(raw, dict) and raw.get("off") is True


def read_plan(vehicle: Vehicle) -> MotNudgePlan | None:
    raw = vehicle.mot_nudge_plan
    if not isinstance(raw, dict) or raw.get("off") is True:
        return None
    try:
        offsets = tuple(
            sorted(
                {int(o) for o in raw.get("offsets", []) if int(o) in NUDGE_OFFSETS},
                reverse=True,
            )
        )
        plan = MotNudgePlan(
            title=str(raw["title"]),
            offsets=offsets,
            repeat=bool(raw.get("repeat", False)),
            due_date=date.fromisoformat(str(raw["due_date"])),
        )
    except (KeyError, TypeError, ValueError):
        return None
    return plan if plan.offsets and plan.title else None


def _description(plan: MotNudgePlan) -> str:
    return f"MOT expires {plan.due_date.day} {plan.due_date:%b %Y}."


async def _delete_events(db: AsyncSession, vehicle: Vehicle, events: list[str]) -> None:
    if not events:
        return
    await db.execute(
        delete(Reminder).where(
            Reminder.group_id == vehicle.group_id,
            Reminder.source_type == DRIVEWAY_SOURCE_TYPE,
            Reminder.source_id == vehicle.id,
            Reminder.source_event.in_(events),
        )
    )


async def apply_plan(
    db: AsyncSession,
    vehicle: Vehicle,
    plan: MotNudgePlan,
    *,
    actor_id: uuid.UUID,
    today: date,
) -> list[date]:
    """Stores the plan and brings the vehicle's MOT reminders in line with
    it. Returns the reminder dates that now exist."""
    vehicle.mot_nudge_plan = plan.as_json()
    # The plan replaces the automatic "MOT due" reminder, and any lead day
    # no longer chosen (or already in the past) is removed.
    keep = {offset for offset in plan.offsets if plan.due_date - timedelta(days=offset) >= today}
    await _delete_events(
        db,
        vehicle,
        [DrivewayReminderEventType.inspection.value]
        + [lead_event(offset) for offset in NUDGE_OFFSETS if offset not in keep],
    )
    for offset in sorted(keep, reverse=True):
        await upsert_driveway_reminder(
            db,
            group_id=vehicle.group_id,
            vehicle=vehicle,
            event_type=lead_event(offset),
            due_date=plan.due_date - timedelta(days=offset),
            title=plan.title,
            description=_description(plan),
            created_by=actor_id,
        )
    return plan.scheduled_dates(today)


async def sync_after_refresh(
    db: AsyncSession,
    vehicle: Vehicle,
    new_due_date: date | None,
    *,
    actor_id: uuid.UUID,
    today: date,
) -> bool:
    """Called by the MOT refresh with the vehicle's new MOT due date.
    Returns True when a plan is handling this vehicle's MOT reminders (so
    the automatic "MOT due" reminder must not be recreated)."""
    if plan_is_off(vehicle):
        return True
    plan = read_plan(vehicle)
    if plan is None:
        return False
    if new_due_date is None or new_due_date == plan.due_date:
        return True
    if new_due_date < plan.due_date:
        # An earlier date is a correction of the same MOT, not a new pass:
        # follow it whether or not the plan repeats.
        await apply_plan(
            db, vehicle, _with_date(plan, new_due_date), actor_id=actor_id, today=today
        )
        return True
    if plan.repeat:
        await apply_plan(
            db, vehicle, _with_date(plan, new_due_date), actor_id=actor_id, today=today
        )
        return True
    # A one-off plan is used up by the next pass. Its reminders stay as they
    # were (they belong to the MOT just passed); the automatic reminder
    # resumes for the new date.
    vehicle.mot_nudge_plan = None
    return False


def _with_date(plan: MotNudgePlan, due_date: date) -> MotNudgePlan:
    return MotNudgePlan(
        title=plan.title, offsets=plan.offsets, repeat=plan.repeat, due_date=due_date
    )


async def drop_lead_day(db: AsyncSession, vehicle: Vehicle, offset: int) -> None:
    """A single plan nudge was deleted: remove its lead day from the plan so
    a refresh never recreates it. Removing the last day turns MOT nudges
    off for the vehicle (see remove_plan)."""
    plan = read_plan(vehicle)
    if plan is None or offset not in plan.offsets:
        return
    remaining = tuple(day for day in plan.offsets if day != offset)
    if not remaining:
        await remove_plan(db, vehicle)
        return
    vehicle.mot_nudge_plan = MotNudgePlan(
        title=plan.title, offsets=remaining, repeat=plan.repeat, due_date=plan.due_date
    ).as_json()


async def remove_plan(db: AsyncSession, vehicle: Vehicle) -> None:
    """Deletes every MOT reminder for the vehicle (the plan's lead days and
    the automatic one) and records that MOT nudges are off."""
    await _delete_events(
        db,
        vehicle,
        [DrivewayReminderEventType.inspection.value]
        + [lead_event(offset) for offset in NUDGE_OFFSETS],
    )
    vehicle.mot_nudge_plan = dict(OFF_MARKER)
