from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from functools import partial

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context
from mykhaya.entitlements import has_entitlement, require_entitlement, require_within_limit
from mykhaya.features import require_feature
from mykhaya.household_permissions import Capability, require_capability
from mykhaya.models import (
    FeatureKey,
    HouseholdRoutine,
    HouseholdRoutineCompletion,
    HouseholdRoutineMember,
    Membership,
    RoutineScope,
    User,
)
from mykhaya.notifications.quiet_hours import home_timezone
from mykhaya.notifications.routine_occurrences import (
    HOME_LOOKBACK_DAYS,
    is_occurrence_date,
    next_occurrence_date,
    select_home_occurrence,
)
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


async def _require_member(home_id: uuid.UUID, auth: AuthContext, db: AsyncSession) -> Membership:
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


def _is_visible(routine: HouseholdRoutine, user_id: uuid.UUID) -> bool:
    # A personal routine is private to its owner — not shown to, editable by, or
    # completable by any other household member, even one with manage_routines.
    if routine.scope == RoutineScope.personal:
        return routine.owner_user_id == user_id
    return True


async def _to_response(
    db: AsyncSession,
    routine: HouseholdRoutine,
    *,
    home_occurrence_date: date | None = None,
    home_completion: HouseholdRoutineCompletion | None = None,
    home_completed_by_display_name: str | None = None,
) -> RoutineResponse:
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
        scope=routine.scope,
        owner_user_id=routine.owner_user_id,
        interval_weeks=routine.interval_weeks,
        repeat_unit=routine.repeat_unit,
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
        home_occurrence_date=home_occurrence_date,
        home_completed_at=home_completion.completed_at if home_completion else None,
        home_completed_by_user_id=home_completion.completed_by if home_completion else None,
        home_completed_by_display_name=home_completed_by_display_name,
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
    home: bool = Query(default=False),
    settings: Settings = Depends(get_settings),
) -> RoutineListResponse:
    await _require_member(home_id, auth, db)
    routines = (
        await db.scalars(
            select(HouseholdRoutine)
            .where(
                HouseholdRoutine.group_id == home_id,
                (HouseholdRoutine.scope == RoutineScope.household)
                | (HouseholdRoutine.owner_user_id == auth.user.id),
            )
            .order_by(HouseholdRoutine.created_at)
            .limit(200)
        )
    ).all()
    if not home:
        return RoutineListResponse(items=[await _to_response(db, routine) for routine in routines])

    # Home may show personal routines to their owner, but household routines
    # remain Family-gated even though the route is otherwise readable.
    household_enabled = await has_entitlement(db, home_id, "routines.household.enabled")
    routines = [
        routine
        for routine in routines
        if routine.scope == RoutineScope.personal or household_enabled
    ]
    tz = await home_timezone(db, home_id, settings.default_timezone)
    today = datetime.now(UTC).astimezone(tz).date()

    # Home's "what needs attention now" view: each routine surfaces at most
    # one occurrence — its current overdue/due-today occurrence if
    # uncompleted, that occurrence still on its due date if just completed,
    # or its next occurrence once that enters its own pre-due visibility
    # window. See routine_occurrences.select_home_occurrence for the exact
    # rules (the recurrence engine — is_occurrence_date/next_occurrence_date
    # — remains the sole source of truth for occurrence dates themselves).
    routine_ids = [routine.id for routine in routines]
    completions = (
        (
            await db.scalars(
                select(HouseholdRoutineCompletion).where(
                    HouseholdRoutineCompletion.routine_id.in_(routine_ids),
                    HouseholdRoutineCompletion.occurrence_date
                    >= today - timedelta(days=HOME_LOOKBACK_DAYS),
                    HouseholdRoutineCompletion.occurrence_date <= today,
                )
            )
        ).all()
        if routine_ids
        else []
    )
    completion_by_key = {(row.routine_id, row.occurrence_date): row for row in completions}
    completed_by_ids = {row.completed_by for row in completions if row.completed_by}
    completed_by_users = (
        {
            user.id: user.display_name
            for user in (await db.scalars(select(User).where(User.id.in_(completed_by_ids)))).all()
        }
        if completed_by_ids
        else {}
    )

    def _is_completed(routine_id: uuid.UUID, occurrence_date: date) -> bool:
        return (routine_id, occurrence_date) in completion_by_key

    selected: list[tuple[int, date, HouseholdRoutine, HouseholdRoutineCompletion | None]] = []
    for routine in routines:
        selection = select_home_occurrence(
            routine,
            today,
            partial(_is_completed, routine.id),
        )
        if selection is None:
            continue
        completion = (
            completion_by_key.get((routine.id, selection.occurrence_date))
            if selection.is_completed
            else None
        )
        selected.append((selection.priority, selection.occurrence_date, routine, completion))
    selected.sort(key=lambda item: (item[0], item[1], item[2].title.casefold(), str(item[2].id)))
    items = [
        await _to_response(
            db,
            routine,
            home_occurrence_date=occurrence_date,
            home_completion=completion,
            home_completed_by_display_name=(
                completed_by_users.get(completion.completed_by)
                if completion and completion.completed_by
                else None
            ),
        )
        for _priority, occurrence_date, routine, completion in selected
    ]
    return RoutineListResponse(items=items)


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

    if body.scope == RoutineScope.household:
        await require_entitlement(db, home_id, "routines.household.enabled")
    else:
        # Race-safe per-person limit — same pg_advisory_xact_lock pattern as
        # routers.calendar's calendar-creation endpoint, keyed per person
        # (not just per Home) since routines.personal.max_active is a
        # per-person entitlement — see
        # mykhaya.entitlements.personal_routine_usage.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"personal-routines:{home_id}:{auth.user.id}"},
        )
        current_count = (
            await db.scalar(
                select(func.count(HouseholdRoutine.id)).where(
                    HouseholdRoutine.group_id == home_id,
                    HouseholdRoutine.scope == RoutineScope.personal,
                    HouseholdRoutine.owner_user_id == auth.user.id,
                    HouseholdRoutine.enabled.is_(True),
                )
            )
            or 0
        )
        await require_within_limit(db, home_id, "routines.personal.max_active", current_count)

    member_ids = await _validate_members(db, home_id, body.member_ids)

    # owner_user_id is never accepted from client input (RoutineCreate has no such
    # field) — a personal routine's owner is always the authenticated actor. There is
    # no "create personal routine on someone else's behalf" capability in MyKhaya's
    # authorization model; see docs task notes on routine scope.
    routine = HouseholdRoutine(
        group_id=home_id,
        title=" ".join(body.title.strip().split()),
        description=body.description,
        scope=body.scope,
        owner_user_id=auth.user.id if body.scope == RoutineScope.personal else None,
        interval_weeks=body.interval_weeks,
        repeat_unit=body.repeat_unit,
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
    if routine is None or not _is_visible(routine, auth.user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That routine could not be found")
    if routine.updated_at != body.expected_updated_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "This routine changed. Reload and try again.")

    # Entitlement checks only apply to a genuine *transition* into a
    # restricted state — never to saving an unrelated edit on a routine that
    # already existed in that state (e.g. a downgraded Home's existing
    # household routines stay editable, matching Calendar's downgrade
    # philosophy: preserve/allow existing, block only new commitment).
    was_household = routine.scope == RoutineScope.household
    will_be_household = body.scope == RoutineScope.household
    if will_be_household and not was_household:
        await require_entitlement(db, home_id, "routines.household.enabled")

    was_counted_personal = routine.scope == RoutineScope.personal and routine.enabled
    will_be_counted_personal = body.scope == RoutineScope.personal and body.enabled
    if will_be_counted_personal and not was_counted_personal:
        effective_owner_id = (
            routine.owner_user_id if routine.scope == RoutineScope.personal else auth.user.id
        )
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"personal-routines:{home_id}:{effective_owner_id}"},
        )
        current_count = (
            await db.scalar(
                select(func.count(HouseholdRoutine.id)).where(
                    HouseholdRoutine.group_id == home_id,
                    HouseholdRoutine.scope == RoutineScope.personal,
                    HouseholdRoutine.owner_user_id == effective_owner_id,
                    HouseholdRoutine.enabled.is_(True),
                    HouseholdRoutine.id != routine.id,
                )
            )
            or 0
        )
        await require_within_limit(db, home_id, "routines.personal.max_active", current_count)

    member_ids = await _validate_members(db, home_id, body.member_ids)
    await db.execute(
        delete(HouseholdRoutineMember).where(HouseholdRoutineMember.routine_id == routine.id)
    )
    for user_id in member_ids:
        db.add(HouseholdRoutineMember(routine_id=routine.id, user_id=user_id))

    routine.title = " ".join(body.title.strip().split())
    routine.description = body.description
    routine.scope = body.scope
    # Switching a routine to personal makes the editing actor its owner unless it's
    # already personal (owner stays put — editing isn't a transfer-of-ownership
    # action); switching to household clears it, matching ck_routine_scope_owner.
    if body.scope == RoutineScope.personal:
        routine.owner_user_id = routine.owner_user_id or auth.user.id
    else:
        routine.owner_user_id = None
    routine.interval_weeks = body.interval_weeks
    routine.repeat_unit = body.repeat_unit
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
    if routine is None or not _is_visible(routine, auth.user.id):
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
    if routine is None or not _is_visible(routine, auth.user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That routine could not be found")
    if routine.scope == RoutineScope.household:
        await require_entitlement(db, home_id, "routines.household.enabled")
    if not is_occurrence_date(routine, body.occurrence_date):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "That date is not a scheduled occurrence"
        )

    await db.execute(
        pg_insert(HouseholdRoutineCompletion)
        .values(
            routine_id=routine.id,
            occurrence_date=body.occurrence_date,
            completed_by=auth.user.id,
        )
        .on_conflict_do_nothing(constraint="uq_routine_occurrence")
    )
    await db.commit()
    return await _to_response(db, routine)


@router.delete("/{home_id}/routines/{routine_id}/complete/{occurrence_date}", status_code=204)
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
    if routine is None or not _is_visible(routine, auth.user.id):
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
