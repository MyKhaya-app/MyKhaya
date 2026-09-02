"""Wishlists V1 — a per-person module, not shared household structure like
Meals/Lists (see models.py's Wishlists section). Each member can create
multiple wishlists; other Home members (via `wishlists_view`) and people
explicitly shared with (MyKhaya users outside the Home, or guests via
link+PIN) can view and reserve/buy items, but the owner must never learn
whether their own items are reserved/bought — see `_owner_item_response`
and `_viewer_item_response`, the one place that split is enforced.

Route shape:
  - `/homes/{home_id}/wishlists...` — creation, editing, deletion and
    sharing, which only make sense in the context of the owner's own Home
    (capability + entitlement checks are Home-scoped) and are always
    additionally gated by `_require_owner_or_admin`.
  - `/wishlists/{wishlist_id}/...` — viewing and reservation actions,
    top-level because a share recipient may belong to a *different* Home
    (or none at all) and should never need to know the sharer's home_id.
    Access here is resolved per-request against owner/home-membership/share,
    not against a single capability check.
  - `/wishlist/share/{token}/verify` and `/wishlist/guest/...` — the guest
    flow, using `wishlist_guest.wishlist_guest_context` instead of
    `AuthContext` entirely.
"""

from __future__ import annotations

import secrets
import string
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context, membership_for
from mykhaya.entitlements import require_entitlement
from mykhaya.features import require_feature
from mykhaya.household_permissions import Capability, capabilities_for, require_capability
from mykhaya.models import (
    FeatureKey,
    Membership,
    PermissionProfile,
    User,
    Wishlist,
    WishlistGuestSession,
    WishlistItem,
    WishlistItemReservation,
    WishlistReservationActorType,
    WishlistReservationStatus,
    WishlistShare,
    WishlistShareType,
)
from mykhaya.notifications.lists_wishlists import (
    notify_wishlist_recipient,
    notify_wishlist_share,
)
from mykhaya.rate_limit import enforce_rate_limit
from mykhaya.security import (
    DUMMY_HASH,
    decode_derived_token,
    derived_token,
    hash_secret,
    is_valid_child_pin,
    normalise_email,
    password_hash,
    verify_password,
)
from mykhaya.wishlist_guest import (
    GUEST_COOKIE_NAME,
    WishlistGuestContext,
    clear_guest_cookies,
    require_guest_csrf,
    set_guest_cookies,
    wishlist_guest_context,
)
from mykhaya.wishlist_link_preview import fetch_link_preview
from mykhaya.wishlist_schemas import (
    GuestShareCreateResponse,
    GuestVerifyRequest,
    GuestVerifyResponse,
    LinkPreviewRequest,
    LinkPreviewResponse,
    MarkBoughtRequest,
    ReserveItemRequest,
    ShareCreateRequest,
    ShareListItemResponse,
    ShareListResponse,
    ShareRecipientLookupRequest,
    ShareRecipientLookupResponse,
    ShareResponse,
    WishlistCreate,
    WishlistItemCreate,
    WishlistItemOwnerResponse,
    WishlistItemReorderRequest,
    WishlistItemUpdate,
    WishlistItemViewerResponse,
    WishlistListResponse,
    WishlistOwnerDetailResponse,
    WishlistSummaryResponse,
    WishlistUpdateRequest,
    WishlistViewerDetailResponse,
    WishlistVisibilityUpdateRequest,
)

WishlistDetailResponse = WishlistOwnerDetailResponse | WishlistViewerDetailResponse

_SHARE_TOKEN_PURPOSE = "wishlist_share"
# Guest PIN brute force is constrained by rate limiting, not hash strength
# (see WishlistShare.pin_hash's docstring) — 10 attempts per 5 minutes per
# IP is generous enough for someone fat-fingering a 6-digit PIN a couple of
# times, tight enough that exhausting a 10^6 keyspace is impractical.
_GUEST_PIN_RATE_LIMIT = 10
_GUEST_PIN_RATE_WINDOW = 300
# Share creation is cheap but still worth a light spam guard — a compromised
# session churning out guest links would otherwise be unbounded.
_SHARE_CREATE_RATE_LIMIT = 20
_SHARE_CREATE_RATE_WINDOW = 300
# Link-preview is SSRF-adjacent (mykhaya.wishlist_link_preview already
# blocks internal targets, but rate limiting keeps this from also being
# usable as a cheap anonymising probe against arbitrary public hosts) —
# generous enough for someone pasting a handful of product links in a
# session, tight enough to not be a useful proxy.
_LINK_PREVIEW_RATE_LIMIT = 20
_LINK_PREVIEW_RATE_WINDOW = 300


async def require_wishlists_feature(home_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    await require_feature(db, FeatureKey.wish_lists, home_id)


router = APIRouter(
    prefix="/homes", tags=["wishlists"], dependencies=[Depends(require_wishlists_feature)]
)
# Top-level: viewing/reserving a wishlist you were shared, independent of
# any Home path — see module docstring.
shared_router = APIRouter(tags=["wishlists"])
guest_router = APIRouter(tags=["wishlists-guest"])


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _get_active_wishlist(
    db: AsyncSession, home_id: uuid.UUID, wishlist_id: uuid.UUID, *, for_update: bool = False
) -> Wishlist:
    query = select(Wishlist).where(
        Wishlist.id == wishlist_id,
        Wishlist.home_id == home_id,
        Wishlist.deleted_at.is_(None),
    )
    if for_update:
        query = query.with_for_update()
    row = await db.scalar(query)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That wishlist could not be found")
    return row


async def _get_active_wishlist_any_home(
    db: AsyncSession, wishlist_id: uuid.UUID, *, for_update: bool = False
) -> Wishlist:
    query = select(Wishlist).where(Wishlist.id == wishlist_id, Wishlist.deleted_at.is_(None))
    if for_update:
        query = query.with_for_update()
    row = await db.scalar(query)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That wishlist could not be found")
    return row


async def _require_owner_or_admin(wishlist: Wishlist, auth: AuthContext, membership: Membership) -> None:
    if wishlist.owner_user_id == auth.user.id:
        return
    if membership.permission_profile == PermissionProfile.home_admin:
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN, "Only the wishlist's owner or a Home Admin can do that."
    )


async def _membership_or_none(
    db: AsyncSession, home_id: uuid.UUID, auth: AuthContext
) -> Membership | None:
    try:
        return await membership_for(home_id, auth, db)
    except HTTPException:
        return None


async def _active_share_for_recipient(
    db: AsyncSession, wishlist_id: uuid.UUID, user_id: uuid.UUID
) -> WishlistShare | None:
    return await db.scalar(
        select(WishlistShare).where(
            WishlistShare.wishlist_id == wishlist_id,
            WishlistShare.recipient_user_id == user_id,
            WishlistShare.share_type == WishlistShareType.mykhaya_user,
            WishlistShare.revoked_at.is_(None),
        )
    )


async def _wishlist_items(db: AsyncSession, wishlist_id: uuid.UUID) -> list[WishlistItem]:
    return list(
        (
            await db.scalars(
                select(WishlistItem)
                .where(WishlistItem.wishlist_id == wishlist_id, WishlistItem.deleted_at.is_(None))
                .order_by(WishlistItem.sort_order)
            )
        ).all()
    )


async def _share_count(db: AsyncSession, wishlist_id: uuid.UUID) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(WishlistShare)
            .where(WishlistShare.wishlist_id == wishlist_id, WishlistShare.revoked_at.is_(None))
        )
        or 0
    )


async def _share_counts(db: AsyncSession, wishlist_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not wishlist_ids:
        return {}
    return dict(
        (
            await db.execute(
                select(WishlistShare.wishlist_id, func.count())
                .where(
                    WishlistShare.wishlist_id.in_(wishlist_ids),
                    WishlistShare.revoked_at.is_(None),
                )
                .group_by(WishlistShare.wishlist_id)
            )
        ).all()
    )


async def _next_sort_order(db: AsyncSession, wishlist_id: uuid.UUID) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(WishlistItem)
            .where(WishlistItem.wishlist_id == wishlist_id, WishlistItem.deleted_at.is_(None))
        )
        or 0
    )


def _owner_item_response(item: WishlistItem) -> WishlistItemOwnerResponse:
    return WishlistItemOwnerResponse(
        id=item.id,
        name=item.name,
        url=item.url,
        price=item.price,
        currency=item.currency,
        note=item.note,
        image_url=item.image_url,
        quantity=item.quantity,
        sort_order=item.sort_order,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _viewer_item_response(
    item: WishlistItem, reservation: WishlistItemReservation | None
) -> WishlistItemViewerResponse:
    return WishlistItemViewerResponse(
        id=item.id,
        name=item.name,
        url=item.url,
        price=item.price,
        currency=item.currency,
        note=item.note,
        image_url=item.image_url,
        quantity=item.quantity,
        sort_order=item.sort_order,
        created_at=item.created_at,
        updated_at=item.updated_at,
        reservation_status=(reservation.status.value if reservation else "available"),
        reserved_by_display_name=(reservation.buyer_display_name if reservation else None),
    )


async def _reservations_by_item(
    db: AsyncSession, item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, WishlistItemReservation]:
    if not item_ids:
        return {}
    rows = (
        await db.scalars(
            select(WishlistItemReservation).where(
                WishlistItemReservation.wishlist_item_id.in_(item_ids)
            )
        )
    ).all()
    return {row.wishlist_item_id: row for row in rows}


async def _owner_detail_response(db: AsyncSession, wishlist: Wishlist) -> WishlistOwnerDetailResponse:
    # Deliberately never queries WishlistItemReservation at all on this path
    # — see module docstring. There is nothing here for a future edit to
    # accidentally leak because the reservation table is simply absent from
    # this function's dataflow.
    items = await _wishlist_items(db, wishlist.id)
    share_count = await _share_count(db, wishlist.id)
    return WishlistOwnerDetailResponse(
        id=wishlist.id,
        home_id=wishlist.home_id,
        title=wishlist.title,
        occasion=wishlist.occasion,
        occasion_date=wishlist.occasion_date,
        description=wishlist.description,
        owner_user_id=wishlist.owner_user_id,
        home_visible=wishlist.home_visible,
        share_count=share_count,
        created_at=wishlist.created_at,
        updated_at=wishlist.updated_at,
        items=[_owner_item_response(item) for item in items],
    )


async def _viewer_detail_response(
    db: AsyncSession, wishlist: Wishlist
) -> WishlistViewerDetailResponse:
    items = await _wishlist_items(db, wishlist.id)
    reservations = await _reservations_by_item(db, [item.id for item in items])
    owner_name = await db.scalar(select(User.display_name).where(User.id == wishlist.owner_user_id))
    return WishlistViewerDetailResponse(
        id=wishlist.id,
        home_id=wishlist.home_id,
        title=wishlist.title,
        occasion=wishlist.occasion,
        occasion_date=wishlist.occasion_date,
        description=wishlist.description,
        owner_user_id=wishlist.owner_user_id,
        owner_display_name=owner_name or "",
        created_at=wishlist.created_at,
        updated_at=wishlist.updated_at,
        items=[_viewer_item_response(item, reservations.get(item.id)) for item in items],
    )


async def _detail_response(
    db: AsyncSession, wishlist: Wishlist, auth: AuthContext
) -> WishlistDetailResponse:
    if wishlist.owner_user_id == auth.user.id:
        return await _owner_detail_response(db, wishlist)
    return await _viewer_detail_response(db, wishlist)


async def _summary_response(
    db: AsyncSession,
    wishlist: Wishlist,
    item_count: int,
    owner_name: str,
    caller_id: uuid.UUID,
    share_count: int = 0,
) -> WishlistSummaryResponse:
    is_owner = wishlist.owner_user_id == caller_id
    return WishlistSummaryResponse(
        id=wishlist.id,
        home_id=wishlist.home_id,
        title=wishlist.title,
        occasion=wishlist.occasion,
        occasion_date=wishlist.occasion_date,
        description=wishlist.description,
        owner_user_id=wishlist.owner_user_id,
        owner_display_name=owner_name,
        item_count=item_count,
        is_owner=is_owner,
        home_visible=wishlist.home_visible,
        # Never exposed for a wishlist that isn't the caller's own — see
        # WishlistSummaryResponse's docstring.
        share_count=share_count if is_owner else 0,
        created_at=wishlist.created_at,
        updated_at=wishlist.updated_at,
    )


class _ViewerAccess:
    """Resolved kind of access a caller has to a wishlist that is not their
    own — used by the top-level view/reserve endpoints, which must work
    identically whether the caller reached the wishlist as a same-Home
    member or as an out-of-Home share recipient."""

    def __init__(self, kind: str, share: WishlistShare | None = None) -> None:
        self.kind = kind  # "member" | "share"
        self.share = share


async def _resolve_non_owner_access(
    db: AsyncSession, wishlist: Wishlist, auth: AuthContext
) -> _ViewerAccess:
    # Same-Home "member" access is now opt-in: a fellow Home member with
    # wishlists_view only gets in if the *owner* has separately turned Home
    # visibility on for this specific wishlist (Wishlist.home_visible).
    # Private is the default (see models.Wishlist.home_visible's docstring)
    # — without this check, any member with the capability could see every
    # Home member's wishlist regardless of the owner's choice, which is
    # exactly the behaviour this task removes.
    #
    # home_admin gets no special-case here on purpose: a Home Admin can
    # still fully manage (edit/delete/reorder/add items to, share) ANY
    # wishlist in their Home via the owner-or-admin-gated management
    # endpoints regardless of home_visible (_require_owner_or_admin doesn't
    # consult home_visible at all) — that's their "genuinely requires
    # management access" path. But they don't get a passive, no-action-taken
    # ability to browse another member's private wishlist's contents through
    # the read-only view/reserve endpoints just by being an admin — that
    # would be a quiet blanket surveillance capability inconsistent with
    # this module's per-person, owner-controlled-visibility philosophy (the
    # same philosophy that keeps the owner blind to their own item
    # reservations). See the router module docstring / final report for the
    # full reasoning.
    if wishlist.home_visible:
        membership = await _membership_or_none(db, wishlist.home_id, auth)
        if membership is not None:
            if Capability.wishlists_view in await capabilities_for(db, membership):
                return _ViewerAccess("member")
    share = await _active_share_for_recipient(db, wishlist.id, auth.user.id)
    if share is not None:
        return _ViewerAccess("share", share)
    # Deliberately the same 404 for "no such wishlist" and "not authorised" —
    # matches membership_for's convention elsewhere in the app.
    raise HTTPException(status.HTTP_404_NOT_FOUND, "That wishlist could not be found")


# ---------------------------------------------------------------------------
# Wishlist CRUD (Home-scoped)
# ---------------------------------------------------------------------------


@router.post("/{home_id}/wishlists", response_model=WishlistOwnerDetailResponse, status_code=201)
async def create_wishlist(
    home_id: uuid.UUID,
    body: WishlistCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> WishlistOwnerDetailResponse:
    membership = await require_capability(home_id, Capability.wishlists_manage, auth, db)
    await require_entitlement(db, home_id, "wishlists.enabled")

    owner_user_id = body.owner_user_id or auth.user.id
    if owner_user_id != auth.user.id:
        # Only a Home Admin may create a wishlist on someone else's behalf
        # (e.g. a managed Child) — see Capability.wishlists_manage's
        # docstring.
        if membership.permission_profile != PermissionProfile.home_admin:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Only a Home Admin can create a wishlist for someone else."
            )
        target = await db.scalar(
            select(Membership.user_id).where(
                Membership.group_id == home_id,
                Membership.user_id == owner_user_id,
                Membership.removed_at.is_(None),
            )
        )
        if target is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That member is invalid")

    row = Wishlist(
        home_id=home_id,
        owner_user_id=owner_user_id,
        title=" ".join(body.title.strip().split()),
        occasion=body.occasion,
        occasion_date=body.occasion_date,
        description=body.description,
        created_by=auth.user.id,
    )
    db.add(row)
    await db.flush()
    audit(db, request, "wishlists.wishlist.created", auth.user.id, home_id, "wishlist", row.id)
    await db.commit()
    return await _owner_detail_response(db, row)


@router.get("/{home_id}/wishlists", response_model=WishlistListResponse)
async def list_wishlists(
    home_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> WishlistListResponse:
    await require_capability(home_id, Capability.wishlists_view, auth, db)
    await require_entitlement(db, home_id, "wishlists.enabled")

    # Own wishlists always included; other members' wishlists only when the
    # owner has opted into Home visibility — this is the query-level
    # enforcement of "must not show private wishlists belonging to other
    # members" (never relying on the frontend to hide anything). A
    # home_admin gets no broader filter here than anyone else with
    # wishlists_view — see _resolve_non_owner_access's docstring for why.
    rows = (
        await db.scalars(
            select(Wishlist)
            .where(
                Wishlist.home_id == home_id,
                Wishlist.deleted_at.is_(None),
                (Wishlist.owner_user_id == auth.user.id) | Wishlist.home_visible.is_(True),
            )
            .order_by(Wishlist.updated_at.desc())
        )
    ).all()
    if not rows:
        return WishlistListResponse(items=[])
    counts = dict(
        (
            await db.execute(
                select(WishlistItem.wishlist_id, func.count())
                .where(
                    WishlistItem.wishlist_id.in_([row.id for row in rows]),
                    WishlistItem.deleted_at.is_(None),
                )
                .group_by(WishlistItem.wishlist_id)
            )
        ).all()
    )
    share_counts = await _share_counts(db, [row.id for row in rows])
    owner_names = dict(
        (
            await db.execute(
                select(User.id, User.display_name).where(
                    User.id.in_({row.owner_user_id for row in rows})
                )
            )
        ).all()
    )
    return WishlistListResponse(
        items=[
            await _summary_response(
                db,
                row,
                counts.get(row.id, 0),
                owner_names.get(row.owner_user_id, ""),
                auth.user.id,
                share_counts.get(row.id, 0),
            )
            for row in rows
        ]
    )


@router.get("/{home_id}/wishlists/{wishlist_id}", response_model=None)
async def get_wishlist(
    home_id: uuid.UUID,
    wishlist_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> WishlistDetailResponse:
    await require_capability(home_id, Capability.wishlists_view, auth, db)
    await require_entitlement(db, home_id, "wishlists.enabled")
    row = await _get_active_wishlist(db, home_id, wishlist_id)
    if row.owner_user_id != auth.user.id and not row.home_visible:
        # Same-Home membership + wishlists_view is no longer sufficient on
        # its own once the owner has kept this wishlist Private — fall back
        # to checking for a personal share, same as the top-level path.
        share = await _active_share_for_recipient(db, row.id, auth.user.id)
        if share is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "That wishlist could not be found")
    return await _detail_response(db, row, auth)


@router.patch("/{home_id}/wishlists/{wishlist_id}", response_model=WishlistOwnerDetailResponse)
async def update_wishlist(
    home_id: uuid.UUID,
    wishlist_id: uuid.UUID,
    body: WishlistUpdateRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> WishlistOwnerDetailResponse:
    membership = await require_capability(home_id, Capability.wishlists_manage, auth, db)
    await require_entitlement(db, home_id, "wishlists.enabled")
    row = await _get_active_wishlist(db, home_id, wishlist_id, for_update=True)
    await _require_owner_or_admin(row, auth, membership)
    if row.updated_at != body.expected_updated_at:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This wishlist changed. Reload and try again."
        )
    row.title = " ".join(body.title.strip().split())
    row.occasion = body.occasion
    row.occasion_date = body.occasion_date
    row.description = body.description
    audit(db, request, "wishlists.wishlist.updated", auth.user.id, home_id, "wishlist", row.id)
    await db.commit()
    await db.refresh(row)
    return await _owner_detail_response(db, row)


@router.delete("/{home_id}/wishlists/{wishlist_id}", status_code=204)
async def delete_wishlist(
    home_id: uuid.UUID,
    wishlist_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    membership = await require_capability(home_id, Capability.wishlists_manage, auth, db)
    await require_entitlement(db, home_id, "wishlists.enabled")
    row = await _get_active_wishlist(db, home_id, wishlist_id)
    await _require_owner_or_admin(row, auth, membership)
    row.deleted_at = datetime.now(tz=row.created_at.tzinfo)
    audit(db, request, "wishlists.wishlist.deleted", auth.user.id, home_id, "wishlist", row.id)
    await db.commit()


@router.post(
    "/{home_id}/wishlists/{wishlist_id}/home-visibility",
    response_model=WishlistOwnerDetailResponse,
)
async def set_wishlist_home_visibility(
    home_id: uuid.UUID,
    wishlist_id: uuid.UUID,
    body: WishlistVisibilityUpdateRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WishlistOwnerDetailResponse:
    """Toggles Wishlist.home_visible only — never creates, revokes, or
    otherwise touches any WishlistShare row. Per-recipient sharing and Home
    visibility are fully independent, in both directions: this endpoint has
    no side effect on shares, and revoke_share has no side effect on
    home_visible. See models.Wishlist.home_visible's docstring."""
    membership = await require_capability(home_id, Capability.wishlists_manage, auth, db)
    await require_entitlement(db, home_id, "wishlists.enabled")
    row = await _get_active_wishlist(db, home_id, wishlist_id, for_update=True)
    await _require_owner_or_admin(row, auth, membership)
    previous_visibility = row.home_visible
    memberships = (
        await db.scalars(
            select(Membership).where(
                Membership.group_id == home_id,
                Membership.user_id != row.owner_user_id,
                Membership.removed_at.is_(None),
            )
        )
    ).all()
    member_ids = [
        member.user_id
        for member in memberships
        if Capability.wishlists_view in await capabilities_for(db, member)
    ]
    row.home_visible = body.enabled
    if previous_visibility != body.enabled:
        for member_id in member_ids:
            await notify_wishlist_recipient(
                db,
                settings=settings,
                wishlist=row,
                actor=auth.user,
                recipient_user_id=member_id,
                notification_type=(
                    "wishlist_share_created" if body.enabled else "wishlist_share_revoked"
                ),
                title=("Wishlist shared with your Home" if body.enabled else "Wishlist access removed"),
                body=(
                    f'{auth.user.display_name} shared "{row.title}" with your Home.'
                    if body.enabled
                    else f'{auth.user.display_name} removed your Home access to "{row.title}".'
                ),
                idempotency_key=f"wishlist_home_visibility:{row.id}:{member_id}:{body.enabled}",
            )
    audit(
        db,
        request,
        f"wishlists.home_visibility.{'enabled' if body.enabled else 'disabled'}",
        auth.user.id,
        home_id,
        "wishlist",
        row.id,
    )
    await db.commit()
    await db.refresh(row)
    return await _owner_detail_response(db, row)


@router.post("/{home_id}/wishlists/link-preview", response_model=LinkPreviewResponse)
async def wishlist_link_preview(
    home_id: uuid.UUID,
    body: LinkPreviewRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LinkPreviewResponse:
    """Stateless server-side metadata fetch for a pasted item URL — never
    touches wishlist/item storage itself (see WishlistItemCreate/Update,
    which already accept image_url/price/name as plain optional fields the
    FRONTEND populates from this response before submitting its own
    create/update call). Gated the same as any other wishlists_manage
    action plus the module entitlement, so this can't be used as a free
    arbitrary-URL-fetch proxy by a non-Family user or from an unrelated
    Home. SSRF protections live in mykhaya.wishlist_link_preview — this
    endpoint never sees a raw upstream error; any failure there already
    resolves to the same empty LinkPreviewResponse as "reachable page with
    no metadata"."""
    await require_capability(home_id, Capability.wishlists_manage, auth, db)
    await require_entitlement(db, home_id, "wishlists.enabled")
    await enforce_rate_limit(
        request, settings, "wishlist_link_preview", _LINK_PREVIEW_RATE_LIMIT, _LINK_PREVIEW_RATE_WINDOW
    )
    result = await fetch_link_preview(body.url, settings)
    return LinkPreviewResponse(
        title=result.title,
        image_url=result.image_url,
        description=result.description,
        price=result.price,
        currency=result.currency,
    )


# ---------------------------------------------------------------------------
# Items (Home-scoped, owner/admin-only mutation)
# ---------------------------------------------------------------------------


@router.post(
    "/{home_id}/wishlists/{wishlist_id}/items",
    response_model=WishlistOwnerDetailResponse,
    status_code=201,
)
async def add_wishlist_item(
    home_id: uuid.UUID,
    wishlist_id: uuid.UUID,
    body: WishlistItemCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> WishlistOwnerDetailResponse:
    membership = await require_capability(home_id, Capability.wishlists_manage, auth, db)
    await require_entitlement(db, home_id, "wishlists.enabled")
    row = await _get_active_wishlist(db, home_id, wishlist_id)
    await _require_owner_or_admin(row, auth, membership)
    next_order = await _next_sort_order(db, row.id)
    db.add(
        WishlistItem(
            wishlist_id=row.id,
            name=body.name.strip(),
            url=body.url,
            price=body.price,
            currency=body.currency,
            note=body.note,
            image_url=body.image_url,
            quantity=body.quantity,
            sort_order=next_order,
        )
    )
    audit(db, request, "wishlists.item.added", auth.user.id, home_id, "wishlist", row.id)
    await db.commit()
    return await _owner_detail_response(db, row)


@router.patch(
    "/{home_id}/wishlists/{wishlist_id}/items/{item_id}",
    response_model=WishlistOwnerDetailResponse,
)
async def update_wishlist_item(
    home_id: uuid.UUID,
    wishlist_id: uuid.UUID,
    item_id: uuid.UUID,
    body: WishlistItemUpdate,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> WishlistOwnerDetailResponse:
    membership = await require_capability(home_id, Capability.wishlists_manage, auth, db)
    await require_entitlement(db, home_id, "wishlists.enabled")
    row = await _get_active_wishlist(db, home_id, wishlist_id)
    await _require_owner_or_admin(row, auth, membership)
    item = await db.scalar(
        select(WishlistItem).where(
            WishlistItem.id == item_id,
            WishlistItem.wishlist_id == row.id,
            WishlistItem.deleted_at.is_(None),
        )
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That item could not be found")

    fields = body.model_fields_set
    if "name" in fields and body.name is not None:
        item.name = body.name.strip()
    if "url" in fields:
        item.url = body.url
    if "price" in fields:
        item.price = body.price
    if "currency" in fields:
        item.currency = body.currency
    if "note" in fields:
        item.note = body.note
    if "image_url" in fields:
        item.image_url = body.image_url
    if "quantity" in fields and body.quantity is not None:
        item.quantity = body.quantity

    await db.commit()
    return await _owner_detail_response(db, row)


@router.delete(
    "/{home_id}/wishlists/{wishlist_id}/items/{item_id}",
    response_model=WishlistOwnerDetailResponse,
)
async def remove_wishlist_item(
    home_id: uuid.UUID,
    wishlist_id: uuid.UUID,
    item_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> WishlistOwnerDetailResponse:
    membership = await require_capability(home_id, Capability.wishlists_manage, auth, db)
    await require_entitlement(db, home_id, "wishlists.enabled")
    row = await _get_active_wishlist(db, home_id, wishlist_id)
    await _require_owner_or_admin(row, auth, membership)
    await db.execute(
        delete(WishlistItem).where(WishlistItem.id == item_id, WishlistItem.wishlist_id == row.id)
    )
    audit(db, request, "wishlists.item.removed", auth.user.id, home_id, "wishlist", row.id)
    await db.commit()
    return await _owner_detail_response(db, row)


@router.post(
    "/{home_id}/wishlists/{wishlist_id}/items/reorder",
    response_model=WishlistOwnerDetailResponse,
)
async def reorder_wishlist_items(
    home_id: uuid.UUID,
    wishlist_id: uuid.UUID,
    body: WishlistItemReorderRequest,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> WishlistOwnerDetailResponse:
    membership = await require_capability(home_id, Capability.wishlists_manage, auth, db)
    await require_entitlement(db, home_id, "wishlists.enabled")
    row = await _get_active_wishlist(db, home_id, wishlist_id, for_update=True)
    await _require_owner_or_admin(row, auth, membership)
    items = await _wishlist_items(db, row.id)
    current_ids = {item.id for item in items}
    if set(body.item_ids) != current_ids or len(body.item_ids) != len(items):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This wishlist's items changed. Reload and try again."
        )
    by_id = {item.id: item for item in items}
    for position, item_id in enumerate(body.item_ids):
        by_id[item_id].sort_order = position
    await db.commit()
    return await _owner_detail_response(db, row)


# ---------------------------------------------------------------------------
# Sharing (Home-scoped, owner/admin-only)
# ---------------------------------------------------------------------------


@router.post(
    "/{home_id}/wishlists/{wishlist_id}/shares/lookup",
    response_model=ShareRecipientLookupResponse,
)
async def lookup_share_recipient(
    home_id: uuid.UUID,
    wishlist_id: uuid.UUID,
    body: ShareRecipientLookupRequest,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ShareRecipientLookupResponse:
    membership = await require_capability(home_id, Capability.wishlists_manage, auth, db)
    await require_entitlement(db, home_id, "wishlists.enabled")
    row = await _get_active_wishlist(db, home_id, wishlist_id)
    await _require_owner_or_admin(row, auth, membership)

    normalised = normalise_email(str(body.email))
    user = await db.scalar(select(User).where(User.email == normalised, User.is_active.is_(True)))
    if user is None:
        return ShareRecipientLookupResponse(existing_user_id=None, existing_user_display_name=None)
    return ShareRecipientLookupResponse(
        existing_user_id=user.id, existing_user_display_name=user.display_name
    )


@router.post("/{home_id}/wishlists/{wishlist_id}/shares", status_code=201)
async def create_share(
    home_id: uuid.UUID,
    wishlist_id: uuid.UUID,
    body: ShareCreateRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ShareResponse | GuestShareCreateResponse:
    membership = await require_capability(home_id, Capability.wishlists_manage, auth, db)
    await require_entitlement(db, home_id, "wishlists.enabled")
    row = await _get_active_wishlist(db, home_id, wishlist_id)
    await _require_owner_or_admin(row, auth, membership)
    await enforce_rate_limit(
        request, settings, "wishlist_share_create", _SHARE_CREATE_RATE_LIMIT, _SHARE_CREATE_RATE_WINDOW
    )

    if body.share_type == "mykhaya_user":
        if body.confirmed_user_id is None or body.recipient_email is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "A confirmed recipient account is required for this share type.",
            )
        # Re-verified server-side rather than trusting the client's earlier
        # lookup response — see ShareCreateRequest.confirmed_user_id's
        # docstring.
        recipient = await db.scalar(
            select(User).where(
                User.id == body.confirmed_user_id,
                User.email == normalise_email(str(body.recipient_email)),
                User.is_active.is_(True),
            )
        )
        if recipient is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That account could not be confirmed.")
        share = WishlistShare(
            wishlist_id=row.id,
            recipient_name=body.recipient_name.strip(),
            recipient_email=normalise_email(str(body.recipient_email)),
            recipient_user_id=recipient.id,
            share_type=WishlistShareType.mykhaya_user,
            created_by=auth.user.id,
        )
        db.add(share)
        await db.flush()
        await notify_wishlist_share(
            db, settings=settings, wishlist=row, share=share, actor=auth.user,
            notification_type="wishlist_share_created", title="Wishlist shared with you",
            body=f'{auth.user.display_name} shared "{row.title}" with you.',
        )
        audit(
            db, request, "wishlists.share.created", auth.user.id, home_id, "wishlist_share", share.id
        )
        await db.commit()
        return ShareResponse(
            id=share.id,
            recipient_name=share.recipient_name,
            share_type="mykhaya_user",
            created_at=share.created_at,
        )

    pin = "".join(secrets.choice(string.digits) for _ in range(6))
    assert is_valid_child_pin(pin)  # same shape as managed-Child PINs, reused deliberately
    share = WishlistShare(
        wishlist_id=row.id,
        recipient_name=body.recipient_name.strip(),
        recipient_email=(normalise_email(str(body.recipient_email)) if body.recipient_email else None),
        share_type=WishlistShareType.guest,
        pin_hash=password_hash.hash(pin),
        created_by=auth.user.id,
    )
    db.add(share)
    await db.flush()
    link_token = derived_token(share.id, _SHARE_TOKEN_PURPOSE, settings.secret_key.get_secret_value())
    audit(db, request, "wishlists.share.created", auth.user.id, home_id, "wishlist_share", share.id)
    await db.commit()
    return GuestShareCreateResponse(
        id=share.id,
        recipient_name=share.recipient_name,
        share_type="guest",
        created_at=share.created_at,
        link_token=link_token,
        pin=pin,
    )


@router.get("/{home_id}/wishlists/{wishlist_id}/shares", response_model=ShareListResponse)
async def list_shares(
    home_id: uuid.UUID,
    wishlist_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> ShareListResponse:
    membership = await require_capability(home_id, Capability.wishlists_manage, auth, db)
    await require_entitlement(db, home_id, "wishlists.enabled")
    row = await _get_active_wishlist(db, home_id, wishlist_id)
    await _require_owner_or_admin(row, auth, membership)
    shares = (
        await db.scalars(
            select(WishlistShare)
            .where(WishlistShare.wishlist_id == row.id)
            .order_by(WishlistShare.created_at.desc())
        )
    ).all()
    return ShareListResponse(
        items=[
            ShareListItemResponse(
                id=share.id,
                recipient_name=share.recipient_name,
                recipient_email=share.recipient_email,
                share_type=share.share_type.value,
                created_at=share.created_at,
                last_accessed_at=share.last_accessed_at,
                revoked=share.revoked_at is not None,
            )
            for share in shares
        ]
    )


@router.post("/{home_id}/wishlists/{wishlist_id}/shares/{share_id}/revoke", status_code=204)
async def revoke_share(
    home_id: uuid.UUID,
    wishlist_id: uuid.UUID,
    share_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    membership = await require_capability(home_id, Capability.wishlists_manage, auth, db)
    await require_entitlement(db, home_id, "wishlists.enabled")
    row = await _get_active_wishlist(db, home_id, wishlist_id)
    await _require_owner_or_admin(row, auth, membership)
    share = await db.scalar(
        select(WishlistShare).where(
            WishlistShare.id == share_id, WishlistShare.wishlist_id == row.id
        )
    )
    if share is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That share could not be found")
    share.revoked_at = datetime.now(UTC)
    # Belt and braces alongside wishlist_guest_context's live revoked_at
    # check — immediately invalidates any already-issued guest session too.
    await db.execute(delete(WishlistGuestSession).where(WishlistGuestSession.share_id == share.id))
    await notify_wishlist_share(
        db, settings=settings, wishlist=row, share=share, actor=auth.user,
        notification_type="wishlist_share_revoked", title="Wishlist access removed",
        body=f'{auth.user.display_name} removed your access to "{row.title}".',
    )
    audit(db, request, "wishlists.share.revoked", auth.user.id, home_id, "wishlist_share", share.id)
    await db.commit()


@router.post(
    "/{home_id}/wishlists/{wishlist_id}/shares/{share_id}/regenerate-guest-pin",
    response_model=GuestShareCreateResponse,
)
async def regenerate_guest_share(
    home_id: uuid.UUID,
    wishlist_id: uuid.UUID,
    share_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> GuestShareCreateResponse:
    """Revoke-and-reissue under one endpoint: the share's public token is
    derived from its row id (WishlistShare has no separate token column —
    see its docstring), so a *compromised link* cannot be rotated without a
    new share row. Revoking the old share and creating a fresh one for the
    same recipient achieves the same outcome (old link+PIN dead, new
    link+PIN issued) without needing a second schema concept."""
    membership = await require_capability(home_id, Capability.wishlists_manage, auth, db)
    await require_entitlement(db, home_id, "wishlists.enabled")
    row = await _get_active_wishlist(db, home_id, wishlist_id)
    await _require_owner_or_admin(row, auth, membership)
    old = await db.scalar(
        select(WishlistShare).where(
            WishlistShare.id == share_id,
            WishlistShare.wishlist_id == row.id,
            WishlistShare.share_type == WishlistShareType.guest,
        )
    )
    if old is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That share could not be found")
    old.revoked_at = datetime.now(UTC)
    await db.execute(delete(WishlistGuestSession).where(WishlistGuestSession.share_id == old.id))

    pin = "".join(secrets.choice(string.digits) for _ in range(6))
    new_share = WishlistShare(
        wishlist_id=row.id,
        recipient_name=old.recipient_name,
        recipient_email=old.recipient_email,
        share_type=WishlistShareType.guest,
        pin_hash=password_hash.hash(pin),
        created_by=auth.user.id,
    )
    db.add(new_share)
    await db.flush()
    link_token = derived_token(
        new_share.id, _SHARE_TOKEN_PURPOSE, settings.secret_key.get_secret_value()
    )
    audit(
        db, request, "wishlists.share.regenerated", auth.user.id, home_id, "wishlist_share", new_share.id
    )
    await db.commit()
    return GuestShareCreateResponse(
        id=new_share.id,
        recipient_name=new_share.recipient_name,
        share_type="guest",
        created_at=new_share.created_at,
        link_token=link_token,
        pin=pin,
    )


# ---------------------------------------------------------------------------
# Top-level: view + reserve (owner, home member, or share recipient)
# ---------------------------------------------------------------------------


@shared_router.get("/wishlists/shared-with-me", response_model=WishlistListResponse)
async def shared_with_me(
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> WishlistListResponse:
    shares = (
        await db.scalars(
            select(WishlistShare).where(
                WishlistShare.recipient_user_id == auth.user.id,
                WishlistShare.share_type == WishlistShareType.mykhaya_user,
                WishlistShare.revoked_at.is_(None),
            )
        )
    ).all()
    wishlist_ids = [share.wishlist_id for share in shares]
    if not wishlist_ids:
        return WishlistListResponse(items=[])
    rows = (
        await db.scalars(
            select(Wishlist).where(Wishlist.id.in_(wishlist_ids), Wishlist.deleted_at.is_(None))
        )
    ).all()
    if not rows:
        return WishlistListResponse(items=[])
    counts = dict(
        (
            await db.execute(
                select(WishlistItem.wishlist_id, func.count())
                .where(
                    WishlistItem.wishlist_id.in_([row.id for row in rows]),
                    WishlistItem.deleted_at.is_(None),
                )
                .group_by(WishlistItem.wishlist_id)
            )
        ).all()
    )
    owner_names = dict(
        (
            await db.execute(
                select(User.id, User.display_name).where(
                    User.id.in_({row.owner_user_id for row in rows})
                )
            )
        ).all()
    )
    return WishlistListResponse(
        items=[
            await _summary_response(
                db, row, counts.get(row.id, 0), owner_names.get(row.owner_user_id, ""), auth.user.id
            )
            for row in rows
        ]
    )


async def _require_module_enabled(db: AsyncSession, home_id: uuid.UUID) -> None:
    await require_feature(db, FeatureKey.wish_lists, home_id)
    await require_entitlement(db, home_id, "wishlists.enabled")


@shared_router.get("/wishlists/{wishlist_id}", response_model=None)
async def get_wishlist_top_level(
    wishlist_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> WishlistDetailResponse:
    row = await _get_active_wishlist_any_home(db, wishlist_id)
    await _require_module_enabled(db, row.home_id)
    if row.owner_user_id == auth.user.id:
        return await _owner_detail_response(db, row)
    await _resolve_non_owner_access(db, row, auth)
    return await _viewer_detail_response(db, row)


async def _get_active_item(db: AsyncSession, wishlist_id: uuid.UUID, item_id: uuid.UUID) -> WishlistItem:
    item = await db.scalar(
        select(WishlistItem).where(
            WishlistItem.id == item_id,
            WishlistItem.wishlist_id == wishlist_id,
            WishlistItem.deleted_at.is_(None),
        )
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That item could not be found")
    return item


async def _do_reserve(
    db: AsyncSession,
    item: WishlistItem,
    status_value: WishlistReservationStatus,
    actor_type: WishlistReservationActorType,
    actor_user_id: uuid.UUID | None,
    actor_share_id: uuid.UUID | None,
    buyer_display_name: str,
) -> WishlistItemReservation:
    existing = await db.scalar(
        select(WishlistItemReservation)
        .where(WishlistItemReservation.wishlist_item_id == item.id)
        .with_for_update()
    )
    if existing is not None:
        # Deliberately generic — never reveals who holds the existing
        # reservation to the caller attempting a new one (co-shoppers who
        # are *already* allowed to see "Reserved by X" saw that on the
        # detail endpoint before ever reaching here).
        raise HTTPException(status.HTTP_409_CONFLICT, "That item is no longer available.")
    reservation = WishlistItemReservation(
        wishlist_item_id=item.id,
        status=status_value,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        actor_share_id=actor_share_id,
        buyer_display_name=buyer_display_name,
    )
    db.add(reservation)
    try:
        await db.commit()
    except IntegrityError:
        # uq_wishlist_item_reservation as the final backstop against two
        # concurrent reserves racing past the with_for_update check above
        # (which has nothing to lock until a row exists) — same generic
        # message, still no reserver identity leaked.
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That item is no longer available.") from None
    return reservation


async def _do_release(
    db: AsyncSession,
    item: WishlistItem,
    *,
    actor_user_id: uuid.UUID | None,
    actor_share_id: uuid.UUID | None,
) -> None:
    reservation = await db.scalar(
        select(WishlistItemReservation)
        .where(WishlistItemReservation.wishlist_item_id == item.id)
        .with_for_update()
    )
    if reservation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That item is not currently reserved.")
    owns_it = (actor_user_id is not None and reservation.actor_user_id == actor_user_id) or (
        actor_share_id is not None and reservation.actor_share_id == actor_share_id
    )
    if not owns_it:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only whoever reserved this item can release it."
        )
    await db.delete(reservation)
    await db.commit()


@shared_router.post(
    "/wishlists/{wishlist_id}/items/{item_id}/reserve", response_model=WishlistItemViewerResponse
)
async def reserve_item(
    wishlist_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ReserveItemRequest,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> WishlistItemViewerResponse:
    row = await _get_active_wishlist_any_home(db, wishlist_id)
    await _require_module_enabled(db, row.home_id)
    if row.owner_user_id == auth.user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You can't reserve items on your own wishlist."
        )
    await _resolve_non_owner_access(db, row, auth)
    item = await _get_active_item(db, row.id, item_id)
    name = body.buyer_display_name or auth.user.display_name
    reservation = await _do_reserve(
        db, item, WishlistReservationStatus.reserved, WishlistReservationActorType.member,
        auth.user.id, None, name,
    )
    return _viewer_item_response(item, reservation)


@shared_router.post(
    "/wishlists/{wishlist_id}/items/{item_id}/mark-bought", response_model=WishlistItemViewerResponse
)
async def mark_item_bought(
    wishlist_id: uuid.UUID,
    item_id: uuid.UUID,
    body: MarkBoughtRequest,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> WishlistItemViewerResponse:
    row = await _get_active_wishlist_any_home(db, wishlist_id)
    await _require_module_enabled(db, row.home_id)
    if row.owner_user_id == auth.user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You can't reserve items on your own wishlist."
        )
    await _resolve_non_owner_access(db, row, auth)
    item = await _get_active_item(db, row.id, item_id)
    name = body.buyer_display_name or auth.user.display_name
    reservation = await _do_reserve(
        db, item, WishlistReservationStatus.bought, WishlistReservationActorType.member,
        auth.user.id, None, name,
    )
    return _viewer_item_response(item, reservation)


@shared_router.post(
    "/wishlists/{wishlist_id}/items/{item_id}/release", response_model=WishlistItemViewerResponse
)
async def release_item(
    wishlist_id: uuid.UUID,
    item_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> WishlistItemViewerResponse:
    row = await _get_active_wishlist_any_home(db, wishlist_id)
    await _require_module_enabled(db, row.home_id)
    if row.owner_user_id == auth.user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You can't reserve items on your own wishlist."
        )
    await _resolve_non_owner_access(db, row, auth)
    item = await _get_active_item(db, row.id, item_id)
    await _do_release(db, item, actor_user_id=auth.user.id, actor_share_id=None)
    return _viewer_item_response(item, None)


# ---------------------------------------------------------------------------
# Guest flow
# ---------------------------------------------------------------------------


@guest_router.post("/wishlist/share/{token}/verify", response_model=GuestVerifyResponse)
async def verify_guest_share(
    token: str,
    body: GuestVerifyRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> GuestVerifyResponse:
    await enforce_rate_limit(
        request, settings, "wishlist_guest_pin", _GUEST_PIN_RATE_LIMIT, _GUEST_PIN_RATE_WINDOW
    )
    share_id = decode_derived_token(token, _SHARE_TOKEN_PURPOSE, settings.secret_key.get_secret_value())
    share = None
    if share_id is not None:
        share = await db.scalar(
            select(WishlistShare).where(
                WishlistShare.id == share_id,
                WishlistShare.share_type == WishlistShareType.guest,
                WishlistShare.revoked_at.is_(None),
            )
        )
    # Timing-safe negative lookup — same DUMMY_HASH pattern routers.auth uses
    # for login/child-PIN, so verification takes the same time whether the
    # token/share resolved or not.
    stored_hash = share.pin_hash if share is not None and share.pin_hash else DUMMY_HASH
    valid = verify_password(body.pin, stored_hash)
    if share is None or not valid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That link or PIN is invalid.")

    share.last_accessed_at = datetime.now(UTC)
    raw_token = secrets.token_urlsafe(32)
    session = WishlistGuestSession(
        share_id=share.id,
        token_hash=hash_secret(raw_token, settings.secret_key.get_secret_value()),
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    db.add(session)
    await db.commit()
    csrf = secrets.token_urlsafe(24)
    set_guest_cookies(response, raw_token, csrf, settings)
    return GuestVerifyResponse(recipient_name=share.recipient_name)


@guest_router.post("/wishlist/guest/logout", status_code=204)
async def guest_logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    require_guest_csrf(request, settings)
    raw = request.cookies.get(GUEST_COOKIE_NAME)
    if raw:
        digest = hash_secret(raw, settings.secret_key.get_secret_value())
        await db.execute(delete(WishlistGuestSession).where(WishlistGuestSession.token_hash == digest))
        await db.commit()
    clear_guest_cookies(response, settings)


@guest_router.get("/wishlist/guest/wishlist", response_model=WishlistViewerDetailResponse)
async def guest_get_wishlist(
    guest: WishlistGuestContext = Depends(wishlist_guest_context),
    db: AsyncSession = Depends(get_db),
) -> WishlistViewerDetailResponse:
    row = await _get_active_wishlist_any_home(db, guest.share.wishlist_id)
    await _require_module_enabled(db, row.home_id)
    return await _viewer_detail_response(db, row)


@guest_router.post(
    "/wishlist/guest/items/{item_id}/reserve", response_model=WishlistItemViewerResponse
)
async def guest_reserve_item(
    item_id: uuid.UUID,
    body: ReserveItemRequest,
    request: Request,
    guest: WishlistGuestContext = Depends(wishlist_guest_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WishlistItemViewerResponse:
    require_guest_csrf(request, settings)
    row = await _get_active_wishlist_any_home(db, guest.share.wishlist_id)
    await _require_module_enabled(db, row.home_id)
    item = await _get_active_item(db, row.id, item_id)
    name = body.buyer_display_name or guest.share.recipient_name
    reservation = await _do_reserve(
        db, item, WishlistReservationStatus.reserved, WishlistReservationActorType.guest,
        None, guest.share.id, name,
    )
    return _viewer_item_response(item, reservation)


@guest_router.post(
    "/wishlist/guest/items/{item_id}/mark-bought", response_model=WishlistItemViewerResponse
)
async def guest_mark_item_bought(
    item_id: uuid.UUID,
    body: MarkBoughtRequest,
    request: Request,
    guest: WishlistGuestContext = Depends(wishlist_guest_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WishlistItemViewerResponse:
    require_guest_csrf(request, settings)
    row = await _get_active_wishlist_any_home(db, guest.share.wishlist_id)
    await _require_module_enabled(db, row.home_id)
    item = await _get_active_item(db, row.id, item_id)
    name = body.buyer_display_name or guest.share.recipient_name
    reservation = await _do_reserve(
        db, item, WishlistReservationStatus.bought, WishlistReservationActorType.guest,
        None, guest.share.id, name,
    )
    return _viewer_item_response(item, reservation)


@guest_router.post(
    "/wishlist/guest/items/{item_id}/release", response_model=WishlistItemViewerResponse
)
async def guest_release_item(
    item_id: uuid.UUID,
    request: Request,
    guest: WishlistGuestContext = Depends(wishlist_guest_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WishlistItemViewerResponse:
    require_guest_csrf(request, settings)
    row = await _get_active_wishlist_any_home(db, guest.share.wishlist_id)
    await _require_module_enabled(db, row.home_id)
    item = await _get_active_item(db, row.id, item_id)
    await _do_release(db, item, actor_user_id=None, actor_share_id=guest.share.id)
    return _viewer_item_response(item, None)
