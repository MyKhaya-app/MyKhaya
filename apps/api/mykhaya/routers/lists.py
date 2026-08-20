"""Household Lists — MyKhaya's one shared-list primitive (groceries,
packing, DIY, school supplies, party/Christmas/holiday prep, and the
destination for Meal Plans' "Add ingredients to list"; see
mykhaya.routers.meal_plans.add_ingredients_to_list). A list is a name plus
an ordered set of items; an item is text plus an optional quantity, note
and member assignment, and a checked-off state with completion metadata.

Reuses FeatureKey.shopping's module slot and the "lists.enabled"
entitlement in mykhaya.entitlements.PLAN_DEFINITIONS, both already declared
ahead of the module shipping — see docs/architecture/lists.md.

Permissions: `lists_view`/`lists_manage`, the same two-capability shape
Meal Plans already uses (no finer split between "can create/delete a List"
and "can only touch its items" — both a Home Admin and a standard_partner
get full `lists_manage`, which already matches this ticket's own
"Recommended starting point" for those two relationships). A managed Child
gets neither capability by default, same deferral as Meal Plans.
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
from mykhaya.models import FeatureKey, HouseholdList, HouseholdListItem, Membership
from mykhaya.schemas import (
    ListCreate,
    ListDetailResponse,
    ListItemInput,
    ListItemReorderRequest,
    ListItemResponse,
    ListItemUpdate,
    ListListResponse,
    ListRenameRequest,
    ListResponse,
)


async def require_lists_feature(home_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    await require_feature(db, FeatureKey.shopping, home_id)


router = APIRouter(prefix="/homes", tags=["lists"], dependencies=[Depends(require_lists_feature)])


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _get_active_list(
    db: AsyncSession, home_id: uuid.UUID, list_id: uuid.UUID, *, for_update: bool = False
) -> HouseholdList:
    query = select(HouseholdList).where(
        HouseholdList.id == list_id,
        HouseholdList.group_id == home_id,
        HouseholdList.deleted_at.is_(None),
    )
    if for_update:
        query = query.with_for_update()
    row = await db.scalar(query)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That list could not be found")
    return row


async def _validate_member(db: AsyncSession, home_id: uuid.UUID, user_id: uuid.UUID) -> None:
    active = await db.scalar(
        select(Membership.user_id).where(
            Membership.group_id == home_id,
            Membership.user_id == user_id,
            Membership.removed_at.is_(None),
        )
    )
    if active is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That member is invalid")


async def _counts(db: AsyncSession, list_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int]]:
    """One grouped query -> {list_id: (total, remaining)} — the Lists
    overview never has to fetch every item row just to show "3 remaining of
    8"."""
    if not list_ids:
        return {}
    rows = (
        await db.execute(
            select(
                HouseholdListItem.list_id,
                func.count(),
                func.count().filter(HouseholdListItem.is_checked.is_(False)),
            )
            .where(HouseholdListItem.list_id.in_(list_ids))
            .group_by(HouseholdListItem.list_id)
        )
    ).all()
    return {list_id: (total, remaining) for list_id, total, remaining in rows}


def _list_response(row: HouseholdList, total: int, remaining: int) -> ListResponse:
    return ListResponse(
        id=row.id,
        name=row.name,
        icon=row.icon,
        item_count=total,
        remaining_count=remaining,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _list_items(db: AsyncSession, list_id: uuid.UUID) -> list[HouseholdListItem]:
    return list(
        (
            await db.scalars(
                select(HouseholdListItem)
                .where(HouseholdListItem.list_id == list_id)
                .order_by(HouseholdListItem.position)
            )
        ).all()
    )


def _item_response(row: HouseholdListItem) -> ListItemResponse:
    return ListItemResponse(
        id=row.id,
        position=row.position,
        text=row.text,
        quantity=row.quantity,
        note=row.note,
        assigned_member_id=row.assigned_member_id,
        is_checked=row.is_checked,
        completed_at=row.completed_at,
        completed_by=row.completed_by,
    )


async def _detail_response(db: AsyncSession, row: HouseholdList) -> ListDetailResponse:
    items = await _list_items(db, row.id)
    remaining = sum(1 for item in items if not item.is_checked)
    return ListDetailResponse(
        id=row.id,
        name=row.name,
        icon=row.icon,
        items=[_item_response(item) for item in items],
        item_count=len(items),
        remaining_count=remaining,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _next_position(db: AsyncSession, list_id: uuid.UUID) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(HouseholdListItem)
            .where(HouseholdListItem.list_id == list_id)
        )
        or 0
    )


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------


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
        group_id=home_id,
        name=" ".join(body.name.strip().split()),
        icon=body.icon,
        created_by=auth.user.id,
    )
    db.add(row)
    await db.flush()
    audit(db, request, "lists.list.created", auth.user.id, home_id, "list", row.id)
    await db.commit()
    return await _detail_response(db, row)


@router.get("/{home_id}/lists", response_model=ListListResponse)
async def list_lists(
    home_id: uuid.UUID,
    q: str | None = None,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ListListResponse:
    await require_capability(home_id, Capability.lists_view, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")

    filters = [HouseholdList.group_id == home_id, HouseholdList.deleted_at.is_(None)]
    if q:
        filters.append(HouseholdList.name.ilike(f"%{q.strip()}%"))
    rows = (
        # Most-recently-updated active list first — a list someone just
        # added/checked something on floats to the top, matching "recently
        # updated Lists first" rather than a fixed alphabetical order.
        await db.scalars(
            select(HouseholdList).where(*filters).order_by(HouseholdList.updated_at.desc())
        )
    ).all()
    counts = await _counts(db, [row.id for row in rows])
    return ListListResponse(
        items=[_list_response(row, *counts.get(row.id, (0, 0))) for row in rows]
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
    body: ListRenameRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ListDetailResponse:
    await require_capability(home_id, Capability.lists_manage, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")
    row = await _get_active_list(db, home_id, list_id, for_update=True)
    if row.updated_at != body.expected_updated_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "This list changed. Reload and try again.")
    row.name = " ".join(body.name.strip().split())
    row.icon = body.icon
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
    # Soft delete only — a deleted List simply stops resolving via
    # _get_active_list, so Meal Plans can never add ingredients into it
    # again (see add_ingredients_to_list, which looks the List up the same
    # way).
    row.deleted_at = datetime.now(tz=row.created_at.tzinfo)
    audit(db, request, "lists.list.deleted", auth.user.id, home_id, "list", row.id)
    await db.commit()


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


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
    if body.assigned_member_id is not None:
        await _validate_member(db, home_id, body.assigned_member_id)
    next_position = await _next_position(db, row.id)
    db.add(
        HouseholdListItem(
            list_id=row.id,
            position=next_position,
            text=body.text.strip(),
            quantity=body.quantity,
            note=body.note,
            assigned_member_id=body.assigned_member_id,
            created_by=auth.user.id,
        )
    )
    audit(db, request, "lists.item.added", auth.user.id, home_id, "list", row.id)
    await db.commit()
    return await _detail_response(db, row)


@router.patch("/{home_id}/lists/{list_id}/items/{item_id}", response_model=ListDetailResponse)
async def update_list_item(
    home_id: uuid.UUID,
    list_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ListItemUpdate,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ListDetailResponse:
    """One endpoint for both a quick checkbox toggle and a full edit — only
    the fields actually present in the request body are applied (see
    ListItemUpdate's docstring), so toggling a checkbox never has to resend
    the item's text/quantity/note just to leave them unchanged."""
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

    fields = body.model_fields_set
    if "assigned_member_id" in fields and body.assigned_member_id is not None:
        await _validate_member(db, home_id, body.assigned_member_id)
    if "text" in fields and body.text is not None:
        item.text = body.text.strip()
    if "quantity" in fields:
        item.quantity = body.quantity
    if "note" in fields:
        item.note = body.note
    if "assigned_member_id" in fields:
        item.assigned_member_id = body.assigned_member_id
    new_checked = body.is_checked
    if "is_checked" in fields and new_checked is not None and new_checked != item.is_checked:
        item.is_checked = new_checked
        if new_checked:
            item.completed_at = datetime.now(tz=item.created_at.tzinfo)
            item.completed_by = auth.user.id
        else:
            item.completed_at = None
            item.completed_by = None

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


@router.post("/{home_id}/lists/{list_id}/items/reorder", response_model=ListDetailResponse)
async def reorder_list_items(
    home_id: uuid.UUID,
    list_id: uuid.UUID,
    body: ListItemReorderRequest,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ListDetailResponse:
    """Backend order persistence for Lists V1 — see
    docs/architecture/lists.md "Reordering": touch drag-and-drop UI is
    deferred (no drag library exists in the codebase yet), but the ordering
    model itself is real, safe and ready for it. `item_ids` must be exactly
    the list's current active item ids (no missing, no foreign, no
    duplicate) — a stale client, or one racing another member's
    add/delete, gets a 409 rather than silently corrupting order."""
    await require_capability(home_id, Capability.lists_manage, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")
    row = await _get_active_list(db, home_id, list_id, for_update=True)
    items = await _list_items(db, row.id)
    current_ids = {item.id for item in items}
    requested_ids = body.item_ids
    if set(requested_ids) != current_ids or len(requested_ids) != len(items):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This list's items changed. Reload and try again.",
        )
    by_id = {item.id: item for item in items}
    for position, item_id in enumerate(requested_ids):
        by_id[item_id].position = position
    await db.commit()
    return await _detail_response(db, row)


@router.post("/{home_id}/lists/{list_id}/items/clear-completed", response_model=ListDetailResponse)
async def clear_completed_items(
    home_id: uuid.UUID,
    list_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ListDetailResponse:
    await require_capability(home_id, Capability.lists_manage, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")
    row = await _get_active_list(db, home_id, list_id)
    await db.execute(
        delete(HouseholdListItem).where(
            HouseholdListItem.list_id == row.id, HouseholdListItem.is_checked.is_(True)
        )
    )
    audit(db, request, "lists.items.cleared_completed", auth.user.id, home_id, "list", row.id)
    await db.commit()
    return await _detail_response(db, row)
