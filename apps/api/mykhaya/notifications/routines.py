"""Household routine reminders (bins, medication, and similar recurring chores): a
durable due-reminder scan plus worker-side delivery that re-validates against current
data, mirroring mykhaya.notifications.reminders. See
mykhaya.notifications.routine_occurrences for the interval_weeks/week_anchor_date
occurrence math.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.models import (
    Group,
    HouseholdRoutine,
    HouseholdRoutineMember,
    Membership,
    OutboxEvent,
    RoutineReminderTiming,
    RoutineScope,
)
from mykhaya.notifications.deep_links import target
from mykhaya.notifications.engine import notify
from mykhaya.notifications.nudges import (
    is_covered_by_daily_nudge_summary,
    is_nudges_notification_eligible,
)
from mykhaya.notifications.quiet_hours import home_timezone
from mykhaya.notifications.routine_occurrences import is_occurrence_date
from mykhaya.notifications.templates import render_notification
from mykhaya.notifications.visibility import active_membership

log = structlog.get_logger()

LOOKAHEAD = timedelta(minutes=2)
ROUTINE_TOPIC = "notification.household_routine"

# Fixed local send times — routines have no per-instance time field, only a
# before/same-day/both preference (mykhaya.models.RoutineReminderTiming).
EVENING_BEFORE_TIME = time(18, 0)
SAME_DAY_TIME = time(7, 30)

TimingSlot = tuple[str, time]
_ALL_SLOTS: dict[str, TimingSlot] = {
    "evening_before": ("evening_before", EVENING_BEFORE_TIME),
    "same_day": ("same_day", SAME_DAY_TIME),
}


def _slots_for(reminder_timing: RoutineReminderTiming) -> list[TimingSlot]:
    if reminder_timing == RoutineReminderTiming.both:
        return [_ALL_SLOTS["evening_before"], _ALL_SLOTS["same_day"]]
    return [_ALL_SLOTS[reminder_timing.value]]


async def scan_due_routines(db: AsyncSession, settings: Settings) -> None:
    now_utc = datetime.now(UTC)
    window_end_utc = now_utc + LOOKAHEAD

    routines = (
        await db.scalars(
            select(HouseholdRoutine)
            .join(Group, Group.id == HouseholdRoutine.group_id)
            .where(HouseholdRoutine.enabled.is_(True), Group.is_active.is_(True))
        )
    ).all()
    for routine in routines:
        # Phase 3A: household routine reminders are a Nudges-owned scheduled
        # notification — see is_nudges_notification_eligible. A Home whose
        # Nudges module/entitlement (not just Notifications) is currently
        # blocked never even gets an OutboxEvent enqueued; the routine data
        # itself is untouched either way.
        if not await is_nudges_notification_eligible(db, routine.group_id):
            continue
        tz = await home_timezone(db, routine.group_id, settings.default_timezone)
        now_local = now_utc.astimezone(tz)
        today_local = now_local.date()
        window_end_local = window_end_utc.astimezone(tz)

        for timing, send_time in _slots_for(routine.reminder_timing):
            occurrence_date = (
                today_local + timedelta(days=1) if timing == "evening_before" else today_local
            )
            if not is_occurrence_date(routine, occurrence_date):
                continue
            scheduled_local = datetime.combine(today_local, send_time, tzinfo=tz)
            if not (scheduled_local <= now_local < window_end_local):
                continue
            key = (str(routine.id), occurrence_date.isoformat(), timing)
            await db.execute(
                pg_insert(OutboxEvent)
                .values(
                    topic=ROUTINE_TOPIC,
                    payload={
                        "routine_id": key[0],
                        "occurrence_date": key[1],
                        "timing": key[2],
                    },
                    dedupe_key=f"routine:{key[0]}:{key[1]}:{key[2]}",
                )
                .on_conflict_do_nothing(index_elements=["dedupe_key"])
            )
    await db.commit()


async def _recipients_for(db: AsyncSession, routine: HouseholdRoutine) -> set[uuid.UUID]:
    if routine.scope == RoutineScope.personal:
        # A personal routine's only recipient is its owner — never derived from
        # group_id/household membership, and HouseholdRoutineMember rows (a
        # household-routine concept) are never consulted here even if present.
        return {routine.owner_user_id} if routine.owner_user_id else set()
    explicit = (
        await db.scalars(
            select(HouseholdRoutineMember.user_id).where(
                HouseholdRoutineMember.routine_id == routine.id
            )
        )
    ).all()
    if explicit:
        return set(explicit)
    household_wide = (
        await db.scalars(
            select(Membership.user_id).where(
                Membership.group_id == routine.group_id, Membership.removed_at.is_(None)
            )
        )
    ).all()
    return set(household_wide)


async def deliver_routine_reminder(
    db: AsyncSession,
    settings: Settings,
    routine_id: str,
    occurrence_date_iso: str,
    timing: str,
) -> None:
    routine = await db.get(HouseholdRoutine, uuid.UUID(routine_id))
    if routine is None or not routine.enabled:
        return  # disabled or deleted since it was scanned
    # Re-validate fresh, same reasoning as the occurrence/timing checks
    # below: Nudges could have been disabled or lost its entitlement in the
    # gap between scan and this worker actually running.
    if not await is_nudges_notification_eligible(db, routine.group_id):
        return

    occurrence_date = date.fromisoformat(occurrence_date_iso)
    # Re-validate fresh: an edit to the schedule or reminder_timing since this was
    # scanned may mean this occurrence/slot is no longer valid — skip rather than
    # deliver stale content.
    if not is_occurrence_date(routine, occurrence_date):
        return
    if timing not in {slot for slot, _time in _slots_for(routine.reminder_timing)}:
        return

    idempotency_key = f"routine:{routine_id}:{occurrence_date_iso}:{timing}"
    if routine.description:
        # A routine's own description is user-authored content, not app
        # wording — used verbatim, never passed through the template
        # registry (there is nothing generic to customise here).
        body = routine.description
    else:
        _subject, body = await render_notification(
            db, "routine.due", {"routine_title": routine.title}
        )

    # Dedup against Daily Nudge Summary: only a "same_day" send can ever be
    # covered by a summary (which only ever covers *today*) — "evening_before"
    # is about *tomorrow's* occurrence and can never collide. Only computed
    # once per routine, not per recipient, since it depends only on the
    # routine's own fixed send time.
    item_scheduled_utc: datetime | None = None
    if timing == "same_day":
        home_tz = await home_timezone(db, routine.group_id, settings.default_timezone)
        item_scheduled_utc = datetime.combine(
            occurrence_date, SAME_DAY_TIME, tzinfo=home_tz
        ).astimezone(UTC)

    for recipient_id in await _recipients_for(db, routine):
        if await active_membership(db, routine.group_id, recipient_id) is None:
            continue  # membership removed since this reminder was scanned
        if item_scheduled_utc is not None and await is_covered_by_daily_nudge_summary(
            db,
            settings,
            recipient_id=recipient_id,
            item_scheduled_utc=item_scheduled_utc,
            kind="routine",
            item_id=routine.id,
        ):
            await log.ainfo(
                "household_routine_reminder_suppressed_by_daily_nudge_summary",
                routine_id=routine_id,
                recipient_id=str(recipient_id),
                occurrence_date=occurrence_date_iso,
            )
            continue
        await notify(
            db,
            settings=settings,
            recipient_user_id=recipient_id,
            notification_type="household_routine_reminder",
            title=routine.title,
            body=body,
            idempotency_key=f"{idempotency_key}:{recipient_id}",
            group_id=routine.group_id,
            related_entity_type="household_routine",
            related_entity_id=routine.id,
            deep_link=target("routine", routine.id),
            is_critical=routine.is_critical,
        )
