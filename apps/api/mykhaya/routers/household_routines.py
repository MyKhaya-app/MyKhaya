from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context
from mykhaya.features import require_feature
from mykhaya.household_permissions import Capability, require_capability
from mykhaya.models import (
    FeatureKey,
    HouseholdRoutine,
    HouseholdRoutineCompletion,
    HouseholdRoutineMember,
    Membership,
)
from mykhaya.notifications.routine_occurrences import is_occurrence_date, next_occurrence_date
from mykhaya.notifications.visibility import active_membership
from mykhaya.schemas import (
    RoutineCompletionRequest,
    RoutineCreate,
    RoutineListResponse,
    RoutineResponse,
    RoutineUpdate,
)


async def require_notifications_feature(
    home_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_feature(db, FeatureKey.notifications, home_id)


router = APIRouter(
    prefix="/homes",
    tags=["household-routines"],
    dependencies=[Depends(require_notifications_feature)],
)


async def _require_member(
    home_id: uuid.UUID, auth: AuthContext, db: AsyncSession
) -> Membership:
    membership = await active_membership(db, home_id, auth.user.id)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return membership


async def _member_ids(db: AsyncSession, routine_id: uuid.UUID) -> list[uuid.UUID]:
    rows = (
        await db.scalars(
            select(HouseholdRoutineMember.user_id).where(
                HouseholdRoutineMember.routine_id == routine_id
            )
        )
    ).all()
    return sorted(rows)


async def _to_response(db: AsyncSession, routine: HouseholdRoutine) -> RoutineResponse:
    today = datetime.now(UTC).date()
    completed = await db.scalar(
        select(HouseholdRoutineCompletion.id).where(
            HouseholdRoutineCompletion.routine_id == routine.id,
            HouseholdRoutineCompletion.occurrence_date == today,
        )
    )
    return RoutineResponse(
        id=routine.id,
        title=routine.title,
        description=routine.description,
        interval_weeks=routine.interval_weeks,
        week_anchor_date=routine.week_anchor_date,
        reminder_timing=routine.reminder_timing,
        is_critical=routine.is_critical,
        pinned=routine.pinned,
        enabled=routine.enabled,
        start_date=routine.start_date,
        end_date=routine.end_date,
        member_ids=await _member_ids(db, routine.id),
        next_occurrence_date=next_occurrence_date(routine, today),
        completed_today=completed is not None and is_occurrence_date(routine, today),
        created_by=routine.created_by,
        updated_at=routine.updated_at,
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


@router.get("/{home_id}/routines", response_model=RoutineListResponse)
async def list_routines(
    home_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> RoutineListResponse:
    await _require_member(home_id, auth, db)
    routines = (
        await db.scalars(
            select(HouseholdRoutine)
            .where(HouseholdRoutine.group_id == home_id)
            .order_by(HouseholdRoutine.created_at)
            .limit(200)
        )
    ).all()
    return RoutineListResponse(items=[await _to_response(db, routine) for routine in routines])


@router.post("/{home_id}/routines", response_model=RoutineResponse, status_code=201)
async def create_routine(
    home_id: uuid.UUID,
    body: RoutineCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> RoutineResponse:
    await require_capability(home_id, Capability.household_manage_routines, auth, db)
    if body.end_date is not None and body.end_date < body.start_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "End must be on or after start")
    member_ids = await _validate_members(db, home_id, body.member_ids)

    routine = HouseholdRoutine(
        group_id=home_id,
        title=" ".join(body.title.strip().split()),
        description=body.description,
        interval_weeks=body.interval_weeks,
        week_anchor_date=body.week_anchor_date,
        reminder_timing=body.reminder_timing,
        is_critical=body.is_critical,
        pinned=body.pinned,
        start_date=body.start_date,
        end_date=body.end_date,
        created_by=auth.user.id,
    )
    db.add(routine)
    await db.flush()
    for user_id in member_ids:
        db.add(HouseholdRoutineMember(routine_id=routine.id, user_id=user_id))

    audit(db, request, "household_routine.created", auth.user.id, home_id, "routine", routine.id)
    await db.commit()
    return await _to_response(db, routine)


@router.patch("/{home_id}/routines/{routine_id}", response_model=RoutineResponse)
async def update_routine(
    home_id: uuid.UUID,
    routine_id: uuid.UUID,
    body: RoutineUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> RoutineResponse:
    await require_capability(home_id, Capability.household_manage_routines, auth, db)
    if body.end_date is not None and body.end_date < body.start_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "End must be on or after start")

    routine = await db.scalar(
        select(HouseholdRoutine)
        .where(HouseholdRoutine.id == routine_id, HouseholdRoutine.group_id == home_id)
        .with_for_update()
    )
    if routine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That routine could not be found")
    if routine.updated_at != body.expected_updated_at:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This routine changed. Reload and try again."
        )

    member_ids = await _validate_members(db, home_id, body.member_ids)
    await db.execute(
        delete(HouseholdRoutineMember).where(HouseholdRoutineMember.routine_id == routine.id)
    )
    for user_id in member_ids:
        db.add(HouseholdRoutineMember(routine_id=routine.id, user_id=user_id))

    routine.title = " ".join(body.title.strip().split())
    routine.description = body.description
    routine.interval_weeks = body.interval_weeks
    routine.week_anchor_date = body.week_anchor_date
    routine.reminder_timing = body.reminder_timing
    routine.is_critical = body.is_critical
    routine.pinned = body.pinned
    routine.enabled = body.enabled
    routine.start_date = body.start_date
    routine.end_date = body.end_date

    audit(db, request, "household_routine.updated", auth.user.id, home_id, "routine", routine.id)
    await db.commit()
    await db.refresh(routine)
    return await _to_response(db, routine)


@router.delete("/{home_id}/routines/{routine_id}", status_code=204)
async def delete_routine(
    home_id: uuid.UUID,
    routine_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_capability(home_id, Capability.household_manage_routines, auth, db)
    routine = await db.scalar(
        select(HouseholdRoutine).where(
            HouseholdRoutine.id == routine_id, HouseholdRoutine.group_id == home_id
        )
    )
    if routine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That routine could not be found")
    audit(db, request, "household_routine.deleted", auth.user.id, home_id, "routine", routine.id)
    await db.delete(routine)
    await db.commit()


@router.post("/{home_id}/routines/{routine_id}/complete", response_model=RoutineResponse)
async def complete_routine(
    home_id: uuid.UUID,
    routine_id: uuid.UUID,
    body: RoutineCompletionRequest,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> RoutineResponse:
    await _require_member(home_id, auth, db)
    routine = await db.scalar(
        select(HouseholdRoutine).where(
            HouseholdRoutine.id == routine_id, HouseholdRoutine.group_id == home_id
        )
    )
    if routine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That routine could not be found")
    if not is_occurrence_date(routine, body.occurrence_date):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "That date is not a scheduled occurrence"
        )

    existing = await db.scalar(
        select(HouseholdRoutineCompletion).where(
            HouseholdRoutineCompletion.routine_id == routine.id,
            HouseholdRoutineCompletion.occurrence_date == body.occurrence_date,
        )
    )
    if existing is None:
        db.add(
            HouseholdRoutineCompletion(
                routine_id=routine.id,
                occurrence_date=body.occurrence_date,
                completed_by=auth.user.id,
            )
        )
    await db.commit()
    return await _to_response(db, routine)


@router.delete(
    "/{home_id}/routines/{routine_id}/complete/{occurrence_date}", status_code=204
)
async def uncomplete_routine(
    home_id: uuid.UUID,
    routine_id: uuid.UUID,
    occurrence_date: str,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require_member(home_id, auth, db)
    routine = await db.scalar(
        select(HouseholdRoutine).where(
            HouseholdRoutine.id == routine_id, HouseholdRoutine.group_id == home_id
        )
    )
    if routine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That routine could not be found")
    parsed_date = date.fromisoformat(occurrence_date)
    completion = await db.scalar(
        select(HouseholdRoutineCompletion).where(
            HouseholdRoutineCompletion.routine_id == routine.id,
            HouseholdRoutineCompletion.occurrence_date == parsed_date,
        )
    )
    if completion is not None:
        await db.delete(completion)
        await db.commit()
