"""Wishlists V1 request/response schemas — split out from schemas.py as its
own file, matching billing_schemas.py's precedent for a large, self-contained
schema group.

The owner/viewer item-response split (WishlistItemOwnerResponse vs
WishlistItemViewerResponse) is deliberate and load-bearing: the wishlist
owner must never learn whether their own items are reserved/bought (see
models.py's Wishlists section and routers.wishlists' serialization). Using
two distinct Pydantic classes makes it structurally impossible for a
reservation field to leak into an owner response by omission at a call
site — there is no shared base class carrying the reservation fields that a
future edit could accidentally re-expose.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import EmailStr, Field

from mykhaya.models import WishlistOccasion
from mykhaya.schemas import StrictModel

ReservationStatus = Literal["available", "reserved", "bought"]


# ---------------------------------------------------------------------------
# Wishlist
# ---------------------------------------------------------------------------


class WishlistCreate(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    occasion: WishlistOccasion
    occasion_date: date | None = None
    description: str | None = Field(default=None, max_length=1000)
    # Only honoured for a Home Admin creating on a Child's behalf — the
    # router enforces owner_user_id == caller unless the caller is
    # home_admin. Defaults to the caller when omitted.
    owner_user_id: uuid.UUID | None = None


class WishlistUpdateRequest(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    occasion: WishlistOccasion
    occasion_date: date | None = None
    description: str | None = Field(default=None, max_length=1000)
    expected_updated_at: datetime


class WishlistVisibilityUpdateRequest(StrictModel):
    """Toggles home_visible only — never touches any WishlistShare row. See
    models.Wishlist.home_visible's docstring: Home visibility and
    per-recipient sharing are deliberately independent, both ways."""

    enabled: bool


class WishlistSummaryResponse(StrictModel):
    """No item-level detail at all, so no reservation surface exists here
    for any viewer — this is deliberately safe to share verbatim between the
    owner's own listing and a co-shopper's Home-wide browse.

    share_count is only ever a real count for the caller's own wishlist
    (is_owner == True) — the router zeroes it out for every other row so a
    fellow Home member browsing a home_visible wishlist can't learn how many
    people it's individually been shared with. Recipient identity never
    appears here at all; that's only ever returned by the dedicated
    GET .../shares endpoint, to the owner/admin only."""

    id: uuid.UUID
    home_id: uuid.UUID
    title: str
    occasion: WishlistOccasion
    occasion_date: date | None
    description: str | None
    owner_user_id: uuid.UUID
    owner_display_name: str
    item_count: int
    is_owner: bool
    home_visible: bool
    share_count: int
    created_at: datetime
    updated_at: datetime


class WishlistListResponse(StrictModel):
    items: list[WishlistSummaryResponse]


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


class WishlistItemCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    url: str | None = Field(default=None, max_length=2000)
    price: Decimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    note: str | None = Field(default=None, max_length=500)
    image_url: str | None = Field(default=None, max_length=2000)
    quantity: int = Field(default=1, ge=1)


class WishlistItemUpdate(StrictModel):
    """Only fields actually present in the request body are applied — same
    partial-update convention as ListItemUpdate in schemas.py."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    url: str | None = Field(default=None, max_length=2000)
    price: Decimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    note: str | None = Field(default=None, max_length=500)
    image_url: str | None = Field(default=None, max_length=2000)
    quantity: int | None = Field(default=None, ge=1)


class WishlistItemReorderRequest(StrictModel):
    item_ids: list[uuid.UUID]


class WishlistItemOwnerResponse(StrictModel):
    """Never includes any reservation-related field — not even a nullable
    placeholder. See module docstring."""

    id: uuid.UUID
    name: str
    url: str | None
    price: Decimal | None
    currency: str | None
    note: str | None
    image_url: str | None
    quantity: int
    sort_order: int
    created_at: datetime
    updated_at: datetime


class WishlistItemViewerResponse(StrictModel):
    id: uuid.UUID
    name: str
    url: str | None
    price: Decimal | None
    currency: str | None
    note: str | None
    image_url: str | None
    quantity: int
    sort_order: int
    created_at: datetime
    updated_at: datetime
    reservation_status: ReservationStatus
    reserved_by_display_name: str | None


class WishlistOwnerDetailResponse(StrictModel):
    id: uuid.UUID
    home_id: uuid.UUID
    title: str
    occasion: WishlistOccasion
    occasion_date: date | None
    description: str | None
    owner_user_id: uuid.UUID
    home_visible: bool
    share_count: int
    created_at: datetime
    updated_at: datetime
    items: list[WishlistItemOwnerResponse]


class WishlistViewerDetailResponse(StrictModel):
    id: uuid.UUID
    home_id: uuid.UUID
    title: str
    occasion: WishlistOccasion
    occasion_date: date | None
    description: str | None
    owner_user_id: uuid.UUID
    owner_display_name: str
    created_at: datetime
    updated_at: datetime
    items: list[WishlistItemViewerResponse]


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------


class ReserveItemRequest(StrictModel):
    # Optional — the router defaults this to the actor's own display name
    # (member) or the share's recipient_name (guest) when omitted.
    buyer_display_name: str | None = Field(default=None, min_length=1, max_length=100)


class MarkBoughtRequest(StrictModel):
    buyer_display_name: str | None = Field(default=None, min_length=1, max_length=100)


# ---------------------------------------------------------------------------
# Sharing — MyKhaya-to-MyKhaya
# ---------------------------------------------------------------------------


class ShareRecipientLookupRequest(StrictModel):
    email: EmailStr


class ShareRecipientLookupResponse(StrictModel):
    """Deliberately minimal — confirms an account with this email exists so
    the sharer can decide whether to proceed, without revealing anything
    about that account's Home, membership size, or activity."""

    existing_user_id: uuid.UUID | None
    existing_user_display_name: str | None


class ShareCreateRequest(StrictModel):
    recipient_name: str = Field(min_length=1, max_length=100)
    recipient_email: EmailStr | None = None
    share_type: Literal["mykhaya_user", "guest"]
    # Required (and re-verified server-side) for share_type == "mykhaya_user"
    # — the explicit confirmation step described in the product spec, from
    # a prior ShareRecipientLookupResponse. Never trusted blindly: the
    # router re-resolves this id against recipient_email itself.
    confirmed_user_id: uuid.UUID | None = None


class ShareResponse(StrictModel):
    id: uuid.UUID
    recipient_name: str
    share_type: Literal["mykhaya_user", "guest"]
    created_at: datetime


class GuestShareCreateResponse(ShareResponse):
    """The plaintext PIN and link token are returned exactly once, at
    creation/regeneration time, and never again — matching the fact that
    WishlistShare.pin_hash never stores them in recoverable form."""

    link_token: str
    pin: str


class ShareListItemResponse(StrictModel):
    id: uuid.UUID
    recipient_name: str
    recipient_email: str | None
    share_type: Literal["mykhaya_user", "guest"]
    created_at: datetime
    last_accessed_at: datetime | None
    revoked: bool


class ShareListResponse(StrictModel):
    items: list[ShareListItemResponse]


# ---------------------------------------------------------------------------
# Guest access
# ---------------------------------------------------------------------------


class GuestVerifyRequest(StrictModel):
    pin: str = Field(min_length=4, max_length=6)


class GuestVerifyResponse(StrictModel):
    recipient_name: str


# ---------------------------------------------------------------------------
# Link preview (server-side URL metadata fetch — see wishlist_link_preview.py)
# ---------------------------------------------------------------------------


class LinkPreviewRequest(StrictModel):
    url: str = Field(min_length=1, max_length=2000)


class LinkPreviewResponse(StrictModel):
    """Stateless — this endpoint never touches item storage, it only ever
    returns what it found (or all-None fields, on any failure/SSRF-block, so
    a blocked/unreachable host is indistinguishable from a page with no
    metadata at all). Deciding whether to overwrite an in-progress form's
    fields with these values is entirely the frontend's responsibility."""

    title: str | None = None
    image_url: str | None = None
    description: str | None = None
    price: Decimal | None = None
    currency: str | None = None
