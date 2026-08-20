"""Meal Plans (Family-only) — see docs/architecture/meal-plans.md for the
architecture notes this module was built against: reused entitlement
service, household/member model, feature-flag gate and API conventions,
and the explicit V1 scope decisions (deferred recurrence, deferred
auto-linked leftovers, deferred Lists integration since MyKhaya has no
Lists module yet).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context
from mykhaya.entitlements import require_entitlement
from mykhaya.features import require_feature
from mykhaya.household_permissions import Capability, require_capability
from mykhaya.models import (
    FeatureKey,
    Meal,
    MealIngredient,
    MealPlanEntry,
    MealPlanParticipant,
    Membership,
)
from mykhaya.schemas import (
    MealCreate,
    MealFavouriteRequest,
    MealIngredientResponse,
    MealListResponse,
    MealPlanDayResponse,
    MealPlanEntryCreate,
    MealPlanEntryResponse,
    MealPlanEntryUpdate,
    MealPlanWeekResponse,
    MealResponse,
    MealUpdate,
)

# Meal Plans has its own dedicated FeatureKey/module_registry entry (unlike
# household_routines, which currently piggy-backs on the notifications
# feature flag) — a household must have this Platform-Admin-releasable
# feature switched on, same mechanism as Calendar.


async def require_meals_feature(
    home_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_feature(db, FeatureKey.meals, home_id)


router = APIRouter(
    prefix="/homes",
    tags=["meal-plans"],
    dependencies=[Depends(require_meals_feature)],
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _validate_member_ids(
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


async def _active_member_ids(db: AsyncSession, home_id: uuid.UUID) -> list[uuid.UUID]:
    rows = (
        await db.scalars(
            select(Membership.user_id).where(
                Membership.group_id == home_id, Membership.removed_at.is_(None)
            )
        )
    ).all()
    return sorted(rows)


async def _meal_ingredients(db: AsyncSession, meal_id: uuid.UUID) -> list[MealIngredientResponse]:
    rows = (
        await db.scalars(
            select(MealIngredient)
            .where(MealIngredient.meal_id == meal_id)
            .order_by(MealIngredient.position)
        )
    ).all()
    return [
        MealIngredientResponse(
            id=row.id, position=row.position, text=row.text, quantity=row.quantity, unit=row.unit
        )
        for row in rows
    ]


def _meal_response(meal: Meal, ingredients: list[MealIngredientResponse]) -> MealResponse:
    return MealResponse(
        id=meal.id,
        name=meal.name,
        description=meal.description,
        image_url=meal.image_url,
        meal_type=meal.meal_type,
        prep_minutes=meal.prep_minutes,
        cook_minutes=meal.cook_minutes,
        servings=meal.servings,
        instructions=meal.instructions,
        is_favourite=meal.is_favourite,
        tags=meal.tags,
        source_url=meal.source_url,
        ingredients=ingredients,
        created_by=meal.created_by,
        created_at=meal.created_at,
        updated_at=meal.updated_at,
    )


async def _get_active_meal(db: AsyncSession, home_id: uuid.UUID, meal_id: uuid.UUID) -> Meal:
    meal = await db.scalar(
        select(Meal).where(
            Meal.id == meal_id, Meal.group_id == home_id, Meal.deleted_at.is_(None)
        )
    )
    if meal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That meal could not be found")
    return meal


async def _participant_ids(db: AsyncSession, entry_id: uuid.UUID) -> list[uuid.UUID]:
    rows = (
        await db.scalars(
            select(MealPlanParticipant.user_id).where(
                MealPlanParticipant.meal_plan_entry_id == entry_id
            )
        )
    ).all()
    return sorted(rows)


async def _entry_response(
    db: AsyncSession, entry: MealPlanEntry, meal: Meal | None
) -> MealPlanEntryResponse:
    participants = await _participant_ids(db, entry.id)
    return MealPlanEntryResponse(
        id=entry.id,
        meal_id=entry.meal_id,
        meal_name=meal.name if meal is not None else None,
        quick_meal_name=entry.quick_meal_name,
        meal_image_url=meal.image_url if meal is not None else None,
        is_favourite=meal.is_favourite if meal is not None else False,
        date=entry.date,
        meal_slot=entry.meal_slot,
        time=entry.time,
        member_ids=participants,
        cook_member_id=entry.cook_member_id,
        makes_leftovers=entry.makes_leftovers,
        created_by=entry.created_by,
        updated_at=entry.updated_at,
    )


def _meal_for(entry: MealPlanEntry, meals: dict[uuid.UUID, Meal]) -> Meal | None:
    return meals.get(entry.meal_id) if entry.meal_id is not None else None


async def _meals_by_id(
    db: AsyncSession, home_id: uuid.UUID, meal_ids: set[uuid.UUID]
) -> dict[uuid.UUID, Meal]:
    if not meal_ids:
        return {}
    rows = (
        await db.scalars(select(Meal).where(Meal.group_id == home_id, Meal.id.in_(meal_ids)))
    ).all()
    return {row.id: row for row in rows}


# ---------------------------------------------------------------------------
# Meals library
# ---------------------------------------------------------------------------


@router.post("/{home_id}/meals", response_model=MealResponse, status_code=201)
async def create_meal(
    home_id: uuid.UUID,
    body: MealCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> MealResponse:
    await require_capability(home_id, Capability.meals_manage, auth, db)
    await require_entitlement(db, home_id, "meals.enabled")

    meal = Meal(
        group_id=home_id,
        name=" ".join(body.name.strip().split()),
        description=body.description,
        image_url=body.image_url,
        meal_type=body.meal_type,
        prep_minutes=body.prep_minutes,
        cook_minutes=body.cook_minutes,
        servings=body.servings,
        instructions=body.instructions,
        is_favourite=body.is_favourite,
        tags=body.tags,
        source_url=body.source_url,
        created_by=auth.user.id,
    )
    db.add(meal)
    await db.flush()
    for position, ingredient in enumerate(body.ingredients):
        db.add(
            MealIngredient(
                meal_id=meal.id,
                position=position,
                text=ingredient.text.strip(),
                quantity=ingredient.quantity,
                unit=ingredient.unit,
            )
        )
    audit(db, request, "meals.meal.created", auth.user.id, home_id, "meal", meal.id)
    await db.commit()
    return _meal_response(meal, await _meal_ingredients(db, meal.id))


@router.get("/{home_id}/meals", response_model=MealListResponse)
async def list_meals(
    home_id: uuid.UUID,
    favourite: bool | None = Query(default=None),
    q: str | None = Query(default=None, max_length=80),
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> MealListResponse:
    await require_capability(home_id, Capability.meals_view, auth, db)
    await require_entitlement(db, home_id, "meals.enabled")

    filters = [Meal.group_id == home_id, Meal.deleted_at.is_(None)]
    if favourite is not None:
        filters.append(Meal.is_favourite.is_(favourite))
    if q:
        filters.append(Meal.name.ilike(f"%{q.strip()}%"))
    meals = (
        await db.scalars(select(Meal).where(*filters).order_by(Meal.name))
    ).all()
    items = []
    for meal in meals:
        items.append(_meal_response(meal, await _meal_ingredients(db, meal.id)))
    return MealListResponse(items=items)


@router.get("/{home_id}/meals/{meal_id}", response_model=MealResponse)
async def get_meal(
    home_id: uuid.UUID,
    meal_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> MealResponse:
    await require_capability(home_id, Capability.meals_view, auth, db)
    await require_entitlement(db, home_id, "meals.enabled")
    meal = await _get_active_meal(db, home_id, meal_id)
    return _meal_response(meal, await _meal_ingredients(db, meal.id))


@router.patch("/{home_id}/meals/{meal_id}", response_model=MealResponse)
async def update_meal(
    home_id: uuid.UUID,
    meal_id: uuid.UUID,
    body: MealUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> MealResponse:
    await require_capability(home_id, Capability.meals_manage, auth, db)
    await require_entitlement(db, home_id, "meals.enabled")

    meal = await db.scalar(
        select(Meal)
        .where(Meal.id == meal_id, Meal.group_id == home_id, Meal.deleted_at.is_(None))
        .with_for_update()
    )
    if meal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That meal could not be found")
    if meal.updated_at != body.expected_updated_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "This meal changed. Reload and try again.")

    meal.name = " ".join(body.name.strip().split())
    meal.description = body.description
    meal.image_url = body.image_url
    meal.meal_type = body.meal_type
    meal.prep_minutes = body.prep_minutes
    meal.cook_minutes = body.cook_minutes
    meal.servings = body.servings
    meal.instructions = body.instructions
    meal.is_favourite = body.is_favourite
    meal.tags = body.tags
    meal.source_url = body.source_url

    await db.execute(delete(MealIngredient).where(MealIngredient.meal_id == meal.id))
    for position, ingredient in enumerate(body.ingredients):
        db.add(
            MealIngredient(
                meal_id=meal.id,
                position=position,
                text=ingredient.text.strip(),
                quantity=ingredient.quantity,
                unit=ingredient.unit,
            )
        )
    audit(db, request, "meals.meal.updated", auth.user.id, home_id, "meal", meal.id)
    await db.commit()
    # updated_at is server-computed (onupdate=func.now()) — refresh so the
    # response reflects the real new value rather than a stale in-memory
    # one, and so the attribute access below never triggers an implicit
    # lazy-load outside an awaited context (MissingGreenlet).
    await db.refresh(meal)
    return _meal_response(meal, await _meal_ingredients(db, meal.id))


@router.patch("/{home_id}/meals/{meal_id}/favourite", response_model=MealResponse)
async def set_meal_favourite(
    home_id: uuid.UUID,
    meal_id: uuid.UUID,
    body: MealFavouriteRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> MealResponse:
    await require_capability(home_id, Capability.meals_manage, auth, db)
    await require_entitlement(db, home_id, "meals.enabled")
    meal = await _get_active_meal(db, home_id, meal_id)
    meal.is_favourite = body.is_favourite
    audit(
        db,
        request,
        "meals.meal.favourited" if body.is_favourite else "meals.meal.unfavourited",
        auth.user.id,
        home_id,
        "meal",
        meal.id,
    )
    await db.commit()
    await db.refresh(meal)
    return _meal_response(meal, await _meal_ingredients(db, meal.id))


@router.delete("/{home_id}/meals/{meal_id}", status_code=204)
async def delete_meal(
    home_id: uuid.UUID,
    meal_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_capability(home_id, Capability.meals_manage, auth, db)
    await require_entitlement(db, home_id, "meals.enabled")
    meal = await _get_active_meal(db, home_id, meal_id)
    # Soft delete only — see Meal's docstring: existing MealPlanEntry rows
    # keep pointing at meal_id, so a planned/past meal never loses its name.
    meal.deleted_at = datetime.now(tz=meal.created_at.tzinfo)
    audit(db, request, "meals.meal.deleted", auth.user.id, home_id, "meal", meal.id)
    await db.commit()


# ---------------------------------------------------------------------------
# Meal Plan entries (the planner)
# ---------------------------------------------------------------------------


async def _resolve_meal_reference(
    db: AsyncSession, home_id: uuid.UUID, meal_id: uuid.UUID | None
) -> Meal | None:
    if meal_id is None:
        return None
    meal = await _get_active_meal(db, home_id, meal_id)
    return meal


def _quick_meal_name(meal: Meal | None, raw: str | None) -> str | None:
    """A saved-meal reference always wins — quick_meal_name is only ever
    set when there's no meal_id, per ck_meal_plan_entry_has_meal."""
    if meal is not None or not raw:
        return None
    return " ".join(raw.strip().split())


async def _set_participants(
    db: AsyncSession, entry_id: uuid.UUID, member_ids: list[uuid.UUID]
) -> None:
    await db.execute(
        delete(MealPlanParticipant).where(MealPlanParticipant.meal_plan_entry_id == entry_id)
    )
    for user_id in member_ids:
        db.add(MealPlanParticipant(meal_plan_entry_id=entry_id, user_id=user_id))


@router.post("/{home_id}/meal-plan/entries", response_model=MealPlanEntryResponse, status_code=201)
async def create_meal_plan_entry(
    home_id: uuid.UUID,
    body: MealPlanEntryCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> MealPlanEntryResponse:
    await require_capability(home_id, Capability.meals_manage, auth, db)
    await require_entitlement(db, home_id, "meals.enabled")

    meal = await _resolve_meal_reference(db, home_id, body.meal_id)

    # None (omitted) defaults to the whole household ("Everyone") — an
    # explicit empty list means the user deliberately chose nobody.
    if body.member_ids is None:
        member_ids = await _active_member_ids(db, home_id)
    else:
        member_ids = await _validate_member_ids(db, home_id, body.member_ids)

    if body.cook_member_id is not None:
        await _validate_member_ids(db, home_id, [body.cook_member_id])

    entry = MealPlanEntry(
        group_id=home_id,
        meal_id=meal.id if meal is not None else None,
        quick_meal_name=_quick_meal_name(meal, body.quick_meal_name),
        date=body.date,
        meal_slot=body.meal_slot,
        time=body.time,
        cook_member_id=body.cook_member_id,
        makes_leftovers=body.makes_leftovers,
        created_by=auth.user.id,
    )
    db.add(entry)
    await db.flush()
    await _set_participants(db, entry.id, member_ids)
    audit(
        db, request, "meals.plan_entry.created", auth.user.id, home_id, "meal_plan_entry", entry.id
    )
    await db.commit()
    return await _entry_response(db, entry, meal)


async def _get_active_entry(
    db: AsyncSession, home_id: uuid.UUID, entry_id: uuid.UUID, *, for_update: bool = False
) -> MealPlanEntry:
    query = select(MealPlanEntry).where(
        MealPlanEntry.id == entry_id,
        MealPlanEntry.group_id == home_id,
        MealPlanEntry.deleted_at.is_(None),
    )
    if for_update:
        query = query.with_for_update()
    entry = await db.scalar(query)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That planned meal could not be found")
    return entry


@router.get("/{home_id}/meal-plan/entries/{entry_id}", response_model=MealPlanEntryResponse)
async def get_meal_plan_entry(
    home_id: uuid.UUID,
    entry_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> MealPlanEntryResponse:
    await require_capability(home_id, Capability.meals_view, auth, db)
    await require_entitlement(db, home_id, "meals.enabled")
    entry = await _get_active_entry(db, home_id, entry_id)
    meal = await _resolve_meal_reference(db, home_id, entry.meal_id) if entry.meal_id else None
    return await _entry_response(db, entry, meal)


@router.patch("/{home_id}/meal-plan/entries/{entry_id}", response_model=MealPlanEntryResponse)
async def update_meal_plan_entry(
    home_id: uuid.UUID,
    entry_id: uuid.UUID,
    body: MealPlanEntryUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> MealPlanEntryResponse:
    await require_capability(home_id, Capability.meals_manage, auth, db)
    await require_entitlement(db, home_id, "meals.enabled")

    entry = await _get_active_entry(db, home_id, entry_id, for_update=True)
    if entry.updated_at != body.expected_updated_at:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This planned meal changed. Reload and try again."
        )

    meal = await _resolve_meal_reference(db, home_id, body.meal_id)

    if body.member_ids is None:
        member_ids = await _active_member_ids(db, home_id)
    else:
        member_ids = await _validate_member_ids(db, home_id, body.member_ids)
    if body.cook_member_id is not None:
        await _validate_member_ids(db, home_id, [body.cook_member_id])

    entry.meal_id = meal.id if meal is not None else None
    entry.quick_meal_name = _quick_meal_name(meal, body.quick_meal_name)
    entry.date = body.date
    entry.meal_slot = body.meal_slot
    entry.time = body.time
    entry.cook_member_id = body.cook_member_id
    entry.makes_leftovers = body.makes_leftovers

    await _set_participants(db, entry.id, member_ids)
    audit(
        db, request, "meals.plan_entry.updated", auth.user.id, home_id, "meal_plan_entry", entry.id
    )
    await db.commit()
    await db.refresh(entry)
    return await _entry_response(db, entry, meal)


@router.delete("/{home_id}/meal-plan/entries/{entry_id}", status_code=204)
async def delete_meal_plan_entry(
    home_id: uuid.UUID,
    entry_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_capability(home_id, Capability.meals_manage, auth, db)
    await require_entitlement(db, home_id, "meals.enabled")
    entry = await _get_active_entry(db, home_id, entry_id)
    entry.deleted_at = datetime.now(tz=entry.created_at.tzinfo)
    audit(
        db, request, "meals.plan_entry.deleted", auth.user.id, home_id, "meal_plan_entry", entry.id
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Day / week retrieval
# ---------------------------------------------------------------------------


async def _entries_for_range(
    db: AsyncSession, home_id: uuid.UUID, start: date, end_inclusive: date
) -> list[MealPlanEntry]:
    return list(
        (
            await db.scalars(
                select(MealPlanEntry)
                .where(
                    MealPlanEntry.group_id == home_id,
                    MealPlanEntry.deleted_at.is_(None),
                    MealPlanEntry.date >= start,
                    MealPlanEntry.date <= end_inclusive,
                )
                .order_by(MealPlanEntry.date, MealPlanEntry.meal_slot)
            )
        ).all()
    )


@router.get("/{home_id}/meal-plan/day", response_model=MealPlanDayResponse)
async def get_meal_plan_day(
    home_id: uuid.UUID,
    plan_date: date = Query(alias="date"),
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> MealPlanDayResponse:
    await require_capability(home_id, Capability.meals_view, auth, db)
    await require_entitlement(db, home_id, "meals.enabled")
    entries = await _entries_for_range(db, home_id, plan_date, plan_date)
    meals = await _meals_by_id(db, home_id, {row.meal_id for row in entries if row.meal_id})
    items = [await _entry_response(db, row, _meal_for(row, meals)) for row in entries]
    return MealPlanDayResponse(date=plan_date, entries=items)


@router.get("/{home_id}/meal-plan/week", response_model=MealPlanWeekResponse)
async def get_meal_plan_week(
    home_id: uuid.UUID,
    start_date: date = Query(),
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> MealPlanWeekResponse:
    await require_capability(home_id, Capability.meals_view, auth, db)
    await require_entitlement(db, home_id, "meals.enabled")
    end_date = start_date + timedelta(days=6)
    entries = await _entries_for_range(db, home_id, start_date, end_date)
    meals = await _meals_by_id(db, home_id, {row.meal_id for row in entries if row.meal_id})
    by_date: dict[date, list[MealPlanEntry]] = {}
    for row in entries:
        by_date.setdefault(row.date, []).append(row)
    days = []
    for offset in range(7):
        day = start_date + timedelta(days=offset)
        rows = by_date.get(day, [])
        items = [await _entry_response(db, row, _meal_for(row, meals)) for row in rows]
        days.append(MealPlanDayResponse(date=day, entries=items))
    return MealPlanWeekResponse(start_date=start_date, days=days)
