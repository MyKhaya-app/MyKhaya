"""Meal Plans (Family-only) — see docs/architecture/meal-plans.md for the
architecture notes this module was built against: reused entitlement
service, household/member model, feature-flag gate and API conventions,
and the explicit V1 scope decisions (deferred recurrence, deferred
auto-linked leftovers). "Add ingredients to list" now integrates with
mykhaya.routers.lists' HouseholdList/HouseholdListItem, MyKhaya's one Lists
primitive — added alongside this iteration rather than a second,
meal-specific shopping-list implementation.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context
from mykhaya.entitlements import require_entitlement
from mykhaya.features import require_feature
from mykhaya.household_permissions import Capability, require_capability
from mykhaya.models import (
    FeatureKey,
    HouseholdList,
    HouseholdListItem,
    Meal,
    MealIngredient,
    MealPlanEntry,
    MealPlanParticipant,
    MealType,
    Membership,
)
from mykhaya.schemas import (
    AddIngredientsToListRequest,
    AddIngredientsToListResponse,
    CopyWeekRequest,
    CopyWeekResponse,
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
    MealSummaryResponse,
    MealUpdate,
    RecentMealResponse,
    RecentMealsResponse,
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


async def _ingredient_counts(db: AsyncSession, meal_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """One grouped query for every meal's ingredient count rather than N —
    the library list view only ever needs a count per card, never the full
    ingredient text of every meal on screen."""
    if not meal_ids:
        return {}
    rows = (
        await db.execute(
            select(MealIngredient.meal_id, func.count())
            .where(MealIngredient.meal_id.in_(meal_ids))
            .group_by(MealIngredient.meal_id)
        )
    ).all()
    return {meal_id: count for meal_id, count in rows}


def _meal_summary(meal: Meal, ingredient_count: int) -> MealSummaryResponse:
    return MealSummaryResponse(
        id=meal.id,
        name=meal.name,
        description=meal.description,
        image_url=meal.image_url,
        meal_type=meal.meal_type,
        prep_minutes=meal.prep_minutes,
        cook_minutes=meal.cook_minutes,
        servings=meal.servings,
        is_favourite=meal.is_favourite,
        tags=meal.tags,
        ingredient_count=ingredient_count,
        created_at=meal.created_at,
        updated_at=meal.updated_at,
    )


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


async def _participants_by_entry(
    db: AsyncSession, entry_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """One query for every entry's participants rather than one query per
    entry — used by day/week retrieval, where N entries would otherwise
    mean N+1 queries just to know who's eating."""
    if not entry_ids:
        return {}
    rows = (
        await db.execute(
            select(MealPlanParticipant.meal_plan_entry_id, MealPlanParticipant.user_id).where(
                MealPlanParticipant.meal_plan_entry_id.in_(entry_ids)
            )
        )
    ).all()
    by_entry: dict[uuid.UUID, list[uuid.UUID]] = {}
    for entry_id, user_id in rows:
        by_entry.setdefault(entry_id, []).append(user_id)
    for participants in by_entry.values():
        participants.sort()
    return by_entry


async def _entry_response(
    db: AsyncSession,
    entry: MealPlanEntry,
    meal: Meal | None,
    *,
    participants: list[uuid.UUID] | None = None,
) -> MealPlanEntryResponse:
    resolved_participants = (
        participants if participants is not None else await _participant_ids(db, entry.id)
    )
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
        member_ids=resolved_participants,
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
        needle = f"%{q.strip()}%"
        # Name + description only — tags is a JSON column, and matching
        # into it isn't a "straightforward" text search, so it's left out
        # rather than reached for with a bespoke JSON-text cast.
        filters.append(or_(Meal.name.ilike(needle), Meal.description.ilike(needle)))
    meals = (
        await db.scalars(select(Meal).where(*filters).order_by(Meal.name))
    ).all()
    counts = await _ingredient_counts(db, [meal.id for meal in meals])
    return MealListResponse(
        items=[_meal_summary(meal, counts.get(meal.id, 0)) for meal in meals]
    )


@router.get("/{home_id}/meals/recent", response_model=RecentMealsResponse)
async def recent_meals(
    home_id: uuid.UUID,
    limit: int = Query(default=8, ge=1, le=25),
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> RecentMealsResponse:
    """Meals most recently planned, derived straight from MealPlanEntry —
    not a separate "last used" counter to keep in sync. One grouped query
    for the most recent date per meal, then a batch meal + ingredient-count
    fetch for just those meals."""
    await require_capability(home_id, Capability.meals_view, auth, db)
    await require_entitlement(db, home_id, "meals.enabled")

    last_planned_rows = (
        await db.execute(
            select(MealPlanEntry.meal_id, func.max(MealPlanEntry.date))
            .where(
                MealPlanEntry.group_id == home_id,
                MealPlanEntry.deleted_at.is_(None),
                MealPlanEntry.meal_id.is_not(None),
            )
            .group_by(MealPlanEntry.meal_id)
            .order_by(func.max(MealPlanEntry.date).desc())
            .limit(limit)
        )
    ).all()
    meal_ids = [meal_id for meal_id, _ in last_planned_rows]
    meals = await _meals_by_id(db, home_id, set(meal_ids))
    counts = await _ingredient_counts(db, meal_ids)
    items = [
        RecentMealResponse(
            meal=_meal_summary(meals[meal_id], counts.get(meal_id, 0)),
            last_planned=last_planned,
        )
        for meal_id, last_planned in last_planned_rows
        # A meal soft-deleted since it was last planned simply drops out of
        # "recently used" rather than surfacing a dead card — _meals_by_id
        # itself still returns deleted rows (day/week views need that, to
        # keep showing a historical entry's name/image), so the filter has
        # to check deleted_at explicitly here rather than membership alone.
        if meal_id in meals and meals[meal_id].deleted_at is None
    ]
    return RecentMealsResponse(items=items)


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
    participants = await _participants_by_entry(db, [row.id for row in entries])
    items = [
        await _entry_response(
            db, row, _meal_for(row, meals), participants=participants.get(row.id, [])
        )
        for row in entries
    ]
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
    participants = await _participants_by_entry(db, [row.id for row in entries])
    by_date: dict[date, list[MealPlanEntry]] = {}
    for row in entries:
        by_date.setdefault(row.date, []).append(row)
    days = []
    for offset in range(7):
        day = start_date + timedelta(days=offset)
        rows = by_date.get(day, [])
        items = [
            await _entry_response(
                db, row, _meal_for(row, meals), participants=participants.get(row.id, [])
            )
            for row in rows
        ]
        days.append(MealPlanDayResponse(date=day, entries=items))
    return MealPlanWeekResponse(start_date=start_date, days=days)


# ---------------------------------------------------------------------------
# Save a quick meal to the library
# ---------------------------------------------------------------------------


@router.post(
    "/{home_id}/meal-plan/entries/{entry_id}/save-as-meal", response_model=MealPlanEntryResponse
)
async def save_entry_as_meal(
    home_id: uuid.UUID,
    entry_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> MealPlanEntryResponse:
    """Turns a frequently-reused quick meal ("Fajitas") into a real library
    Meal, and repoints this one planned entry at it — the mechanical half
    of "Save to Meals"; the other planned entries an ambiguous quick-meal
    text might match are deliberately left untouched, since MealPlanEntry
    keeps free text, not a foreign key, until this action is taken."""
    await require_capability(home_id, Capability.meals_manage, auth, db)
    await require_entitlement(db, home_id, "meals.enabled")

    entry = await _get_active_entry(db, home_id, entry_id, for_update=True)
    if entry.meal_id is not None or not entry.quick_meal_name:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This planned meal is already backed by a saved meal."
        )

    # MealSlot (breakfast/lunch/dinner) is a strict subset of MealType's
    # values, so the slot the quick meal was planned into is always a valid
    # starting category for the new library Meal.
    meal = Meal(
        group_id=home_id,
        name=entry.quick_meal_name,
        meal_type=MealType(entry.meal_slot.value),
        created_by=auth.user.id,
    )
    db.add(meal)
    await db.flush()
    entry.meal_id = meal.id
    entry.quick_meal_name = None
    audit(db, request, "meals.meal.created_from_quick_meal", auth.user.id, home_id, "meal", meal.id)
    await db.commit()
    await db.refresh(entry)
    return await _entry_response(db, entry, meal)


# ---------------------------------------------------------------------------
# Add ingredients to a Household List
# ---------------------------------------------------------------------------


def _ingredient_item_text(ingredient: MealIngredient) -> str:
    parts = [part for part in (ingredient.quantity, ingredient.unit, ingredient.text) if part]
    return " ".join(parts)


@router.post(
    "/{home_id}/meals/{meal_id}/add-ingredients-to-list",
    response_model=AddIngredientsToListResponse,
)
async def add_ingredients_to_list(
    home_id: uuid.UUID,
    meal_id: uuid.UUID,
    body: AddIngredientsToListRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> AddIngredientsToListResponse:
    """A single server-side operation rather than a client-orchestrated
    read-list/read-meal/write-items sequence — the server is the only place
    that can validate Meal ownership, List ownership and both modules'
    entitlements together in one transaction. See
    docs/architecture/meal-plans.md "Lists integration"."""
    await require_capability(home_id, Capability.meals_view, auth, db)
    await require_entitlement(db, home_id, "meals.enabled")
    await require_capability(home_id, Capability.lists_manage, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")

    meal = await _get_active_meal(db, home_id, meal_id)
    target_list = await db.scalar(
        select(HouseholdList)
        .where(
            HouseholdList.id == body.list_id,
            HouseholdList.group_id == home_id,
            HouseholdList.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if target_list is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That list could not be found")

    ingredients = (
        await db.scalars(
            select(MealIngredient)
            .where(MealIngredient.meal_id == meal.id)
            .order_by(MealIngredient.position)
        )
    ).all()
    if body.ingredient_ids is not None:
        wanted = set(body.ingredient_ids)
        ingredients = [row for row in ingredients if row.id in wanted]

    candidate_texts = [_ingredient_item_text(row) for row in ingredients]
    candidate_texts = [text for text in candidate_texts if text]
    if not candidate_texts:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No ingredients to add")

    existing_texts = {
        text.strip().lower()
        for text in (
            await db.scalars(
                select(HouseholdListItem.text).where(HouseholdListItem.list_id == target_list.id)
            )
        ).all()
    }
    duplicates = [text for text in candidate_texts if text.strip().lower() in existing_texts]
    new_texts = [text for text in candidate_texts if text.strip().lower() not in existing_texts]

    if duplicates and not body.confirm:
        return AddIngredientsToListResponse(
            requires_confirmation=True,
            added_count=0,
            duplicate_count=len(duplicates),
            duplicate_texts=duplicates,
            list_id=target_list.id,
        )

    # Duplicates are never (re-)added, confirmed or not — "confirm" only
    # gets the user past the warning ("2 already on Groceries. Add the
    # remaining 4?"); the 4 it then adds are exactly `new_texts`.
    to_add = new_texts
    next_position = await db.scalar(
        select(func.count()).select_from(HouseholdListItem).where(
            HouseholdListItem.list_id == target_list.id
        )
    ) or 0
    for offset, text in enumerate(to_add):
        db.add(
            HouseholdListItem(
                list_id=target_list.id,
                position=next_position + offset,
                text=text,
                created_by=auth.user.id,
            )
        )
    audit(
        db,
        request,
        "meals.meal.ingredients_added_to_list",
        auth.user.id,
        home_id,
        "list",
        target_list.id,
        metadata={"meal_id": str(meal.id), "count": len(to_add)},
    )
    await db.commit()
    return AddIngredientsToListResponse(
        requires_confirmation=False,
        added_count=len(to_add),
        duplicate_count=len(duplicates),
        duplicate_texts=duplicates,
        list_id=target_list.id,
    )


# ---------------------------------------------------------------------------
# Copy previous week
# ---------------------------------------------------------------------------


@router.post("/{home_id}/meal-plan/week/copy", response_model=CopyWeekResponse)
async def copy_week(
    home_id: uuid.UUID,
    body: CopyWeekRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> CopyWeekResponse:
    """Copies each source-week entry into the corresponding weekday/slot of
    the target week, skipping any target slot that already has a planned
    meal. A one-off copy, not a recurrence record — see
    docs/architecture/meal-plans.md "Copy previous week". Runs inside the
    request's single transaction (one commit at the end), so a failure
    partway through leaves nothing copied rather than half a week."""
    await require_capability(home_id, Capability.meals_manage, auth, db)
    await require_entitlement(db, home_id, "meals.enabled")

    source_end = body.source_start_date + timedelta(days=6)
    target_end = body.target_start_date + timedelta(days=6)
    source_entries = await _entries_for_range(db, home_id, body.source_start_date, source_end)
    target_entries = await _entries_for_range(db, home_id, body.target_start_date, target_end)
    occupied = {(row.date, row.meal_slot) for row in target_entries}

    active_members = set(await _active_member_ids(db, home_id))
    meal_ids = {row.meal_id for row in source_entries if row.meal_id}
    meals = await _meals_by_id(db, home_id, meal_ids)
    participants = await _participants_by_entry(db, [row.id for row in source_entries])

    copied = 0
    skipped = 0
    for row in source_entries:
        offset = (row.date - body.source_start_date).days
        target_date = body.target_start_date + timedelta(days=offset)
        if (target_date, row.meal_slot) in occupied:
            skipped += 1
            continue

        # A meal soft-deleted since the source week was planned falls back
        # to a quick-meal name rather than resurrecting it or copying a
        # broken reference (see docs/architecture/meal-plans.md "Copy
        # previous week" safety notes).
        meal = meals.get(row.meal_id) if row.meal_id else None
        if meal is not None and meal.deleted_at is not None:
            meal = None
        meal_id = meal.id if meal is not None else None
        quick_name = row.quick_meal_name
        if row.meal_id is not None and meal is None:
            source_meal = await db.scalar(select(Meal).where(Meal.id == row.meal_id))
            quick_name = source_meal.name if source_meal is not None else "Meal"

        cook_member_id = row.cook_member_id if row.cook_member_id in active_members else None
        entry_participants = [
            user_id for user_id in participants.get(row.id, []) if user_id in active_members
        ]

        if not body.dry_run:
            new_entry = MealPlanEntry(
                group_id=home_id,
                meal_id=meal_id,
                quick_meal_name=quick_name if meal_id is None else None,
                date=target_date,
                meal_slot=row.meal_slot,
                time=row.time,
                cook_member_id=cook_member_id,
                makes_leftovers=row.makes_leftovers,
                created_by=auth.user.id,
            )
            db.add(new_entry)
            await db.flush()
            await _set_participants(db, new_entry.id, entry_participants)
        copied += 1

    if not body.dry_run:
        audit(
            db,
            request,
            "meals.plan_week.copied",
            auth.user.id,
            home_id,
            "meal_plan_entry",
            None,
            metadata={
                "source_start_date": body.source_start_date.isoformat(),
                "target_start_date": body.target_start_date.isoformat(),
                "copied": copied,
                "skipped": skipped,
            },
        )
        await db.commit()
    return CopyWeekResponse(copied_count=copied, skipped_count=skipped)
