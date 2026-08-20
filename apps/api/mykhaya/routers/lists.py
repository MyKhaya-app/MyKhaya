"""Household Lists — MyKhaya's one shared-list primitive (groceries,
packing, to-dos, and the destination for Meal Plans' "Add ingredients to
list"; see mykhaya.routers.meal_plans.add_ingredients_to_list). Deliberately
minimal: a list is a name plus an ordered set of plain-text items with a
checked-off flag. No due dates, no assignment, no categories — those are
future-iteration territory, not this one.

Reuses FeatureKey.shopping's existing (previously unreleased) module slot
and the pre-declared "lists.enabled" entitlement in
mykhaya.entitlements.PLAN_DEFINITIONS rather than adding a new feature key
or entitlement — both already existed as commercial data ahead of the
module actually shipping.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context
from mykhaya.entitlements import require_entitlement
from mykhaya.features import require_feature
from mykhaya.household_permissions import Capability, require_capability
from mykhaya.models import FeatureKey, HouseholdList, HouseholdListItem
from mykhaya.schemas import (
    ListCreate,
    ListDetailResponse,
    ListItemInput,
    ListItemResponse,
    ListItemToggleRequest,
    ListListResponse,
    ListResponse,
)


async def require_lists_feature(home_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    await require_feature(db, FeatureKey.shopping, home_id)


router = APIRouter(prefix="/homes", tags=["lists"], dependencies=[Depends(require_lists_feature)])


async def _get_active_list(
    db: AsyncSession, home_id: uuid.UUID, list_id: uuid.UUID
) -> HouseholdList:
    row = await db.scalar(
        select(HouseholdList).where(
            HouseholdList.id == list_id,
            HouseholdList.group_id == home_id,
            HouseholdList.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That list could not be found")
    return row


async def _item_count(db: AsyncSession, list_id: uuid.UUID) -> int:
    return int(
        await db.scalar(
            select(func.count()).select_from(HouseholdListItem).where(
                HouseholdListItem.list_id == list_id
            )
        )
        or 0
    )


def _list_response(row: HouseholdList, item_count: int) -> ListResponse:
    return ListResponse(
        id=row.id,
        name=row.name,
        item_count=item_count,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _list_items(db: AsyncSession, list_id: uuid.UUID) -> list[ListItemResponse]:
    rows = (
        await db.scalars(
            select(HouseholdListItem)
            .where(HouseholdListItem.list_id == list_id)
            .order_by(HouseholdListItem.position)
        )
    ).all()
    return [
        ListItemResponse(id=row.id, position=row.position, text=row.text, is_checked=row.is_checked)
        for row in rows
    ]


async def _detail_response(db: AsyncSession, row: HouseholdList) -> ListDetailResponse:
    return ListDetailResponse(
        id=row.id,
        name=row.name,
        items=await _list_items(db, row.id),
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/{home_id}/lists", response_model=ListDetailResponse, status_code=201)
async def create_list(
    home_id: uuid.UUID,
    body: ListCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ListDetailResponse:
    await require_capability(home_id, Capability.lists_manage, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")

    row = HouseholdList(
        group_id=home_id, name=" ".join(body.name.strip().split()), created_by=auth.user.id
    )
    db.add(row)
    await db.flush()
    audit(db, request, "lists.list.created", auth.user.id, home_id, "list", row.id)
    await db.commit()
    return await _detail_response(db, row)


@router.get("/{home_id}/lists", response_model=ListListResponse)
async def list_lists(
    home_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ListListResponse:
    await require_capability(home_id, Capability.lists_view, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")

    rows = (
        await db.scalars(
            select(HouseholdList)
            .where(HouseholdList.group_id == home_id, HouseholdList.deleted_at.is_(None))
            .order_by(HouseholdList.name)
        )
    ).all()
    # One count query for every list rather than N — a Home's list count is
    # small, and this keeps GET /lists to two queries total regardless.
    counts_by_list: dict[uuid.UUID, int] = {}
    if rows:
        count_rows = (
            await db.execute(
                select(HouseholdListItem.list_id, func.count())
                .where(HouseholdListItem.list_id.in_([row.id for row in rows]))
                .group_by(HouseholdListItem.list_id)
            )
        ).all()
        counts_by_list = {list_id: count for list_id, count in count_rows}
    return ListListResponse(
        items=[_list_response(row, counts_by_list.get(row.id, 0)) for row in rows]
    )


@router.get("/{home_id}/lists/{list_id}", response_model=ListDetailResponse)
async def get_list(
    home_id: uuid.UUID,
    list_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ListDetailResponse:
    await require_capability(home_id, Capability.lists_view, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")
    row = await _get_active_list(db, home_id, list_id)
    return await _detail_response(db, row)


@router.patch("/{home_id}/lists/{list_id}", response_model=ListDetailResponse)
async def rename_list(
    home_id: uuid.UUID,
    list_id: uuid.UUID,
    body: ListCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ListDetailResponse:
    await require_capability(home_id, Capability.lists_manage, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")
    row = await _get_active_list(db, home_id, list_id)
    row.name = " ".join(body.name.strip().split())
    audit(db, request, "lists.list.renamed", auth.user.id, home_id, "list", row.id)
    await db.commit()
    await db.refresh(row)
    return await _detail_response(db, row)


@router.delete("/{home_id}/lists/{list_id}", status_code=204)
async def delete_list(
    home_id: uuid.UUID,
    list_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_capability(home_id, Capability.lists_manage, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")
    row = await _get_active_list(db, home_id, list_id)
    row.deleted_at = datetime.now(tz=row.created_at.tzinfo)
    audit(db, request, "lists.list.deleted", auth.user.id, home_id, "list", row.id)
    await db.commit()


@router.post("/{home_id}/lists/{list_id}/items", response_model=ListDetailResponse, status_code=201)
async def add_list_item(
    home_id: uuid.UUID,
    list_id: uuid.UUID,
    body: ListItemInput,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ListDetailResponse:
    await require_capability(home_id, Capability.lists_manage, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")
    row = await _get_active_list(db, home_id, list_id)
    next_position = await _item_count(db, row.id)
    db.add(
        HouseholdListItem(
            list_id=row.id,
            position=next_position,
            text=body.text.strip(),
            created_by=auth.user.id,
        )
    )
    audit(db, request, "lists.item.added", auth.user.id, home_id, "list", row.id)
    await db.commit()
    return await _detail_response(db, row)


@router.patch(
    "/{home_id}/lists/{list_id}/items/{item_id}", response_model=ListDetailResponse
)
async def toggle_list_item(
    home_id: uuid.UUID,
    list_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ListItemToggleRequest,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ListDetailResponse:
    await require_capability(home_id, Capability.lists_manage, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")
    row = await _get_active_list(db, home_id, list_id)
    item = await db.scalar(
        select(HouseholdListItem).where(
            HouseholdListItem.id == item_id, HouseholdListItem.list_id == row.id
        )
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That item could not be found")
    item.is_checked = body.is_checked
    await db.commit()
    return await _detail_response(db, row)


@router.delete("/{home_id}/lists/{list_id}/items/{item_id}", response_model=ListDetailResponse)
async def remove_list_item(
    home_id: uuid.UUID,
    list_id: uuid.UUID,
    item_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ListDetailResponse:
    await require_capability(home_id, Capability.lists_manage, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")
    row = await _get_active_list(db, home_id, list_id)
    await db.execute(
        delete(HouseholdListItem).where(
            HouseholdListItem.id == item_id, HouseholdListItem.list_id == row.id
        )
    )
    audit(db, request, "lists.item.removed", auth.user.id, home_id, "list", row.id)
    await db.commit()
    return await _detail_response(db, row)
