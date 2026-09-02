"""Actionable Lists and Wishlist notifications.

Mutations remain silent by default. This module contains only notifications for
access/assignment changes and routes them through the shared notification engine.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.models import HouseholdList, HouseholdListItem, User, Wishlist, WishlistShare
from mykhaya.notifications.deep_links import target
from mykhaya.notifications.engine import notify


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
    await notify(
        db,
        settings=settings,
        recipient_user_id=recipient_user_id,
        notification_type="list_item_assigned",
        title="List item assigned",
        body=f'{actor.display_name} assigned "{item.text}" to you on {list_row.name}.',
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
