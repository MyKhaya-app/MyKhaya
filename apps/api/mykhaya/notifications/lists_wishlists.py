"""Actionable Lists and Wishlist notifications.

Mutations remain silent by default. This module contains only notifications for
access/assignment changes and routes them through the shared notification engine.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.entitlements import has_entitlement
from mykhaya.features import is_feature_enabled
from mykhaya.models import (
    FeatureKey,
    HouseholdList,
    HouseholdListItem,
    User,
    Wishlist,
    WishlistShare,
)
from mykhaya.notifications.deep_links import target
from mykhaya.notifications.engine import notify
from mykhaya.notifications.templates import render_notification


async def _wishlists_notification_eligible(db: AsyncSession, group_id: uuid.UUID) -> bool:
    """Whether a Home is currently eligible to receive a Wishlists-owned
    notification (Phase 3A) — checked independently here even though every
    caller (routers.wishlists) has already required wishlists.enabled
    moments earlier for the mutation that triggered it, matching this
    workstream's "self-defending delivery" principle rather than trusting
    the caller alone."""
    return (
        await is_feature_enabled(db, FeatureKey.wish_lists, group_id)
        and await has_entitlement(db, group_id, "wishlists.enabled")
        and await is_feature_enabled(db, FeatureKey.notifications, group_id)
    )


async def _lists_notification_eligible(db: AsyncSession, group_id: uuid.UUID) -> bool:
    """Whether a Home is currently eligible to receive a Lists-owned
    notification (Phase 3A) — checked independently here even though every
    caller (routers.lists) has already required lists.enabled moments
    earlier for the mutation that triggered it. lists.enabled is True on
    both Free and Family (Free is bounded by lists.max_lists, a numeric
    limit, never a boolean gate) — but that commercial entitlement is a
    separate concern from whether the Home Admin has switched the Lists
    *module* off (FeatureKey.shopping) or the platform has, either of
    which must still stop this notification independently, exactly like
    every other module here. The Free 2-list numeric model itself is
    unaffected — this never checks list count/over-limit state, only
    whether Lists is currently a reachable module at all."""
    return (
        await is_feature_enabled(db, FeatureKey.shopping, group_id)
        and await has_entitlement(db, group_id, "lists.enabled")
        and await is_feature_enabled(db, FeatureKey.notifications, group_id)
    )


async def notify_list_assignment(
    db: AsyncSession,
    *,
    settings: Settings,
    item: HouseholdListItem,
    list_row: HouseholdList,
    actor: User,
    recipient_user_id: uuid.UUID,
) -> None:
    if recipient_user_id == actor.id:
        return
    if not await _lists_notification_eligible(db, list_row.group_id):
        return
    title, body = await render_notification(
        db,
        "list_item_assigned",
        {
            "actor_display_name": actor.display_name,
            "item_name": item.text,
            "list_name": list_row.name,
        },
    )
    await notify(
        db,
        settings=settings,
        recipient_user_id=recipient_user_id,
        notification_type="list_item_assigned",
        title=title,
        body=body,
        idempotency_key=f"list_item_assigned:{item.id}:{recipient_user_id}",
        group_id=list_row.group_id,
        related_entity_type="household_list_item",
        related_entity_id=item.id,
        deep_link=target("list", list_row.id),
        allow_email=False,
    )


async def notify_wishlist_share(
    db: AsyncSession,
    *,
    settings: Settings,
    wishlist: Wishlist,
    share: WishlistShare,
    actor: User,
    notification_type: str,
    title: str,
    body: str,
) -> None:
    if share.recipient_user_id is None or share.recipient_user_id == actor.id:
        return
    await notify_wishlist_recipient(
        db,
        settings=settings,
        wishlist=wishlist,
        actor=actor,
        recipient_user_id=share.recipient_user_id,
        notification_type=notification_type,
        title=title,
        body=body,
        idempotency_key=f"{notification_type}:{share.id}:{share.recipient_user_id}",
    )


async def notify_wishlist_recipient(
    db: AsyncSession,
    *,
    settings: Settings,
    wishlist: Wishlist,
    actor: User,
    recipient_user_id: uuid.UUID,
    notification_type: str,
    title: str,
    body: str,
    idempotency_key: str,
) -> None:
    if recipient_user_id == actor.id:
        return
    if not await _wishlists_notification_eligible(db, wishlist.home_id):
        return
    await notify(
        db,
        settings=settings,
        recipient_user_id=recipient_user_id,
        notification_type=notification_type,
        title=title,
        body=body,
        idempotency_key=idempotency_key,
        group_id=wishlist.home_id,
        related_entity_type="wishlist",
        related_entity_id=wishlist.id,
        deep_link=target("wishlist", wishlist.id),
        allow_email=False,
    )
