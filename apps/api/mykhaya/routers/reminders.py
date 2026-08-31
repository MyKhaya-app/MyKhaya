from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from functools import partial

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context
from mykhaya.features import require_feature
from mykhaya.household_permissions import Capability, require_capability
from mykhaya.models import (
    FeatureKey,
    Membership,
    Reminder,
    ReminderCompletion,
    ReminderMember,
    RoutineScope,
    User,
)
from mykhaya.notifications.quiet_hours import home_timezone
from mykhaya.notifications.reminder_occurrences import (
    HOME_LOOKBACK_DAYS,
    is_occurrence_date,
    next_occurrence_date,
    select_home_occurrence,
)
from mykhaya.notifications.visibility import active_membership
from mykhaya.schemas import (
    ReminderCompletionRequest,
    ReminderCreate,
    ReminderListResponse,
    ReminderResponse,
    ReminderUpdate,
)


async def require_notifications_feature(
    home_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_feature(db, FeatureKey.notifications, home_id)


router = APIRouter(
    prefix="/homes",
    tags=["reminders"],
    dependencies=[Depends(require_notifications_feature)],
)


async def _require_member(home_id: uuid.UUID, auth: AuthContext, db: AsyncSession) -> Membership:
    membership = await active_membership(db, home_id, auth.user.id)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return membership


async def _member_ids(db: AsyncSession, reminder_id: uuid.UUID) -> list[uuid.UUID]:
    rows = (
        await db.scalars(
            select(ReminderMember.user_id).where(ReminderMember.reminder_id == reminder_id)
        )
    ).all()
    return sorted(rows)


def _is_visible(reminder: Reminder, user_id: uuid.UUID) -> bool:
    # A personal reminder is private to its owner — not shown to, editable by, or
    # completable by any other household member.
    if reminder.scope == RoutineScope.personal:
        return reminder.owner_user_id == user_id
    return True


async def _to_response(
    db: AsyncSession,
    reminder: Reminder,
    *,
    home_occurrence_date: date | None = None,
    home_completion: ReminderCompletion | None = None,
    home_completed_by_display_name: str | None = None,
) -> ReminderResponse:
    today = datetime.now(UTC).date()
    completed = await db.scalar(
        select(ReminderCompletion.id).where(
            ReminderCompletion.reminder_id == reminder.id,
            ReminderCompletion.occurrence_date == today,
        )
    )
    return ReminderResponse(
        id=reminder.id,
        title=reminder.title,
        description=reminder.description,
        scope=reminder.scope,
        owner_user_id=reminder.owner_user_id,
        due_date=reminder.due_date,
        due_time=reminder.due_time,
        repeat=reminder.repeat,
        cadence=reminder.cadence,
        enabled=reminder.enabled,
        member_ids=await _member_ids(db, reminder.id),
        next_occurrence_date=next_occurrence_date(reminder, today),
        completed_today=completed is not None and is_occurrence_date(reminder, today),
        home_occurrence_date=home_occurrence_date,
        home_completed_at=home_completion.completed_at if home_completion else None,
        home_completed_by_user_id=home_completion.completed_by if home_completion else None,
        home_completed_by_display_name=home_completed_by_display_name,
        created_by=reminder.created_by,
        updated_at=reminder.updated_at,
    )


async def _validate_members(
    db: AsyncSession, home_id: uuid.UUID, member_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    requested = sorted(set(member_ids))
    if not requested:
        return requested
    rows = (
        await db.scalars(
            select(Membership.user_id).where(
                Membership.group_id == home_id,
                Membership.removed_at.is_(None),
                Membership.user_id.in_(requested),
            )
        )
    ).all()
    if set(rows) != set(requested):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A selected member is invalid")
    return requested


@router.get("/{home_id}/reminders", response_model=ReminderListResponse)
async def list_reminders(
    home_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    home: bool = Query(default=False),
    settings: Settings = Depends(get_settings),
) -> ReminderListResponse:
    await _require_member(home_id, auth, db)
    reminders = (
        await db.scalars(
            select(Reminder)
            .where(
                Reminder.group_id == home_id,
                (Reminder.scope == RoutineScope.household)
                | (Reminder.owner_user_id == auth.user.id),
            )
            .order_by(Reminder.created_at)
            .limit(200)
        )
    ).all()
    if not home:
        return ReminderListResponse(
            items=[await _to_response(db, reminder) for reminder in reminders]
        )

    tz = await home_timezone(db, home_id, settings.default_timezone)
    today = datetime.now(UTC).astimezone(tz).date()

    reminder_ids = [reminder.id for reminder in reminders]
    completions = (
        (
            await db.scalars(
                select(ReminderCompletion).where(
                    ReminderCompletion.reminder_id.in_(reminder_ids),
                    ReminderCompletion.occurrence_date
                    >= today - timedelta(days=HOME_LOOKBACK_DAYS),
                    ReminderCompletion.occurrence_date <= today,
                )
            )
        ).all()
        if reminder_ids
        else []
    )
    completion_by_key = {(row.reminder_id, row.occurrence_date): row for row in completions}
    completed_by_ids = {row.completed_by for row in completions if row.completed_by}
    completed_by_users = (
        {
            user.id: user.display_name
            for user in (await db.scalars(select(User).where(User.id.in_(completed_by_ids)))).all()
        }
        if completed_by_ids
        else {}
    )

    def _is_completed(reminder_id: uuid.UUID, occurrence_date: date) -> bool:
        return (reminder_id, occurrence_date) in completion_by_key

    selected: list[tuple[int, date, Reminder, ReminderCompletion | None]] = []
    for reminder in reminders:
        selection = select_home_occurrence(reminder, today, partial(_is_completed, reminder.id))
        if selection is None:
            continue
        completion = (
            completion_by_key.get((reminder.id, selection.occurrence_date))
            if selection.is_completed
            else None
        )
        selected.append((selection.priority, selection.occurrence_date, reminder, completion))
    selected.sort(key=lambda item: (item[0], item[1], item[2].title.casefold(), str(item[2].id)))
    items = [
        await _to_response(
            db,
            reminder,
            home_occurrence_date=occurrence_date,
            home_completion=completion,
            home_completed_by_display_name=(
                completed_by_users.get(completion.completed_by)
                if completion and completion.completed_by
                else None
            ),
        )
        for _priority, occurrence_date, reminder, completion in selected
    ]
    return ReminderListResponse(items=items)


@router.post("/{home_id}/reminders", response_model=ReminderResponse, status_code=201)
async def create_reminder(
    home_id: uuid.UUID,
    body: ReminderCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ReminderResponse:
    await require_capability(home_id, Capability.household_manage_reminders, auth, db)
    member_ids = await _validate_members(db, home_id, body.member_ids)

    # owner_user_id is never accepted from client input (ReminderCreate has no such
    # field) — a personal reminder's owner is always the authenticated actor,
    # matching HouseholdRoutine's identical rule.
    reminder = Reminder(
        group_id=home_id,
        title=" ".join(body.title.strip().split()),
        description=body.description,
        scope=body.scope,
        owner_user_id=auth.user.id if body.scope == RoutineScope.personal else None,
        due_date=body.due_date,
        due_time=body.due_time,
        repeat=body.repeat,
        cadence=body.cadence,
        created_by=auth.user.id,
    )
    db.add(reminder)
    await db.flush()
    for user_id in member_ids:
        db.add(ReminderMember(reminder_id=reminder.id, user_id=user_id))

    audit(db, request, "reminder.created", auth.user.id, home_id, "reminder", reminder.id)
    await db.commit()
    return await _to_response(db, reminder)


@router.patch("/{home_id}/reminders/{reminder_id}", response_model=ReminderResponse)
async def update_reminder(
    home_id: uuid.UUID,
    reminder_id: uuid.UUID,
    body: ReminderUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ReminderResponse:
    await require_capability(home_id, Capability.household_manage_reminders, auth, db)

    reminder = await db.scalar(
        select(Reminder)
        .where(Reminder.id == reminder_id, Reminder.group_id == home_id)
        .with_for_update()
    )
    if reminder is None or not _is_visible(reminder, auth.user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That reminder could not be found")
    if reminder.updated_at != body.expected_updated_at:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This reminder changed. Reload and try again."
        )

    member_ids = await _validate_members(db, home_id, body.member_ids)
    await db.execute(delete(ReminderMember).where(ReminderMember.reminder_id == reminder.id))
    for user_id in member_ids:
        db.add(ReminderMember(reminder_id=reminder.id, user_id=user_id))

    reminder.title = " ".join(body.title.strip().split())
    reminder.description = body.description
    reminder.scope = body.scope
    # Switching to personal makes the editing actor its owner unless it's already
    # personal (owner stays put — editing isn't a transfer-of-ownership action);
    # switching to household clears it, matching ck_reminder_scope_owner.
    if body.scope == RoutineScope.personal:
        reminder.owner_user_id = reminder.owner_user_id or auth.user.id
    else:
        reminder.owner_user_id = None
    reminder.due_date = body.due_date
    reminder.due_time = body.due_time
    reminder.repeat = body.repeat
    reminder.cadence = body.cadence
    reminder.enabled = body.enabled

    audit(db, request, "reminder.updated", auth.user.id, home_id, "reminder", reminder.id)
    await db.commit()
    await db.refresh(reminder)
    return await _to_response(db, reminder)


@router.delete("/{home_id}/reminders/{reminder_id}", status_code=204)
async def delete_reminder(
    home_id: uuid.UUID,
    reminder_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_capability(home_id, Capability.household_manage_reminders, auth, db)
    reminder = await db.scalar(
        select(Reminder).where(Reminder.id == reminder_id, Reminder.group_id == home_id)
    )
    if reminder is None or not _is_visible(reminder, auth.user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That reminder could not be found")
    audit(db, request, "reminder.deleted", auth.user.id, home_id, "reminder", reminder.id)
    await db.delete(reminder)
    await db.commit()


@router.post("/{home_id}/reminders/{reminder_id}/complete", response_model=ReminderResponse)
async def complete_reminder(
    home_id: uuid.UUID,
    reminder_id: uuid.UUID,
    body: ReminderCompletionRequest,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ReminderResponse:
    await _require_member(home_id, auth, db)
    reminder = await db.scalar(
        select(Reminder).where(Reminder.id == reminder_id, Reminder.group_id == home_id)
    )
    if reminder is None or not _is_visible(reminder, auth.user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That reminder could not be found")
    if not is_occurrence_date(reminder, body.occurrence_date):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "That date is not a scheduled occurrence"
        )

    await db.execute(
        pg_insert(ReminderCompletion)
        .values(
            reminder_id=reminder.id,
            occurrence_date=body.occurrence_date,
            completed_by=auth.user.id,
        )
        .on_conflict_do_nothing(constraint="uq_reminder_occurrence")
    )
    await db.commit()
    return await _to_response(db, reminder)


@router.delete("/{home_id}/reminders/{reminder_id}/complete/{occurrence_date}", status_code=204)
async def uncomplete_reminder(
    home_id: uuid.UUID,
    reminder_id: uuid.UUID,
    occurrence_date: str,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require_member(home_id, auth, db)
    reminder = await db.scalar(
        select(Reminder).where(Reminder.id == reminder_id, Reminder.group_id == home_id)
    )
    if reminder is None or not _is_visible(reminder, auth.user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That reminder could not be found")
    parsed_date = date.fromisoformat(occurrence_date)
    completion = await db.scalar(
        select(ReminderCompletion).where(
            ReminderCompletion.reminder_id == reminder.id,
            ReminderCompletion.occurrence_date == parsed_date,
        )
    )
    if completion is not None:
        await db.delete(completion)
        await db.commit()
