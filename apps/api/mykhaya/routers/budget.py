"""Personal Budget API.

Budget rows belong to an adult User. A Home is supplied only as the context
for feature availability and membership checks; no Budget table is Home-owned.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.budget_schemas import (
    BudgetActualUpdate,
    BudgetCategoryCreate,
    BudgetCategoryNoteUpdate,
    BudgetCategoryResponse,
    BudgetCategoryUpdate,
    BudgetItemCreate,
    BudgetItemResponse,
    BudgetItemUpdate,
    BudgetMonthCopyRequest,
    BudgetMonthItemResponse,
    BudgetIncomeSourceCreate,
    BudgetIncomeSourceResponse,
    BudgetIncomeSourceUpdate,
    BudgetIncomingShareResponse,
    BudgetMonthCategoryResponse,
    BudgetMonthIncomeResponse,
    BudgetMonthIncomeUpdate,
    BudgetMonthResponse,
    BudgetPartnerShareCreate,
    BudgetPartnerShareResponse,
    BudgetPlanAmountUpdate,
    BudgetProfileResponse,
    BudgetSettingsUpdate,
    BudgetSpendingEntryCreate,
    BudgetSpendingEntryResponse,
    BudgetSpendingEntryUpdate,
)
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context, membership_for, require_adult_session
from mykhaya.features import require_feature
from mykhaya.models import (
    BudgetActualSource,
    BudgetCategory,
    BudgetItem,
    BudgetItemType,
    BudgetIncomeSource,
    BudgetMonth,
    BudgetMonthCategory,
    BudgetMonthItem,
    BudgetMonthIncome,
    BudgetPartnerShare,
    BudgetProfile,
    BudgetSharingLevel,
    BudgetSpendingEntry,
    FeatureKey,
    HouseholdRelationship,
    Membership,
    User,
)

router = APIRouter(prefix="/homes", tags=["budget"])


def calculate_actual_amount(
    source: BudgetActualSource, manual_actual: Decimal | None, entries_actual: Decimal
) -> Decimal:
    """Return exactly one actual source; never sum manual and entries."""
    return manual_actual or Decimal("0") if source == BudgetActualSource.manual else entries_actual


async def _member_and_feature(
    home_id: uuid.UUID, auth: AuthContext, db: AsyncSession
) -> Membership:
    require_adult_session(auth)
    membership = await membership_for(home_id, auth, db)
    await require_feature(db, FeatureKey.budget, home_id)
    return membership


async def _profile(db: AsyncSession, user_id: uuid.UUID) -> BudgetProfile:
    row = await db.scalar(select(BudgetProfile).where(BudgetProfile.owner_user_id == user_id))
    if row is None:
        row = BudgetProfile(owner_user_id=user_id)
        db.add(row)
        await db.flush()
    if row.archived_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget not found")
    return row


def _profile_response(row: BudgetProfile) -> BudgetProfileResponse:
    return BudgetProfileResponse(
        id=row.id,
        owner_user_id=row.owner_user_id,
        currency=row.currency,
        month_start_day=row.month_start_day,
        default_view=row.default_view,
        archived=row.archived_at is not None,
    )


def _entry_response(row: BudgetSpendingEntry, category_id: uuid.UUID) -> BudgetSpendingEntryResponse:
    return BudgetSpendingEntryResponse(
        id=row.id,
        category_id=category_id,
        description=row.description,
        amount=float(row.amount),
        spent_on=row.spent_on,
        note=row.note,
    )


async def _month_for_owner(
    db: AsyncSession, profile_id: uuid.UUID, year: int, month: int
) -> BudgetMonth:
    if not 1 <= month <= 12:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Month must be between 1 and 12")
    row = await db.scalar(
        select(BudgetMonth).where(
            BudgetMonth.profile_id == profile_id,
            BudgetMonth.year == year,
            BudgetMonth.month == month,
            BudgetMonth.archived_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget month not found")
    return row


async def _create_month_snapshot(
    db: AsyncSession,
    profile: BudgetProfile,
    year: int,
    month: int,
    request: Request,
    user_id: uuid.UUID,
    *,
    copy_income: bool = True,
) -> BudgetMonth:
    """Create one independent month snapshot seeded from current masters."""
    if not 1 <= month <= 12:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Month must be between 1 and 12")
    row = BudgetMonth(profile_id=profile.id, year=year, month=month)
    db.add(row)
    await db.flush()
    categories = (
        await db.scalars(
            select(BudgetCategory).where(
                BudgetCategory.profile_id == profile.id,
                BudgetCategory.archived_at.is_(None),
            )
        )
    ).all()
    for category in categories:
        db.add(
            BudgetMonthCategory(month_id=row.id, category_id=category.id, category_name=category.name)
        )
    fixed_items = (
        await db.scalars(
            select(BudgetItem).where(
                BudgetItem.profile_id == profile.id,
                BudgetItem.item_type == BudgetItemType.fixed,
                BudgetItem.recurring.is_(True),
                BudgetItem.archived_at.is_(None),
                BudgetItem.starts_on <= date(year, month, 1),
            )
        )
    ).all()
    for item in fixed_items:
        db.add(
            BudgetMonthItem(
                month_id=row.id,
                budget_item_id=item.id,
                category_id=item.category_id,
                name_snapshot=item.name,
                item_type_snapshot=item.item_type,
                planned_amount=item.default_amount,
            )
        )
    await db.flush()
    for category_id in {item.category_id for item in fixed_items}:
        await _sync_category_planned_compatibility(db, row, category_id)
    if copy_income:
        income_sources = (
            await db.scalars(
                select(BudgetIncomeSource).where(
                    BudgetIncomeSource.profile_id == profile.id,
                    BudgetIncomeSource.archived_at.is_(None),
                )
            )
        ).all()
        for source in income_sources:
            db.add(BudgetMonthIncome(month_id=row.id, source_id=source.id, source_name=source.name))
    audit(db, request, "budget.month.created", user_id, target_type="budget_month", target_id=row.id)
    return row


def _is_current_or_future_month(year: int, month: int) -> bool:
    now = datetime.now(UTC)
    return (year, month) >= (now.year, now.month)


def _item_response(row: BudgetItem) -> BudgetItemResponse:
    return BudgetItemResponse(
        id=row.id,
        category_id=row.category_id,
        name=row.name,
        item_type=row.item_type,
        default_amount=float(row.default_amount),
        recurring=row.recurring,
        starts_on=row.starts_on,
        archived=row.archived_at is not None,
    )


async def _sync_category_planned_compatibility(
    db: AsyncSession, month: BudgetMonth, category_id: uuid.UUID
) -> None:
    """Keep the legacy category total in step without double-counting items."""
    item_total = await db.scalar(
        select(func.sum(BudgetMonthItem.planned_amount)).where(
            BudgetMonthItem.month_id == month.id,
            BudgetMonthItem.category_id == category_id,
            BudgetMonthItem.archived_at.is_(None),
        )
    )
    if item_total is None:
        return
    row = await db.scalar(
        select(BudgetMonthCategory).where(
            BudgetMonthCategory.month_id == month.id,
            BudgetMonthCategory.category_id == category_id,
        )
    )
    if row is not None:
        row.planned_amount = Decimal(item_total)


async def _reconcile_month_items(
    db: AsyncSession,
    profile_id: uuid.UUID,
    month: BudgetMonth,
    *,
    include_variables: bool = False,
) -> int:
    """Seed missing current/future item snapshots without overwriting edits."""
    if not _is_current_or_future_month(month.year, month.month):
        return 0
    items = (
        await db.scalars(
            select(BudgetItem).where(
                BudgetItem.profile_id == profile_id,
                BudgetItem.archived_at.is_(None),
                BudgetItem.starts_on <= date(month.year, month.month, 1),
                ((BudgetItem.item_type == BudgetItemType.fixed) & BudgetItem.recurring.is_(True))
                | ((BudgetItem.item_type == BudgetItemType.variable) if include_variables else False),
            )
        )
    ).all()
    existing_ids = set(
        (
            await db.scalars(
                select(BudgetMonthItem.budget_item_id).where(
                    BudgetMonthItem.month_id == month.id,
                    BudgetMonthItem.archived_at.is_(None),
                    BudgetMonthItem.budget_item_id.is_not(None),
                )
            )
        ).all()
    )
    missing = [item for item in items if item.id not in existing_ids]
    for item in missing:
        db.add(
            BudgetMonthItem(
                month_id=month.id,
                budget_item_id=item.id,
                category_id=item.category_id,
                name_snapshot=item.name,
                item_type_snapshot=item.item_type,
                planned_amount=item.default_amount,
            )
        )
    if missing:
        await db.flush()
        for category_id in {item.category_id for item in missing}:
            await _sync_category_planned_compatibility(db, month, category_id)
    return len(missing)


async def _reconcile_month_categories(
    db: AsyncSession,
    profile_id: uuid.UUID,
    month: BudgetMonth,
    request: Request | None,
    actor_id: uuid.UUID,
) -> int:
    """Repair only current/future snapshots left incomplete by the old flow."""
    if not _is_current_or_future_month(month.year, month.month):
        return 0
    categories = (
        await db.scalars(
            select(BudgetCategory).where(
                BudgetCategory.profile_id == profile_id,
                BudgetCategory.archived_at.is_(None),
            )
        )
    ).all()
    existing_ids = set(
        (
            await db.scalars(
                select(BudgetMonthCategory.category_id).where(
                    BudgetMonthCategory.month_id == month.id,
                )
            )
        ).all()
    )
    missing = [category for category in categories if category.id not in existing_ids]
    for category in missing:
        db.add(
            BudgetMonthCategory(
                month_id=month.id,
                category_id=category.id,
                category_name=category.name,
            )
        )
    if missing:
        await db.flush()
        if request is not None:
            audit(
                db,
                request,
                "budget.month.categories.reconciled",
                actor_id,
                target_type="budget_month",
                target_id=month.id,
                metadata={"category_count": len(missing), "reason": "legacy_snapshot_repair"},
            )
    return len(missing)


async def _reconcile_month_income(
    db: AsyncSession,
    profile_id: uuid.UUID,
    month: BudgetMonth,
    request: Request | None,
    actor_id: uuid.UUID,
) -> int:
    """Add newly-created sources to current/future snapshots only."""
    if not _is_current_or_future_month(month.year, month.month):
        return 0
    sources = (
        await db.scalars(
            select(BudgetIncomeSource).where(
                BudgetIncomeSource.profile_id == profile_id,
                BudgetIncomeSource.archived_at.is_(None),
            )
        )
    ).all()
    existing_ids = set(
        (
            await db.scalars(
                select(BudgetMonthIncome.source_id).where(
                    BudgetMonthIncome.month_id == month.id,
                )
            )
        ).all()
    )
    missing = [source for source in sources if source.id not in existing_ids]
    for source in missing:
        db.add(
            BudgetMonthIncome(
                month_id=month.id,
                source_id=source.id,
                source_name=source.name,
            )
        )
    if missing:
        await db.flush()
        if request is not None:
            audit(
                db,
                request,
                "budget.month.income.reconciled",
                actor_id,
                target_type="budget_month",
                target_id=month.id,
                metadata={"source_count": len(missing), "reason": "income_source_created"},
            )
    return len(missing)


async def _month_response(
    db: AsyncSession, month: BudgetMonth, *, include_categories: bool = True
) -> BudgetMonthResponse:
    rows = (
        await db.scalars(
            select(BudgetMonthCategory)
            .where(BudgetMonthCategory.month_id == month.id)
            .order_by(BudgetMonthCategory.category_name)
        )
    ).all()
    categories: list[BudgetMonthCategoryResponse] = []
    if include_categories:
        for row in rows:
            entries_total = await db.scalar(
                select(func.coalesce(func.sum(BudgetSpendingEntry.amount), 0)).where(
                    BudgetSpendingEntry.month_category_id == row.id,
                    BudgetSpendingEntry.archived_at.is_(None),
                )
            )
            entries_amount = Decimal(entries_total or 0)
            actual = calculate_actual_amount(row.actual_source, row.manual_actual, entries_amount)
            item_rows = (
                await db.scalars(
                    select(BudgetMonthItem).where(
                        BudgetMonthItem.month_id == month.id,
                        BudgetMonthItem.category_id == row.category_id,
                        BudgetMonthItem.archived_at.is_(None),
                    ).order_by(BudgetMonthItem.name_snapshot)
                )
            ).all()
            fixed_planned = sum(
                (item.planned_amount for item in item_rows if item.item_type_snapshot == BudgetItemType.fixed),
                Decimal("0"),
            )
            variable_planned = sum(
                (item.planned_amount for item in item_rows if item.item_type_snapshot == BudgetItemType.variable),
                Decimal("0"),
            )
            planned = fixed_planned + variable_planned if item_rows else row.planned_amount
            categories.append(
                BudgetMonthCategoryResponse(
                    id=row.id,
                    category_id=row.category_id,
                    category_name=row.category_name,
                    planned_amount=float(planned),
                    actual_source=row.actual_source,
                    manual_actual=float(row.manual_actual) if row.manual_actual is not None else None,
                    entries_actual=float(entries_amount),
                    actual_amount=float(actual),
                    note=row.note,
                    fixed_planned_amount=float(fixed_planned),
                    variable_planned_amount=float(variable_planned),
                    items=[
                        BudgetMonthItemResponse(
                            id=item.id,
                            budget_item_id=item.budget_item_id,
                            category_id=item.category_id,
                            name=item.name_snapshot,
                            item_type=item.item_type_snapshot,
                            planned_amount=float(item.planned_amount),
                            note=item.note,
                        )
                        for item in item_rows
                    ],
                )
            )
    income_rows = (
        await db.scalars(select(BudgetMonthIncome).where(BudgetMonthIncome.month_id == month.id))
    ).all()
    income = [
        BudgetMonthIncomeResponse(
            id=row.id,
            source_id=row.source_id,
            source_name=row.source_name,
            expected_amount=float(row.expected_amount),
            received_amount=float(row.received_amount),
        )
        for row in income_rows
    ]
    return BudgetMonthResponse(
        id=month.id, year=month.year, month=month.month, categories=categories, income=income
    )


@router.get("/{home_id}/budget", response_model=BudgetProfileResponse)
async def get_budget(
    home_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BudgetProfileResponse:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    await db.commit()
    return _profile_response(profile)


@router.get("/{home_id}/budget/settings", response_model=BudgetProfileResponse)
async def get_budget_settings(
    home_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BudgetProfileResponse:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    await db.commit()
    return _profile_response(profile)


@router.put("/{home_id}/budget/settings", response_model=BudgetProfileResponse)
async def update_budget_settings(
    home_id: uuid.UUID,
    body: BudgetSettingsUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BudgetProfileResponse:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    profile.currency = body.currency.upper()
    profile.month_start_day = body.month_start_day
    profile.default_view = body.default_view
    audit(
        db,
        request,
        "budget.settings.updated",
        auth.user.id,
        target_type="budget_profile",
        target_id=profile.id,
        metadata={"currency": profile.currency, "month_start_day": profile.month_start_day},
    )
    await db.commit()
    return _profile_response(profile)


@router.get("/{home_id}/budget/categories", response_model=list[BudgetCategoryResponse])
async def list_categories(
    home_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[BudgetCategoryResponse]:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    rows = (
        await db.scalars(
            select(BudgetCategory)
            .where(BudgetCategory.profile_id == profile.id, BudgetCategory.archived_at.is_(None))
            .order_by(BudgetCategory.sort_order, BudgetCategory.name)
        )
    ).all()
    return [BudgetCategoryResponse(id=row.id, name=row.name, sort_order=row.sort_order, archived=False) for row in rows]


@router.post("/{home_id}/budget/categories", response_model=BudgetCategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    home_id: uuid.UUID,
    body: BudgetCategoryCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BudgetCategoryResponse:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    row = BudgetCategory(profile_id=profile.id, name=body.name.strip(), sort_order=body.sort_order)
    db.add(row)
    await db.flush()
    if body.year is not None and body.month is not None:
        month_row = await db.scalar(
            select(BudgetMonth).where(
                BudgetMonth.profile_id == profile.id,
                BudgetMonth.year == body.year,
                BudgetMonth.month == body.month,
                BudgetMonth.archived_at.is_(None),
            )
        )
        if month_row is None:
            month_row = await _create_month_snapshot(
                db, profile, body.year, body.month, request, auth.user.id
            )
        existing_membership = await db.scalar(
            select(BudgetMonthCategory).where(
                BudgetMonthCategory.month_id == month_row.id,
                BudgetMonthCategory.category_id == row.id,
            )
        )
        if existing_membership is None:
            db.add(
                BudgetMonthCategory(
                    month_id=month_row.id,
                    category_id=row.id,
                    category_name=row.name,
                )
            )
    audit(db, request, "budget.category.created", auth.user.id, target_type="budget_category", target_id=row.id)
    await db.commit()
    return BudgetCategoryResponse(id=row.id, name=row.name, sort_order=row.sort_order, archived=False)


@router.put("/{home_id}/budget/categories/{category_id}", response_model=BudgetCategoryResponse)
async def update_category(
    home_id: uuid.UUID,
    category_id: uuid.UUID,
    body: BudgetCategoryUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BudgetCategoryResponse:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    row = await db.scalar(select(BudgetCategory).where(BudgetCategory.id == category_id, BudgetCategory.profile_id == profile.id, BudgetCategory.archived_at.is_(None)))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget category not found")
    row.name = body.name.strip()
    row.sort_order = body.sort_order
    months = (await db.scalars(select(BudgetMonth).where(BudgetMonth.profile_id == profile.id, BudgetMonth.archived_at.is_(None)))).all()
    for month in months:
        if _is_current_or_future_month(month.year, month.month):
            membership = await db.scalar(select(BudgetMonthCategory).where(BudgetMonthCategory.month_id == month.id, BudgetMonthCategory.category_id == row.id))
            if membership is not None:
                membership.category_name = row.name
    audit(db, request, "budget.category.updated", auth.user.id, target_type="budget_category", target_id=row.id)
    await db.commit()
    return BudgetCategoryResponse(id=row.id, name=row.name, sort_order=row.sort_order, archived=False)


@router.delete("/{home_id}/budget/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    home_id: uuid.UUID,
    category_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    row = await db.scalar(select(BudgetCategory).where(BudgetCategory.id == category_id, BudgetCategory.profile_id == profile.id, BudgetCategory.archived_at.is_(None)))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget category not found")
    months = (await db.scalars(select(BudgetMonth).where(BudgetMonth.profile_id == profile.id, BudgetMonth.archived_at.is_(None)))).all()
    current_future_ids = [month.id for month in months if _is_current_or_future_month(month.year, month.month)]
    if current_future_ids:
        await db.execute(delete(BudgetMonthCategory).where(BudgetMonthCategory.category_id == row.id, BudgetMonthCategory.month_id.in_(current_future_ids)))
    row.archived_at = datetime.now(UTC)
    audit(db, request, "budget.category.archived", auth.user.id, target_type="budget_category", target_id=row.id)
    await db.commit()


@router.get("/{home_id}/budget/items", response_model=list[BudgetItemResponse])
async def list_budget_items(
    home_id: uuid.UUID,
    category_id: uuid.UUID | None = Query(default=None),
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[BudgetItemResponse]:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    query = select(BudgetItem).where(
        BudgetItem.profile_id == profile.id,
        BudgetItem.archived_at.is_(None),
    ).order_by(BudgetItem.name)
    if category_id is not None:
        query = query.where(BudgetItem.category_id == category_id)
    return [_item_response(row) for row in (await db.scalars(query)).all()]


@router.post("/{home_id}/budget/items", response_model=BudgetItemResponse, status_code=status.HTTP_201_CREATED)
async def create_budget_item(
    home_id: uuid.UUID,
    body: BudgetItemCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BudgetItemResponse:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    category = await db.scalar(select(BudgetCategory).where(
        BudgetCategory.id == body.category_id,
        BudgetCategory.profile_id == profile.id,
        BudgetCategory.archived_at.is_(None),
    ))
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget category not found")
    row = BudgetItem(
        profile_id=profile.id,
        category_id=category.id,
        name=body.name.strip(),
        item_type=body.item_type,
        default_amount=Decimal(str(body.default_amount)),
        recurring=body.recurring,
        starts_on=body.starts_on,
    )
    db.add(row)
    await db.flush()
    target = (body.year, body.month) if body.year is not None else (datetime.now(UTC).year, datetime.now(UTC).month)
    month = await db.scalar(select(BudgetMonth).where(
        BudgetMonth.profile_id == profile.id,
        BudgetMonth.year == target[0],
        BudgetMonth.month == target[1],
        BudgetMonth.archived_at.is_(None),
    ))
    if month is None:
        month = await _create_month_snapshot(db, profile, target[0], target[1], request, auth.user.id)
    db.add(BudgetMonthItem(
        month_id=month.id,
        budget_item_id=row.id,
        category_id=category.id,
        name_snapshot=row.name,
        item_type_snapshot=row.item_type,
        planned_amount=row.default_amount,
    ))
    await db.flush()
    await _sync_category_planned_compatibility(db, month, category.id)
    audit(db, request, "budget.item.created", auth.user.id, target_type="budget_item", target_id=row.id)
    await db.commit()
    return _item_response(row)


@router.put("/{home_id}/budget/items/{item_id}", response_model=BudgetItemResponse)
async def update_budget_item(
    home_id: uuid.UUID,
    item_id: uuid.UUID,
    body: BudgetItemUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BudgetItemResponse:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    row = await db.scalar(select(BudgetItem).where(
        BudgetItem.id == item_id,
        BudgetItem.profile_id == profile.id,
        BudgetItem.archived_at.is_(None),
    ))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget item not found")
    row.name = body.name.strip()
    row.default_amount = Decimal(str(body.default_amount))
    row.recurring = body.recurring
    row.starts_on = body.starts_on
    if body.year is not None and body.month is not None:
        if not _is_current_or_future_month(body.year, body.month):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Historical month plans cannot be changed")
        month = await _month_for_owner(db, profile.id, body.year, body.month)
        snapshot = await db.scalar(select(BudgetMonthItem).where(
            BudgetMonthItem.month_id == month.id,
            BudgetMonthItem.budget_item_id == row.id,
            BudgetMonthItem.archived_at.is_(None),
        ))
        if snapshot is None:
            snapshot = BudgetMonthItem(
                month_id=month.id,
                budget_item_id=row.id,
                category_id=row.category_id,
                name_snapshot=row.name,
                item_type_snapshot=row.item_type,
                planned_amount=Decimal(str(body.planned_amount if body.planned_amount is not None else body.default_amount)),
            )
            db.add(snapshot)
        else:
            snapshot.name_snapshot = row.name
            if body.planned_amount is not None:
                snapshot.planned_amount = Decimal(str(body.planned_amount))
        await db.flush()
        await _sync_category_planned_compatibility(db, month, row.category_id)
    audit(db, request, "budget.item.updated", auth.user.id, target_type="budget_item", target_id=row.id)
    await db.commit()
    return _item_response(row)


@router.delete("/{home_id}/budget/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_budget_item(
    home_id: uuid.UUID,
    item_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    row = await db.scalar(select(BudgetItem).where(
        BudgetItem.id == item_id,
        BudgetItem.profile_id == profile.id,
        BudgetItem.archived_at.is_(None),
    ))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget item not found")
    row.archived_at = datetime.now(UTC)
    months = (await db.scalars(select(BudgetMonth).where(
        BudgetMonth.profile_id == profile.id,
        BudgetMonth.archived_at.is_(None),
    ))).all()
    for month in months:
        if _is_current_or_future_month(month.year, month.month):
            snapshot = await db.scalar(select(BudgetMonthItem).where(
                BudgetMonthItem.month_id == month.id,
                BudgetMonthItem.budget_item_id == row.id,
                BudgetMonthItem.archived_at.is_(None),
            ))
            if snapshot is not None:
                snapshot.archived_at = datetime.now(UTC)
                await _sync_category_planned_compatibility(db, month, row.category_id)
    audit(db, request, "budget.item.archived", auth.user.id, target_type="budget_item", target_id=row.id)
    await db.commit()


@router.get("/{home_id}/budget/income-sources", response_model=list[BudgetIncomeSourceResponse])
async def list_income_sources(
    home_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[BudgetIncomeSourceResponse]:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    rows = (
        await db.scalars(
            select(BudgetIncomeSource)
            .where(BudgetIncomeSource.profile_id == profile.id, BudgetIncomeSource.archived_at.is_(None))
            .order_by(BudgetIncomeSource.sort_order, BudgetIncomeSource.name)
        )
    ).all()
    return [
        BudgetIncomeSourceResponse(id=row.id, name=row.name, sort_order=row.sort_order, archived=False)
        for row in rows
    ]


@router.post("/{home_id}/budget/income-sources", response_model=BudgetIncomeSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_income_source(
    home_id: uuid.UUID,
    body: BudgetIncomeSourceCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BudgetIncomeSourceResponse:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    name = body.name.strip()
    row = BudgetIncomeSource(profile_id=profile.id, name=name, sort_order=body.sort_order)
    db.add(row)
    try:
        await db.flush()
        if body.year is not None and body.month is not None:
            month_row = await db.scalar(
                select(BudgetMonth).where(
                    BudgetMonth.profile_id == profile.id,
                    BudgetMonth.year == body.year,
                    BudgetMonth.month == body.month,
                    BudgetMonth.archived_at.is_(None),
                )
            )
            if month_row is None:
                month_row = await _create_month_snapshot(
                    db, profile, body.year, body.month, request, auth.user.id
                )
            await _reconcile_month_income(db, profile.id, month_row, request, auth.user.id)
        audit(db, request, "budget.income_source.created", auth.user.id, target_type="budget_income_source", target_id=row.id)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f'Income source already exists. You already have an income source called “{name}”. You can edit the existing one instead.',
        ) from None
    return BudgetIncomeSourceResponse(id=row.id, name=row.name, sort_order=row.sort_order, archived=False)


@router.put("/{home_id}/budget/income-sources/{source_id}", response_model=BudgetIncomeSourceResponse)
async def update_income_source(
    home_id: uuid.UUID,
    source_id: uuid.UUID,
    body: BudgetIncomeSourceUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BudgetIncomeSourceResponse:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    row = await db.scalar(
        select(BudgetIncomeSource).where(
            BudgetIncomeSource.id == source_id,
            BudgetIncomeSource.profile_id == profile.id,
            BudgetIncomeSource.archived_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Income source not found")
    name = body.name.strip()
    row.name = name
    row.sort_order = body.sort_order
    current_future = (
        await db.scalars(
            select(BudgetMonth).where(
                BudgetMonth.profile_id == profile.id,
                BudgetMonth.archived_at.is_(None),
            )
        )
    ).all()
    try:
        for month in current_future:
            if _is_current_or_future_month(month.year, month.month):
                membership = await db.scalar(
                    select(BudgetMonthIncome).where(
                        BudgetMonthIncome.month_id == month.id,
                        BudgetMonthIncome.source_id == row.id,
                    )
                )
                if membership is not None:
                    membership.source_name = name
        audit(db, request, "budget.income_source.updated", auth.user.id, target_type="budget_income_source", target_id=row.id)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f'Income source already exists. You already have an income source called “{name}”. You can edit the existing one instead.',
        ) from None
    return BudgetIncomeSourceResponse(id=row.id, name=row.name, sort_order=row.sort_order, archived=False)


@router.delete("/{home_id}/budget/income-sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_income_source(
    home_id: uuid.UUID,
    source_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    row = await db.scalar(
        select(BudgetIncomeSource).where(
            BudgetIncomeSource.id == source_id,
            BudgetIncomeSource.profile_id == profile.id,
            BudgetIncomeSource.archived_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Income source not found")
    months = (
        await db.scalars(
            select(BudgetMonth).where(
                BudgetMonth.profile_id == profile.id,
                BudgetMonth.archived_at.is_(None),
            )
        )
    ).all()
    current_future_ids = [month.id for month in months if _is_current_or_future_month(month.year, month.month)]
    if current_future_ids:
        await db.execute(
            delete(BudgetMonthIncome).where(
                BudgetMonthIncome.source_id == row.id,
                BudgetMonthIncome.month_id.in_(current_future_ids),
            )
        )
    row.archived_at = datetime.now(UTC)
    audit(db, request, "budget.income_source.archived", auth.user.id, target_type="budget_income_source", target_id=row.id)
    await db.commit()


@router.post("/{home_id}/budget/months/{year}/{month}", response_model=BudgetMonthResponse, status_code=status.HTTP_201_CREATED)
async def create_month(
    home_id: uuid.UUID,
    year: int,
    month: int,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BudgetMonthResponse:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    if not 1 <= month <= 12:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Month must be between 1 and 12")
    existing = await db.scalar(
        select(BudgetMonth).where(BudgetMonth.profile_id == profile.id, BudgetMonth.year == year, BudgetMonth.month == month)
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That budget month already exists")
    row = await _create_month_snapshot(db, profile, year, month, request, auth.user.id)
    await db.commit()
    return await _month_response(db, row)


@router.post("/{home_id}/budget/months/{year}/{month}/copy", response_model=BudgetMonthResponse)
async def copy_month(
    home_id: uuid.UUID,
    year: int,
    month: int,
    body: BudgetMonthCopyRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BudgetMonthResponse:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    if not _is_current_or_future_month(year, month):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Historical month plans cannot be created")
    target = await db.scalar(select(BudgetMonth).where(
        BudgetMonth.profile_id == profile.id,
        BudgetMonth.year == year,
        BudgetMonth.month == month,
        BudgetMonth.archived_at.is_(None),
    ))
    if target is None:
        target = await _create_month_snapshot(
            db, profile, year, month, request, auth.user.id, copy_income=body.copy_income_sources
        )
    await _reconcile_month_items(db, profile.id, target, include_variables=False)
    if body.copy_variable_items:
        previous_date = date(year, month, 1) - timedelta(days=1)
        source_month = await db.scalar(select(BudgetMonth).where(
            BudgetMonth.profile_id == profile.id,
            BudgetMonth.year == previous_date.year,
            BudgetMonth.month == previous_date.month,
            BudgetMonth.archived_at.is_(None),
        ))
        source_items = []
        if source_month is not None:
            source_items = (await db.scalars(select(BudgetMonthItem).where(
                BudgetMonthItem.month_id == source_month.id,
                BudgetMonthItem.item_type_snapshot == BudgetItemType.variable,
                BudgetMonthItem.archived_at.is_(None),
            ))).all()
        if not source_items:
            source_items = (await db.scalars(select(BudgetItem).where(
                BudgetItem.profile_id == profile.id,
                BudgetItem.item_type == BudgetItemType.variable,
                BudgetItem.archived_at.is_(None),
            ))).all()
        for source in source_items:
            item_id = source.budget_item_id if isinstance(source, BudgetMonthItem) else source.id
            exists = await db.scalar(select(BudgetMonthItem).where(
                BudgetMonthItem.month_id == target.id,
                BudgetMonthItem.budget_item_id == item_id,
                BudgetMonthItem.archived_at.is_(None),
            ))
            if exists is not None:
                continue
            if isinstance(source, BudgetMonthItem):
                if source.budget_item_id is None:
                    continue
                item = await db.get(BudgetItem, source.budget_item_id)
                if item is None or item.archived_at is not None:
                    continue
                name, amount, category_id = source.name_snapshot, source.planned_amount, source.category_id
            else:
                item = source
                name, amount, category_id = item.name, item.default_amount, item.category_id
            db.add(BudgetMonthItem(
                month_id=target.id,
                budget_item_id=item.id,
                category_id=category_id,
                name_snapshot=name,
                item_type_snapshot=BudgetItemType.variable,
                planned_amount=amount,
            ))
            await db.flush()
            await _sync_category_planned_compatibility(db, target, category_id)
    audit(db, request, "budget.month.copied", auth.user.id, target_type="budget_month", target_id=target.id)
    await db.commit()
    return await _month_response(db, target)


@router.get("/{home_id}/budget/months/{year}/{month}", response_model=BudgetMonthResponse)
async def get_month(
    home_id: uuid.UUID,
    year: int,
    month: int,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BudgetMonthResponse:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    month_row = await _month_for_owner(db, profile.id, year, month)
    await _reconcile_month_categories(db, profile.id, month_row, request, auth.user.id)
    await _reconcile_month_income(db, profile.id, month_row, request, auth.user.id)
    await _reconcile_month_items(db, profile.id, month_row)
    await db.commit()
    return await _month_response(db, month_row)


@router.post("/{home_id}/budget/entries", response_model=BudgetSpendingEntryResponse, status_code=status.HTTP_201_CREATED)
async def create_entry(
    home_id: uuid.UUID,
    body: BudgetSpendingEntryCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BudgetSpendingEntryResponse:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    category = await db.scalar(select(BudgetCategory).where(BudgetCategory.id == body.category_id, BudgetCategory.profile_id == profile.id, BudgetCategory.archived_at.is_(None)))
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget category not found")
    month = await db.scalar(select(BudgetMonth).where(BudgetMonth.profile_id == profile.id, BudgetMonth.year == body.spent_on.year, BudgetMonth.month == body.spent_on.month, BudgetMonth.archived_at.is_(None)))
    if month is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget month not found")
    await _reconcile_month_categories(db, profile.id, month, request, auth.user.id)
    month_category = await db.scalar(select(BudgetMonthCategory).where(BudgetMonthCategory.month_id == month.id, BudgetMonthCategory.category_id == category.id))
    if month_category is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Category is not part of that historical month")
    row = BudgetSpendingEntry(
        month_category_id=month_category.id,
        description=body.description.strip(),
        amount=Decimal(str(body.amount)),
        spent_on=body.spent_on,
        note=body.note.strip() if body.note else None,
    )
    db.add(row)
    await db.flush()
    audit(db, request, "budget.entry.created", auth.user.id, target_type="budget_entry", target_id=row.id)
    await db.commit()
    return _entry_response(row, category.id)


@router.get("/{home_id}/budget/entries", response_model=list[BudgetSpendingEntryResponse])
async def list_entries(
    home_id: uuid.UUID,
    year: int | None = Query(default=None),
    month: int | None = Query(default=None, ge=1, le=12),
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[BudgetSpendingEntryResponse]:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    query = (
        select(BudgetSpendingEntry, BudgetMonthCategory.category_id)
        .join(BudgetMonthCategory, BudgetMonthCategory.id == BudgetSpendingEntry.month_category_id)
        .join(BudgetMonth, BudgetMonth.id == BudgetMonthCategory.month_id)
        .where(BudgetMonth.profile_id == profile.id, BudgetSpendingEntry.archived_at.is_(None))
        .order_by(BudgetSpendingEntry.spent_on.desc(), BudgetSpendingEntry.created_at.desc())
    )
    if year is not None:
        query = query.where(BudgetMonth.year == year)
    if month is not None:
        query = query.where(BudgetMonth.month == month)
    rows = (await db.execute(query)).all()
    return [_entry_response(row, category_id) for row, category_id in rows]


async def _entry_for_owner(
    db: AsyncSession, profile_id: uuid.UUID, entry_id: uuid.UUID
) -> tuple[BudgetSpendingEntry, BudgetMonthCategory, BudgetMonth]:
    row = await db.execute(
        select(BudgetSpendingEntry, BudgetMonthCategory, BudgetMonth)
        .join(BudgetMonthCategory, BudgetMonthCategory.id == BudgetSpendingEntry.month_category_id)
        .join(BudgetMonth, BudgetMonth.id == BudgetMonthCategory.month_id)
        .where(
            BudgetSpendingEntry.id == entry_id,
            BudgetSpendingEntry.archived_at.is_(None),
            BudgetMonth.profile_id == profile_id,
            BudgetMonth.archived_at.is_(None),
        )
    )
    result = row.one_or_none()
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Spending entry not found")
    return result


@router.get("/{home_id}/budget/entries/{entry_id}", response_model=BudgetSpendingEntryResponse)
async def get_entry(
    home_id: uuid.UUID,
    entry_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BudgetSpendingEntryResponse:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    entry, category, _ = await _entry_for_owner(db, profile.id, entry_id)
    return _entry_response(entry, category.category_id)


@router.put("/{home_id}/budget/entries/{entry_id}", response_model=BudgetSpendingEntryResponse)
async def update_entry(
    home_id: uuid.UUID,
    entry_id: uuid.UUID,
    body: BudgetSpendingEntryUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BudgetSpendingEntryResponse:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    entry, _, _ = await _entry_for_owner(db, profile.id, entry_id)
    target_category = await db.scalar(
        select(BudgetCategory).where(
            BudgetCategory.id == body.category_id,
            BudgetCategory.profile_id == profile.id,
            BudgetCategory.archived_at.is_(None),
        )
    )
    if target_category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget category not found")
    target_month = await db.scalar(
        select(BudgetMonth).where(
            BudgetMonth.profile_id == profile.id,
            BudgetMonth.year == body.spent_on.year,
            BudgetMonth.month == body.spent_on.month,
            BudgetMonth.archived_at.is_(None),
        )
    )
    if target_month is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget month not found")
    target_month_category = await db.scalar(
        select(BudgetMonthCategory).where(
            BudgetMonthCategory.month_id == target_month.id,
            BudgetMonthCategory.category_id == target_category.id,
        )
    )
    if target_month_category is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Category is not part of that historical month")
    entry.month_category_id = target_month_category.id
    entry.description = body.description.strip()
    entry.amount = Decimal(str(body.amount))
    entry.spent_on = body.spent_on
    entry.note = body.note.strip() if body.note else None
    audit(db, request, "budget.entry.updated", auth.user.id, target_type="budget_entry", target_id=entry.id)
    await db.commit()
    return _entry_response(entry, target_category.id)


@router.delete("/{home_id}/budget/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    home_id: uuid.UUID,
    entry_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    entry, _, _ = await _entry_for_owner(db, profile.id, entry_id)
    entry.archived_at = datetime.now(UTC)
    audit(db, request, "budget.entry.deleted", auth.user.id, target_type="budget_entry", target_id=entry.id)
    await db.commit()


@router.put("/{home_id}/budget/months/{year}/{month}/categories/{category_id}/actual", response_model=BudgetMonthCategoryResponse)
async def update_actual(
    home_id: uuid.UUID,
    year: int,
    month: int,
    category_id: uuid.UUID,
    body: BudgetActualUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BudgetMonthCategoryResponse:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    month_row = await _month_for_owner(db, profile.id, year, month)
    await _reconcile_month_categories(db, profile.id, month_row, request, auth.user.id)
    row = await db.scalar(select(BudgetMonthCategory).where(BudgetMonthCategory.month_id == month_row.id, BudgetMonthCategory.category_id == category_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget category not found for that month")
    row.actual_source = body.source
    row.manual_actual = Decimal(str(body.manual_actual)) if body.manual_actual is not None else None
    audit(db, request, "budget.actual_source.updated", auth.user.id, target_type="budget_month_category", target_id=row.id, metadata={"source": body.source.value})
    await db.commit()
    response = await _month_response(db, month_row)
    return next(item for item in response.categories if item.category_id == category_id)


@router.put("/{home_id}/budget/months/{year}/{month}/categories/{category_id}/plan", response_model=BudgetMonthCategoryResponse)
async def update_planned_amount(
    home_id: uuid.UUID,
    year: int,
    month: int,
    category_id: uuid.UUID,
    body: BudgetPlanAmountUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BudgetMonthCategoryResponse:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    month_row = await _month_for_owner(db, profile.id, year, month)
    await _reconcile_month_categories(db, profile.id, month_row, request, auth.user.id)
    row = await db.scalar(
        select(BudgetMonthCategory).where(
            BudgetMonthCategory.month_id == month_row.id,
            BudgetMonthCategory.category_id == category_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget category not found for that month")
    row.planned_amount = Decimal(str(body.planned_amount))
    audit(db, request, "budget.plan_amount.updated", auth.user.id, target_type="budget_month_category", target_id=row.id)
    await db.commit()
    response = await _month_response(db, month_row)
    return next(item for item in response.categories if item.category_id == category_id)


@router.put("/{home_id}/budget/months/{year}/{month}/categories/{category_id}/note", response_model=BudgetMonthCategoryResponse)
async def update_category_note(
    home_id: uuid.UUID,
    year: int,
    month: int,
    category_id: uuid.UUID,
    body: BudgetCategoryNoteUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BudgetMonthCategoryResponse:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    month_row = await _month_for_owner(db, profile.id, year, month)
    await _reconcile_month_categories(db, profile.id, month_row, request, auth.user.id)
    row = await db.scalar(select(BudgetMonthCategory).where(BudgetMonthCategory.month_id == month_row.id, BudgetMonthCategory.category_id == category_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget category not found for that month")
    row.note = body.note.strip() if body.note else None
    audit(db, request, "budget.category.note.updated", auth.user.id, target_type="budget_month_category", target_id=row.id)
    await db.commit()
    response = await _month_response(db, month_row)
    return next(item for item in response.categories if item.category_id == category_id)


@router.put("/{home_id}/budget/months/{year}/{month}/income/{source_id}", response_model=BudgetMonthIncomeResponse)
async def update_month_income(
    home_id: uuid.UUID,
    year: int,
    month: int,
    source_id: uuid.UUID,
    body: BudgetMonthIncomeUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BudgetMonthIncomeResponse:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    month_row = await _month_for_owner(db, profile.id, year, month)
    row = await db.scalar(
        select(BudgetMonthIncome).where(
            BudgetMonthIncome.month_id == month_row.id,
            BudgetMonthIncome.source_id == source_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Income source not found for that month")
    row.expected_amount = Decimal(str(body.expected_amount))
    row.received_amount = Decimal(str(body.received_amount))
    audit(db, request, "budget.month_income.updated", auth.user.id, target_type="budget_month_income", target_id=row.id)
    await db.commit()
    return BudgetMonthIncomeResponse(
        id=row.id,
        source_id=row.source_id,
        source_name=row.source_name,
        expected_amount=float(row.expected_amount),
        received_amount=float(row.received_amount),
    )


@router.get("/{home_id}/budget/shares", response_model=list[BudgetPartnerShareResponse])
async def list_shares(
    home_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[BudgetPartnerShareResponse]:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    rows = (await db.scalars(select(BudgetPartnerShare).where(BudgetPartnerShare.profile_id == profile.id))).all()
    return [BudgetPartnerShareResponse(id=row.id, partner_user_id=row.partner_user_id, level=row.level, active=row.revoked_at is None, category_ids=row.category_ids) for row in rows]


@router.put("/{home_id}/budget/shares/{partner_user_id}", response_model=BudgetPartnerShareResponse)
async def set_share(
    home_id: uuid.UUID,
    partner_user_id: uuid.UUID,
    body: BudgetPartnerShareCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BudgetPartnerShareResponse:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    if partner_user_id == auth.user.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A Budget cannot be shared with its owner")
    partner = await db.scalar(select(Membership).where(Membership.group_id == home_id, Membership.user_id == partner_user_id, Membership.removed_at.is_(None)))
    if partner is None or partner.relationship == HouseholdRelationship.child:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Partner not found")
    category_ids: list[str] | None = None
    if body.level == BudgetSharingLevel.categories:
        requested = {str(category_id) for category_id in (body.category_ids or [])}
        valid = set(
            str(category_id)
            for category_id in (
                await db.scalars(
                    select(BudgetCategory.id).where(
                        BudgetCategory.profile_id == profile.id,
                        BudgetCategory.archived_at.is_(None),
                    )
                )
            ).all()
        )
        if not requested.issubset(valid):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "One or more shared categories are invalid")
        category_ids = sorted(requested)
    row = await db.scalar(select(BudgetPartnerShare).where(BudgetPartnerShare.profile_id == profile.id, BudgetPartnerShare.partner_user_id == partner_user_id))
    if row is None:
        row = BudgetPartnerShare(profile_id=profile.id, partner_user_id=partner_user_id, level=body.level, category_ids=category_ids)
        db.add(row)
    else:
        row.level = body.level
        row.category_ids = category_ids
        row.revoked_at = None
    audit(db, request, "budget.partner_sharing.updated", auth.user.id, target_type="budget_partner_share", target_id=row.id, metadata={"level": body.level.value})
    await db.commit()
    return BudgetPartnerShareResponse(id=row.id, partner_user_id=row.partner_user_id, level=row.level, active=True, category_ids=row.category_ids)


@router.delete("/{home_id}/budget/shares/{partner_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share(
    home_id: uuid.UUID,
    partner_user_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _member_and_feature(home_id, auth, db)
    profile = await _profile(db, auth.user.id)
    row = await db.scalar(select(BudgetPartnerShare).where(BudgetPartnerShare.profile_id == profile.id, BudgetPartnerShare.partner_user_id == partner_user_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Share not found")
    row.revoked_at = datetime.now(UTC)
    audit(db, request, "budget.partner_sharing.revoked", auth.user.id, target_type="budget_partner_share", target_id=row.id)
    await db.commit()


@router.get("/{home_id}/budget/shared-with-me", response_model=list[BudgetIncomingShareResponse])
async def list_incoming_shares(
    home_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[BudgetIncomingShareResponse]:
    await _member_and_feature(home_id, auth, db)
    viewer = await db.scalar(
        select(Membership).where(
            Membership.group_id == home_id,
            Membership.user_id == auth.user.id,
            Membership.removed_at.is_(None),
        )
    )
    if viewer is None or viewer.relationship == HouseholdRelationship.child:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget not found")
    rows = (
        await db.execute(
            select(BudgetPartnerShare, BudgetProfile, User)
            .join(BudgetProfile, BudgetProfile.id == BudgetPartnerShare.profile_id)
            .join(User, User.id == BudgetProfile.owner_user_id)
            .join(
                Membership,
                (Membership.user_id == BudgetProfile.owner_user_id)
                & (Membership.group_id == home_id),
            )
            .where(
                BudgetPartnerShare.partner_user_id == auth.user.id,
                BudgetPartnerShare.revoked_at.is_(None),
                BudgetProfile.archived_at.is_(None),
                Membership.removed_at.is_(None),
                Membership.relationship != HouseholdRelationship.child,
                User.is_active.is_(True),
            )
            .order_by(User.display_name, BudgetPartnerShare.created_at)
        )
    ).all()
    return [
        BudgetIncomingShareResponse(
            home_id=home_id,
            owner_user_id=profile.owner_user_id,
            owner_display_name=user.display_name,
            level=share.level,
        )
        for share, profile, user in rows
    ]


@router.get("/{home_id}/budget/shared/{owner_user_id}/months/{year}/{month}", response_model=BudgetMonthResponse)
async def get_shared_month(
    home_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    year: int,
    month: int,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> BudgetMonthResponse:
    await _member_and_feature(home_id, auth, db)
    if owner_user_id == auth.user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Use the owner Budget endpoint")
    viewer = await db.scalar(select(Membership).where(Membership.group_id == home_id, Membership.user_id == auth.user.id, Membership.removed_at.is_(None)))
    if viewer is None or viewer.relationship == HouseholdRelationship.child:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget not found")
    profile = await db.scalar(select(BudgetProfile).where(BudgetProfile.owner_user_id == owner_user_id, BudgetProfile.archived_at.is_(None)))
    share = None if profile is None else await db.scalar(select(BudgetPartnerShare).where(BudgetPartnerShare.profile_id == profile.id, BudgetPartnerShare.partner_user_id == auth.user.id, BudgetPartnerShare.revoked_at.is_(None)))
    if profile is None or share is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget not found")
    month_row = await _month_for_owner(db, profile.id, year, month)
    response = await _month_response(db, month_row, include_categories=share.level != BudgetSharingLevel.summary)
    if share.level == BudgetSharingLevel.categories and share.category_ids is not None:
        allowed = set(share.category_ids)
        response.categories = [category for category in response.categories if str(category.category_id) in allowed]
    if share.level != BudgetSharingLevel.full:
        for category in response.categories:
            category.items = []
            category.fixed_planned_amount = 0
            category.variable_planned_amount = 0
    return response
