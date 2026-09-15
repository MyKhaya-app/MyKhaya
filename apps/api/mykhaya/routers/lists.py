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
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context
from mykhaya.entitlements import (
    CommercialRestrictionCode,
    classify_ordered_resources,
    commercial_restriction_error,
    get_limit,
    require_entitlement,
    require_within_limit,
)
from mykhaya.features import require_feature
from mykhaya.household_permissions import Capability, require_capability
from mykhaya.models import (
    FeatureKey,
    HouseholdList,
    HouseholdListItem,
    HouseholdListSection,
    ListTemplate,
    ListTemplateItem,
    ListTemplateSection,
    Membership,
    RoutineScope,
)
from mykhaya.notifications.lists_wishlists import notify_list_assignment
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
    ListScopeUpdateRequest,
    ListSectionCreate,
    ListSectionRenameRequest,
    ListSectionReorderRequest,
    ListSectionResponse,
    ListTemplateCreate,
    ListTemplateItemResponse,
    ListTemplateListResponse,
    ListTemplateResponse,
    ListTemplateUpdate,
)

LISTS_LIMIT_KEY = "lists.max_lists"


async def require_lists_feature(home_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    await require_feature(db, FeatureKey.shopping, home_id)


router = APIRouter(prefix="/homes", tags=["lists"], dependencies=[Depends(require_lists_feature)])


async def _ordered_lists(db: AsyncSession, group_id: uuid.UUID) -> list[HouseholdList]:
    """Deterministic priority order for commercial classification: oldest-
    created first (Lists has no "primary" concept, unlike HomeCalendar), a
    stable id tie-breaker for the vanishingly unlikely case of two rows
    sharing a created_at timestamp. See "Choosing the retained Free
    calendar" in docs/architecture/commercial-entitlements.md for the
    equivalent Calendar rule this mirrors."""
    return list(
        (
            await db.scalars(
                select(HouseholdList)
                .where(HouseholdList.group_id == group_id, HouseholdList.deleted_at.is_(None))
                .order_by(HouseholdList.created_at.asc(), HouseholdList.id.asc())
            )
        ).all()
    )


async def _list_access(db: AsyncSession, group_id: uuid.UUID) -> dict[uuid.UUID, bool]:
    """True = normal (within the Home's current lists.max_lists
    entitlement), False = read_only_due_to_plan. Computed fresh from
    current usage + entitlement on every call — never persisted, so it can
    never drift when the Home's plan changes. See mykhaya.entitlements
    .classify_ordered_resources and routers.calendar._calendar_access for
    the identical pattern this mirrors."""
    lists = await _ordered_lists(db, group_id)
    limit = await get_limit(db, group_id, LISTS_LIMIT_KEY)
    return classify_ordered_resources([row.id for row in lists], limit)


def _require_list_writable(access: dict[uuid.UUID, bool], list_id: uuid.UUID) -> None:
    if not access.get(list_id, False):
        raise commercial_restriction_error(
            CommercialRestrictionCode.resource_restricted_by_plan,
            "This list is included with MyKhaya Family. Upgrade to add or edit items here.",
            entitlement=LISTS_LIMIT_KEY,
        )


def _access_state(access: dict[uuid.UUID, bool], list_id: uuid.UUID) -> str:
    return "normal" if access.get(list_id, False) else "read_only_due_to_plan"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _get_active_list(
    db: AsyncSession,
    home_id: uuid.UUID,
    list_id: uuid.UUID,
    *,
    viewer_id: uuid.UUID | None = None,
    for_update: bool = False,
) -> HouseholdList:
    query = select(HouseholdList).where(
        HouseholdList.id == list_id,
        HouseholdList.group_id == home_id,
        HouseholdList.deleted_at.is_(None),
    )
    if for_update:
        query = query.with_for_update()
    row = await db.scalar(query)
    if row is None or (row.scope == RoutineScope.personal and row.created_by != viewer_id):
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


def _list_response(
    row: HouseholdList, total: int, remaining: int, access: dict[uuid.UUID, bool]
) -> ListResponse:
    return ListResponse(
        id=row.id,
        name=row.name,
        icon=row.icon,
        item_count=total,
        remaining_count=remaining,
        created_by=row.created_by,
        scope=row.scope,
        created_at=row.created_at,
        updated_at=row.updated_at,
        commercial_access=_access_state(access, row.id),
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
        section_id=row.section_id,
        text=row.text,
        quantity=row.quantity,
        note=row.note,
        assigned_member_id=row.assigned_member_id,
        is_checked=row.is_checked,
        completed_at=row.completed_at,
        completed_by=row.completed_by,
    )


async def _detail_response(
    db: AsyncSession, row: HouseholdList, access: dict[uuid.UUID, bool]
) -> ListDetailResponse:
    items = await _list_items(db, row.id)
    sections = list(
        (
            await db.scalars(
                select(HouseholdListSection)
                .where(HouseholdListSection.list_id == row.id)
                .order_by(HouseholdListSection.position, HouseholdListSection.id)
            )
        ).all()
    )
    section_items: dict[uuid.UUID, list[ListTemplateItemResponse]] = {}
    if sections:
        list_section_ids = [section.id for section in sections]
        copied_items = (
            await db.scalars(
                select(HouseholdListItem)
                .where(HouseholdListItem.section_id.in_(list_section_ids))
                .order_by(HouseholdListItem.position, HouseholdListItem.id)
            )
        ).all()
        for item in copied_items:
            if item.section_id is not None:
                section_items.setdefault(item.section_id, []).append(
                    ListTemplateItemResponse(id=item.id, text=item.text, position=item.position)
                )
    remaining = sum(1 for item in items if not item.is_checked)
    return ListDetailResponse(
        id=row.id,
        name=row.name,
        icon=row.icon,
        items=[_item_response(item) for item in items],
        item_count=len(items),
        remaining_count=remaining,
        created_by=row.created_by,
        scope=row.scope,
        created_at=row.created_at,
        updated_at=row.updated_at,
        commercial_access=_access_state(access, row.id),
        sections=[
            ListSectionResponse(
                id=section.id,
                name=section.name,
                position=section.position,
                items=section_items.get(section.id, []),
                updated_at=section.updated_at,
            )
            for section in sections
        ],
        source_template_id=row.source_template_id,
        source_template_name=row.source_template_name,
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


async def _get_active_section(
    db: AsyncSession, list_id: uuid.UUID, section_id: uuid.UUID, *, for_update: bool = False
) -> HouseholdListSection:
    query = select(HouseholdListSection).where(
        HouseholdListSection.id == section_id, HouseholdListSection.list_id == list_id
    )
    if for_update:
        query = query.with_for_update()
    section = await db.scalar(query)
    if section is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That section is invalid")
    return section


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------


async def _template_sections(db: AsyncSession, template_id: uuid.UUID) -> list[ListTemplateSection]:
    return list(
        (
            await db.scalars(
                select(ListTemplateSection)
                .where(ListTemplateSection.template_id == template_id)
                .order_by(ListTemplateSection.position, ListTemplateSection.id)
            )
        ).all()
    )


async def _template_response(db: AsyncSession, row: ListTemplate) -> ListTemplateResponse:
    sections = await _template_sections(db, row.id)
    item_rows = list(
        (
            await db.scalars(
                select(ListTemplateItem)
                .join(ListTemplateSection)
                .where(ListTemplateSection.template_id == row.id)
                .order_by(ListTemplateItem.position, ListTemplateItem.id)
            )
        ).all()
    )
    items_by_section: dict[uuid.UUID, list[ListTemplateItemResponse]] = {}
    for item in item_rows:
        items_by_section.setdefault(item.section_id, []).append(
            ListTemplateItemResponse(id=item.id, text=item.text, position=item.position)
        )
    return ListTemplateResponse(
        id=row.id,
        name=row.name,
        description=row.description,
        scope=row.scope,
        owner_user_id=row.owner_user_id,
        group_id=row.group_id,
        archived=row.archived_at is not None,
        created_at=row.created_at,
        updated_at=row.updated_at,
        sections=[
            ListSectionResponse(
                id=section.id,
                name=section.name,
                position=section.position,
                items=items_by_section.get(section.id, []),
                updated_at=section.updated_at,
            )
            for section in sections
        ],
    )


async def _get_template(
    db: AsyncSession, home_id: uuid.UUID, template_id: uuid.UUID, *, for_update: bool = False
) -> ListTemplate:
    query = select(ListTemplate).where(
        ListTemplate.id == template_id,
        ListTemplate.group_id == home_id,
        ListTemplate.archived_at.is_(None),
    )
    if for_update:
        query = query.with_for_update()
    row = await db.scalar(query)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That template could not be found")
    return row


async def _require_template_owner_or_household_manage(
    db: AsyncSession, home_id: uuid.UUID, row: ListTemplate, auth: AuthContext
) -> None:
    if row.scope == RoutineScope.personal and row.owner_user_id != auth.user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission to edit that template.")
    await require_capability(home_id, Capability.lists_manage, auth, db)


@router.get("/{home_id}/list-templates", response_model=ListTemplateListResponse)
async def list_templates(
    home_id: uuid.UUID,
    q: str | None = None,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ListTemplateListResponse:
    await require_capability(home_id, Capability.lists_view, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")
    filters = [ListTemplate.group_id == home_id, ListTemplate.archived_at.is_(None)]
    filters.append(
        (ListTemplate.scope == RoutineScope.household)
        | ((ListTemplate.scope == RoutineScope.personal) & (ListTemplate.owner_user_id == auth.user.id))
    )
    if q and q.strip():
        filters.append(ListTemplate.name.ilike(f"%{q.strip()}%"))
    rows = (
        await db.scalars(select(ListTemplate).where(*filters).order_by(ListTemplate.updated_at.desc()))
    ).all()
    return ListTemplateListResponse(items=[await _template_response(db, row) for row in rows])


@router.post("/{home_id}/list-templates", response_model=ListTemplateResponse, status_code=201)
async def create_template(
    home_id: uuid.UUID,
    body: ListTemplateCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ListTemplateResponse:
    await require_capability(home_id, Capability.lists_manage, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")
    row = ListTemplate(
        group_id=home_id,
        owner_user_id=auth.user.id,
        name=" ".join(body.name.strip().split()),
        description=body.description.strip() if body.description else None,
        scope=body.scope,
    )
    db.add(row)
    await db.flush()
    for section_position, section_input in enumerate(body.sections):
        section = ListTemplateSection(template_id=row.id, name=section_input.name.strip(), position=section_position)
        db.add(section)
        await db.flush()
        for item_position, item_input in enumerate(section_input.items):
            db.add(ListTemplateItem(section_id=section.id, text=item_input.text.strip(), position=item_position))
    audit(db, request, "lists.template.created", auth.user.id, home_id, "list_template", row.id)
    await db.commit()
    await db.refresh(row)
    return await _template_response(db, row)


@router.get("/{home_id}/list-templates/{template_id}", response_model=ListTemplateResponse)
async def get_template(
    home_id: uuid.UUID,
    template_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ListTemplateResponse:
    await require_capability(home_id, Capability.lists_view, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")
    row = await _get_template(db, home_id, template_id)
    if row.scope == RoutineScope.personal and row.owner_user_id != auth.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That template could not be found")
    return await _template_response(db, row)


@router.patch("/{home_id}/list-templates/{template_id}", response_model=ListTemplateResponse)
async def update_template(
    home_id: uuid.UUID,
    template_id: uuid.UUID,
    body: ListTemplateUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ListTemplateResponse:
    await require_entitlement(db, home_id, "lists.enabled")
    row = await _get_template(db, home_id, template_id, for_update=True)
    await _require_template_owner_or_household_manage(db, home_id, row, auth)
    if row.updated_at != body.expected_updated_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "This template changed. Reload and try again.")
    row.name = " ".join(body.name.strip().split())
    row.description = body.description.strip() if body.description else None
    row.scope = body.scope
    old_sections = await _template_sections(db, row.id)
    if old_sections:
        await db.execute(delete(ListTemplateSection).where(ListTemplateSection.template_id == row.id))
    for section_position, section_input in enumerate(body.sections):
        section = ListTemplateSection(template_id=row.id, name=section_input.name.strip(), position=section_position)
        db.add(section)
        await db.flush()
        for item_position, item_input in enumerate(section_input.items):
            db.add(ListTemplateItem(section_id=section.id, text=item_input.text.strip(), position=item_position))
    audit(db, request, "lists.template.updated", auth.user.id, home_id, "list_template", row.id)
    await db.commit()
    await db.refresh(row)
    return await _template_response(db, row)


@router.post("/{home_id}/list-templates/{template_id}/duplicate", response_model=ListTemplateResponse, status_code=201)
async def duplicate_template(
    home_id: uuid.UUID,
    template_id: uuid.UUID,
    body: ListTemplateCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ListTemplateResponse:
    await require_capability(home_id, Capability.lists_manage, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")
    source = await _get_template(db, home_id, template_id)
    if source.scope == RoutineScope.personal and source.owner_user_id != auth.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That template could not be found")
    row = ListTemplate(
        group_id=home_id, owner_user_id=auth.user.id, name=" ".join(body.name.strip().split()),
        description=body.description, scope=body.scope,
    )
    db.add(row)
    await db.flush()
    for source_section in await _template_sections(db, source.id):
        section = ListTemplateSection(template_id=row.id, name=source_section.name, position=source_section.position)
        db.add(section)
        await db.flush()
        items = (
            await db.scalars(select(ListTemplateItem).where(ListTemplateItem.section_id == source_section.id).order_by(ListTemplateItem.position))
        ).all()
        for item in items:
            db.add(ListTemplateItem(section_id=section.id, text=item.text, position=item.position))
    audit(db, request, "lists.template.duplicated", auth.user.id, home_id, "list_template", row.id)
    await db.commit()
    await db.refresh(row)
    return await _template_response(db, row)


@router.delete("/{home_id}/list-templates/{template_id}", status_code=204)
async def archive_template(
    home_id: uuid.UUID,
    template_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    await require_entitlement(db, home_id, "lists.enabled")
    row = await _get_template(db, home_id, template_id, for_update=True)
    await _require_template_owner_or_household_manage(db, home_id, row, auth)
    row.archived_at = datetime.now(tz=row.created_at.tzinfo)
    audit(db, request, "lists.template.archived", auth.user.id, home_id, "list_template", row.id)
    await db.commit()


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

    # Race-safe: serialises concurrent "create another list" attempts for
    # this Home so two simultaneous requests can't both observe the same
    # under-limit count and both insert past it — identical pattern to
    # routers.calendar.create_calendar's per-Home advisory lock. See
    # mykhaya.entitlements.require_within_limit's docstring.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"lists:{home_id}"}
    )
    current_count = await db.scalar(
        select(func.count())
        .select_from(HouseholdList)
        .where(HouseholdList.group_id == home_id, HouseholdList.deleted_at.is_(None))
    )
    await require_within_limit(db, home_id, LISTS_LIMIT_KEY, current_count or 0)

    template = None
    if body.template_id is not None:
        template = await _get_template(db, home_id, body.template_id)
        if template.scope == RoutineScope.personal and template.owner_user_id != auth.user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "That template could not be found")

    row = HouseholdList(
        group_id=home_id,
        name=" ".join(body.name.strip().split()),
        icon=body.icon,
        created_by=auth.user.id,
        scope=body.scope,
        source_template_id=template.id if template else None,
        source_template_name=template.name if template else None,
    )
    db.add(row)
    await db.flush()
    if template:
        template_sections = await _template_sections(db, template.id)
        for section_position, template_section in enumerate(template_sections):
            section = HouseholdListSection(
                list_id=row.id, name=template_section.name, position=section_position
            )
            db.add(section)
            await db.flush()
            template_items = (
                await db.scalars(
                    select(ListTemplateItem)
                    .where(ListTemplateItem.section_id == template_section.id)
                    .order_by(ListTemplateItem.position, ListTemplateItem.id)
                )
            ).all()
            for item_position, template_item in enumerate(template_items):
                db.add(
                    HouseholdListItem(
                        list_id=row.id,
                        section_id=section.id,
                        position=item_position,
                        text=template_item.text,
                        created_by=auth.user.id,
                    )
                )
    audit(db, request, "lists.list.created", auth.user.id, home_id, "list", row.id)
    await db.commit()
    return await _detail_response(db, row, {row.id: True})


@router.get("/{home_id}/lists", response_model=ListListResponse)
async def list_lists(
    home_id: uuid.UUID,
    q: str | None = None,
    scope: RoutineScope = RoutineScope.household,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ListListResponse:
    await require_capability(home_id, Capability.lists_view, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")

    filters = [
        HouseholdList.group_id == home_id,
        HouseholdList.deleted_at.is_(None),
        HouseholdList.scope == scope,
    ]
    if scope == RoutineScope.personal:
        filters.append(HouseholdList.created_by == auth.user.id)
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
    access = await _list_access(db, home_id)
    return ListListResponse(
        items=[_list_response(row, *counts.get(row.id, (0, 0)), access) for row in rows]
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
    row = await _get_active_list(db, home_id, list_id, viewer_id=auth.user.id)
    access = await _list_access(db, home_id)
    return await _detail_response(db, row, access)


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
    row = await _get_active_list(db, home_id, list_id, viewer_id=auth.user.id, for_update=True)
    access = await _list_access(db, home_id)
    _require_list_writable(access, row.id)
    if row.updated_at != body.expected_updated_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "This list changed. Reload and try again.")
    row.name = " ".join(body.name.strip().split())
    row.icon = body.icon
    audit(db, request, "lists.list.renamed", auth.user.id, home_id, "list", row.id)
    await db.commit()
    await db.refresh(row)
    return await _detail_response(db, row, access)


@router.patch("/{home_id}/lists/{list_id}/scope", response_model=ListDetailResponse)
async def update_list_scope(
    home_id: uuid.UUID,
    list_id: uuid.UUID,
    body: ListScopeUpdateRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ListDetailResponse:
    await require_capability(home_id, Capability.lists_manage, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")
    row = await _get_active_list(db, home_id, list_id, viewer_id=auth.user.id, for_update=True)
    access = await _list_access(db, home_id)
    _require_list_writable(access, row.id)
    if row.updated_at != body.expected_updated_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "This list changed. Reload and try again.")

    old_scope = row.scope
    if old_scope == body.scope:
        return await _detail_response(db, row, access)
    if old_scope == RoutineScope.household and row.created_by != auth.user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the list owner can make a household list personal.",
        )

    row.scope = body.scope
    audit(
        db,
        request,
        "lists.list.scope_changed",
        auth.user.id,
        home_id,
        "list",
        row.id,
        metadata={"old_scope": old_scope, "new_scope": body.scope},
    )
    await db.commit()
    await db.refresh(row)
    return await _detail_response(db, row, access)


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
    row = await _get_active_list(db, home_id, list_id, viewer_id=auth.user.id)
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


@router.post("/{home_id}/lists/{list_id}/sections", response_model=ListDetailResponse, status_code=201)
async def add_list_section(
    home_id: uuid.UUID, list_id: uuid.UUID, body: ListSectionCreate, request: Request,
    auth: AuthContext = Depends(auth_context), db: AsyncSession = Depends(get_db),
) -> ListDetailResponse:
    await require_capability(home_id, Capability.lists_manage, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")
    row = await _get_active_list(db, home_id, list_id, viewer_id=auth.user.id)
    access = await _list_access(db, home_id)
    _require_list_writable(access, row.id)
    position = int(await db.scalar(select(func.count()).where(HouseholdListSection.list_id == row.id)) or 0)
    db.add(HouseholdListSection(list_id=row.id, name=body.name.strip(), position=position))
    audit(db, request, "lists.section.added", auth.user.id, home_id, "list", row.id)
    await db.commit()
    return await _detail_response(db, row, access)


@router.patch("/{home_id}/lists/{list_id}/sections/{section_id}", response_model=ListDetailResponse)
async def rename_list_section(
    home_id: uuid.UUID, list_id: uuid.UUID, section_id: uuid.UUID, body: ListSectionRenameRequest,
    request: Request, auth: AuthContext = Depends(auth_context), db: AsyncSession = Depends(get_db),
) -> ListDetailResponse:
    await require_capability(home_id, Capability.lists_manage, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")
    row = await _get_active_list(db, home_id, list_id, viewer_id=auth.user.id)
    access = await _list_access(db, home_id)
    _require_list_writable(access, row.id)
    section = await _get_active_section(db, row.id, section_id, for_update=True)
    if section.updated_at != body.expected_updated_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "This section changed. Reload and try again.")
    section.name = body.name.strip()
    audit(db, request, "lists.section.renamed", auth.user.id, home_id, "list", row.id)
    await db.commit()
    return await _detail_response(db, row, access)


@router.delete("/{home_id}/lists/{list_id}/sections/{section_id}", response_model=ListDetailResponse)
async def remove_list_section(
    home_id: uuid.UUID, list_id: uuid.UUID, section_id: uuid.UUID, request: Request,
    auth: AuthContext = Depends(auth_context), db: AsyncSession = Depends(get_db),
) -> ListDetailResponse:
    await require_capability(home_id, Capability.lists_manage, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")
    row = await _get_active_list(db, home_id, list_id, viewer_id=auth.user.id)
    access = await _list_access(db, home_id)
    _require_list_writable(access, row.id)
    section = await _get_active_section(db, row.id, section_id)
    await db.execute(
        HouseholdListItem.__table__.update().where(HouseholdListItem.section_id == section.id).values(section_id=None)
    )
    await db.delete(section)
    audit(db, request, "lists.section.removed", auth.user.id, home_id, "list", row.id)
    await db.commit()
    return await _detail_response(db, row, access)


@router.post("/{home_id}/lists/{list_id}/sections/reorder", response_model=ListDetailResponse)
async def reorder_list_sections(
    home_id: uuid.UUID, list_id: uuid.UUID, body: ListSectionReorderRequest,
    auth: AuthContext = Depends(auth_context), db: AsyncSession = Depends(get_db),
) -> ListDetailResponse:
    await require_capability(home_id, Capability.lists_manage, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")
    row = await _get_active_list(db, home_id, list_id, viewer_id=auth.user.id, for_update=True)
    access = await _list_access(db, home_id)
    _require_list_writable(access, row.id)
    sections = list(
        (
            await db.scalars(
                select(HouseholdListSection).where(HouseholdListSection.list_id == row.id)
            )
        ).all()
    )
    if {section.id for section in sections} != set(body.section_ids) or len(sections) != len(body.section_ids):
        raise HTTPException(status.HTTP_409_CONFLICT, "This list's sections changed. Reload and try again.")
    by_id = {section.id: section for section in sections}
    for position, section_id in enumerate(body.section_ids):
        by_id[section_id].position = position
    await db.commit()
    return await _detail_response(db, row, access)


@router.post("/{home_id}/lists/{list_id}/items", response_model=ListDetailResponse, status_code=201)
async def add_list_item(
    home_id: uuid.UUID,
    list_id: uuid.UUID,
    body: ListItemInput,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ListDetailResponse:
    await require_capability(home_id, Capability.lists_manage, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")
    row = await _get_active_list(db, home_id, list_id, viewer_id=auth.user.id)
    access = await _list_access(db, home_id)
    _require_list_writable(access, row.id)
    if body.section_id is not None:
        await _get_active_section(db, row.id, body.section_id)
    if body.assigned_member_id is not None:
        await _validate_member(db, home_id, body.assigned_member_id)
        if row.scope == RoutineScope.personal and body.assigned_member_id != auth.user.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Personal list items can only be assigned to the owner",
            )
    next_position = await _next_position(db, row.id)
    item = HouseholdListItem(
        list_id=row.id,
        position=next_position,
        text=body.text.strip(),
        quantity=body.quantity,
        note=body.note,
        assigned_member_id=body.assigned_member_id,
        section_id=body.section_id,
        created_by=auth.user.id,
    )
    db.add(item)
    await db.flush()
    if item.assigned_member_id is not None:
        await notify_list_assignment(
            db, settings=settings, item=item, list_row=row, actor=auth.user,
            recipient_user_id=item.assigned_member_id,
        )
    audit(db, request, "lists.item.added", auth.user.id, home_id, "list", row.id)
    await db.commit()
    return await _detail_response(db, row, access)


@router.patch("/{home_id}/lists/{list_id}/items/{item_id}", response_model=ListDetailResponse)
async def update_list_item(
    home_id: uuid.UUID,
    list_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ListItemUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ListDetailResponse:
    """One endpoint for both a quick checkbox toggle and a full edit — only
    the fields actually present in the request body are applied (see
    ListItemUpdate's docstring), so toggling a checkbox never has to resend
    the item's text/quantity/note just to leave them unchanged."""
    await require_capability(home_id, Capability.lists_manage, auth, db)
    await require_entitlement(db, home_id, "lists.enabled")
    row = await _get_active_list(db, home_id, list_id, viewer_id=auth.user.id)
    access = await _list_access(db, home_id)
    _require_list_writable(access, row.id)
    item = await db.scalar(
        select(HouseholdListItem).where(
            HouseholdListItem.id == item_id, HouseholdListItem.list_id == row.id
        )
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That item could not be found")

    fields = body.model_fields_set
    previous_assignee = item.assigned_member_id
    if "assigned_member_id" in fields and body.assigned_member_id is not None:
        await _validate_member(db, home_id, body.assigned_member_id)
        if row.scope == RoutineScope.personal and body.assigned_member_id != auth.user.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Personal list items can only be assigned to the owner",
            )
    if "text" in fields and body.text is not None:
        item.text = body.text.strip()
    if "quantity" in fields:
        item.quantity = body.quantity
    if "note" in fields:
        item.note = body.note
    if "assigned_member_id" in fields:
        item.assigned_member_id = body.assigned_member_id
    if "section_id" in fields:
        if body.section_id is not None:
            await _get_active_section(db, row.id, body.section_id)
        item.section_id = body.section_id
    new_checked = body.is_checked
    if "is_checked" in fields and new_checked is not None and new_checked != item.is_checked:
        item.is_checked = new_checked
        if new_checked:
            item.completed_at = datetime.now(tz=item.created_at.tzinfo)
            item.completed_by = auth.user.id
        else:
            item.completed_at = None
            item.completed_by = None

    if item.assigned_member_id is not None and item.assigned_member_id != previous_assignee:
        await notify_list_assignment(
            db, settings=settings, item=item, list_row=row, actor=auth.user,
            recipient_user_id=item.assigned_member_id,
        )
    audit(db, request, "lists.item.updated", auth.user.id, home_id, "list", row.id)
    await db.commit()
    return await _detail_response(db, row, access)


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
    row = await _get_active_list(db, home_id, list_id, viewer_id=auth.user.id)
    access = await _list_access(db, home_id)
    _require_list_writable(access, row.id)
    await db.execute(
        delete(HouseholdListItem).where(
            HouseholdListItem.id == item_id, HouseholdListItem.list_id == row.id
        )
    )
    audit(db, request, "lists.item.removed", auth.user.id, home_id, "list", row.id)
    await db.commit()
    return await _detail_response(db, row, access)


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
    row = await _get_active_list(db, home_id, list_id, viewer_id=auth.user.id, for_update=True)
    access = await _list_access(db, home_id)
    _require_list_writable(access, row.id)
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
    return await _detail_response(db, row, access)


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
    row = await _get_active_list(db, home_id, list_id, viewer_id=auth.user.id)
    access = await _list_access(db, home_id)
    _require_list_writable(access, row.id)
    await db.execute(
        delete(HouseholdListItem).where(
            HouseholdListItem.list_id == row.id, HouseholdListItem.is_checked.is_(True)
        )
    )
    audit(db, request, "lists.items.cleared_completed", auth.user.id, home_id, "list", row.id)
    await db.commit()
    return await _detail_response(db, row, access)
