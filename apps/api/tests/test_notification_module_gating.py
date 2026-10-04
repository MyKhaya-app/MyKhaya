"""Phase 3A: background/helper notification paths must independently
respect their owning module's platform state and commercial entitlement,
never trust the calling router alone — see docs/architecture/
notification-engine.md "Module gating". Service-level tests against the
small per-file eligibility helpers directly, mirroring
mykhaya.notifications.nudges.is_nudges_notification_eligible's own
coverage style; the scheduled-job scan/deliver functions themselves are
covered in test_household_routines.py, test_reminders.py and
test_calendar_reminders.py.
"""

import uuid

import pytest
from sqlalchemy import select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import ensure_home_subscription, get_home_subscription
from mykhaya.models import (
    FeatureFlag,
    FeatureKey,
    FeatureOverride,
    Group,
    HouseholdList,
    HouseholdListItem,
    Notification,
    SubscriptionPlan,
    User,
)
from mykhaya.notifications.calendar_shares import _external_sharing_notification_eligible
from mykhaya.notifications.lists_wishlists import (
    _lists_notification_eligible,
    _wishlists_notification_eligible,
    notify_list_assignment,
)
from mykhaya.notifications.nudges import is_nudges_notification_eligible


async def _make_home(name: str = "Test Home") -> uuid.UUID:
    async with SessionFactory() as db:
        user = User(email=f"owner-{uuid.uuid4()}@example.com", display_name="Owner")
        db.add(user)
        await db.flush()
        group = Group(name=name, created_by=user.id)
        db.add(group)
        await db.commit()
        await ensure_home_subscription(db, group.id)
        await db.commit()
        return group.id


async def _set_plan(home_id: uuid.UUID, plan: SubscriptionPlan) -> None:
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        subscription.plan = plan
        await db.commit()


async def _set_override(home_id: uuid.UUID, feature_key: FeatureKey, *, enabled: bool) -> None:
    async with SessionFactory() as db:
        db.add(FeatureOverride(feature_key=feature_key, group_id=home_id, enabled=enabled))
        await db.commit()


async def _set_platform_flag(feature_key: FeatureKey, *, enabled: bool) -> None:
    """External sharing (Beta) is not globally enabled by default — unlike
    Calendar/Lists/Meals/Wishlists/Nudges/Notifications, no migration has
    promoted it — so a test exercising the eligible path must opt the
    platform flag in itself, exactly like a PCC operator would."""
    async with SessionFactory() as db:
        row = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == feature_key))
        if row is None:
            db.add(FeatureFlag(key=feature_key, enabled=enabled))
        else:
            row.enabled = enabled
        await db.commit()


# ---------------------------------------------------------------------------
# Wishlists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wishlists_notification_ineligible_when_module_disabled() -> None:
    home_id = await _make_home()
    await _set_plan(home_id, SubscriptionPlan.family)
    await _set_override(home_id, FeatureKey.wish_lists, enabled=False)
    await _set_override(home_id, FeatureKey.notifications, enabled=True)
    async with SessionFactory() as db:
        assert await _wishlists_notification_eligible(db, home_id) is False


@pytest.mark.asyncio
async def test_wishlists_notification_ineligible_on_free_plan() -> None:
    home_id = await _make_home()
    await _set_override(home_id, FeatureKey.wish_lists, enabled=True)
    await _set_override(home_id, FeatureKey.notifications, enabled=True)
    async with SessionFactory() as db:
        # A fresh Home is Free by default — wishlists.enabled is False there.
        assert await _wishlists_notification_eligible(db, home_id) is False


@pytest.mark.asyncio
async def test_wishlists_notification_ineligible_when_notifications_disabled() -> None:
    home_id = await _make_home()
    await _set_plan(home_id, SubscriptionPlan.family)
    await _set_override(home_id, FeatureKey.wish_lists, enabled=True)
    await _set_override(home_id, FeatureKey.notifications, enabled=False)
    async with SessionFactory() as db:
        assert await _wishlists_notification_eligible(db, home_id) is False


@pytest.mark.asyncio
async def test_wishlists_notification_eligible_on_family_with_module_and_notifications_on() -> None:
    home_id = await _make_home()
    await _set_plan(home_id, SubscriptionPlan.family)
    await _set_override(home_id, FeatureKey.wish_lists, enabled=True)
    await _set_override(home_id, FeatureKey.notifications, enabled=True)
    async with SessionFactory() as db:
        assert await _wishlists_notification_eligible(db, home_id) is True


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lists_notification_ineligible_when_module_disabled() -> None:
    home_id = await _make_home()
    await _set_plan(home_id, SubscriptionPlan.family)
    await _set_override(home_id, FeatureKey.shopping, enabled=False)
    await _set_override(home_id, FeatureKey.notifications, enabled=True)
    async with SessionFactory() as db:
        assert await _lists_notification_eligible(db, home_id) is False


@pytest.mark.asyncio
async def test_lists_notification_ineligible_when_notifications_disabled() -> None:
    home_id = await _make_home()
    await _set_override(home_id, FeatureKey.shopping, enabled=True)
    await _set_override(home_id, FeatureKey.notifications, enabled=False)
    async with SessionFactory() as db:
        assert await _lists_notification_eligible(db, home_id) is False


@pytest.mark.asyncio
async def test_lists_notification_eligible_with_module_and_notifications_on() -> None:
    """lists.enabled is True on both Free and Family — the eligible path
    only needs the module and Notifications on, no plan upgrade, unlike
    Wishlists/Nudges/External Sharing. The Free 2-list numeric model is a
    separate, unaffected concern (see _lists_notification_eligible's own
    docstring)."""
    home_id = await _make_home()
    await _set_override(home_id, FeatureKey.shopping, enabled=True)
    await _set_override(home_id, FeatureKey.notifications, enabled=True)
    async with SessionFactory() as db:
        assert await _lists_notification_eligible(db, home_id) is True


async def _make_list_with_item(home_id: uuid.UUID, creator_id: uuid.UUID) -> HouseholdListItem:
    async with SessionFactory() as db:
        list_row = HouseholdList(group_id=home_id, name="Groceries", created_by=creator_id)
        db.add(list_row)
        await db.flush()
        item = HouseholdListItem(list_id=list_row.id, text="Milk", created_by=creator_id)
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return item


async def _notifications_for(recipient_id: uuid.UUID) -> list[Notification]:
    async with SessionFactory() as db:
        return list(
            (
                await db.scalars(
                    select(Notification).where(Notification.recipient_user_id == recipient_id)
                )
            ).all()
        )


@pytest.mark.asyncio
async def test_list_assignment_notification_not_sent_when_lists_module_disabled() -> None:
    home_id = await _make_home()
    await _set_plan(home_id, SubscriptionPlan.family)
    await _set_override(home_id, FeatureKey.notifications, enabled=True)
    await _set_override(home_id, FeatureKey.shopping, enabled=False)
    async with SessionFactory() as db:
        actor = User(email=f"actor-{uuid.uuid4()}@example.com", display_name="Actor")
        recipient = User(email=f"recipient-{uuid.uuid4()}@example.com", display_name="Recipient")
        db.add_all([actor, recipient])
        await db.commit()
        item = await _make_list_with_item(home_id, actor.id)
        list_row = await db.get(HouseholdList, item.list_id)
        assert list_row is not None

        await notify_list_assignment(
            db,
            settings=get_settings(),
            item=item,
            list_row=list_row,
            actor=actor,
            recipient_user_id=recipient.id,
        )
        await db.commit()
        assert await _notifications_for(recipient.id) == []


@pytest.mark.asyncio
async def test_list_assignment_notification_not_sent_when_notifications_disabled() -> None:
    home_id = await _make_home()
    await _set_plan(home_id, SubscriptionPlan.family)
    await _set_override(home_id, FeatureKey.shopping, enabled=True)
    await _set_override(home_id, FeatureKey.notifications, enabled=False)
    async with SessionFactory() as db:
        actor = User(email=f"actor-{uuid.uuid4()}@example.com", display_name="Actor")
        recipient = User(email=f"recipient-{uuid.uuid4()}@example.com", display_name="Recipient")
        db.add_all([actor, recipient])
        await db.commit()
        item = await _make_list_with_item(home_id, actor.id)
        list_row = await db.get(HouseholdList, item.list_id)
        assert list_row is not None

        await notify_list_assignment(
            db,
            settings=get_settings(),
            item=item,
            list_row=list_row,
            actor=actor,
            recipient_user_id=recipient.id,
        )
        await db.commit()
        assert await _notifications_for(recipient.id) == []


@pytest.mark.asyncio
async def test_list_assignment_notification_sent_when_lists_and_notifications_enabled() -> None:
    """Regression: the existing, already-eligible path must keep working —
    Lists module on, Notifications on (Free is fine here too, since
    lists.enabled doesn't require Family)."""
    home_id = await _make_home()
    await _set_override(home_id, FeatureKey.shopping, enabled=True)
    await _set_override(home_id, FeatureKey.notifications, enabled=True)
    async with SessionFactory() as db:
        actor = User(email=f"actor-{uuid.uuid4()}@example.com", display_name="Actor")
        recipient = User(email=f"recipient-{uuid.uuid4()}@example.com", display_name="Recipient")
        db.add_all([actor, recipient])
        await db.commit()
        item = await _make_list_with_item(home_id, actor.id)
        list_row = await db.get(HouseholdList, item.list_id)
        assert list_row is not None

        await notify_list_assignment(
            db,
            settings=get_settings(),
            item=item,
            list_row=list_row,
            actor=actor,
            recipient_user_id=recipient.id,
        )
        await db.commit()
        notifications = await _notifications_for(recipient.id)
        assert len(notifications) == 1
        assert notifications[0].notification_type == "list_item_assigned"


@pytest.mark.asyncio
async def test_disabling_lists_does_not_suppress_wishlists_notifications() -> None:
    """Disabling one module must never affect another's eligibility — the
    Lists-specific and Wishlists-specific checks are fully independent."""
    home_id = await _make_home()
    await _set_plan(home_id, SubscriptionPlan.family)
    await _set_override(home_id, FeatureKey.shopping, enabled=False)
    await _set_override(home_id, FeatureKey.wish_lists, enabled=True)
    await _set_override(home_id, FeatureKey.notifications, enabled=True)
    async with SessionFactory() as db:
        assert await _lists_notification_eligible(db, home_id) is False
        assert await _wishlists_notification_eligible(db, home_id) is True


# ---------------------------------------------------------------------------
# External Sharing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_external_sharing_notification_ineligible_when_not_enabled_for_the_home() -> None:
    """A Home override can only narrow, never bypass, the global platform
    flag (see is_feature_enabled) — forcing it off here exercises the same
    "not currently enabled" outcome regardless of the platform flag's own
    live state; the fuller platform-vs-Home precedence matrix is covered in
    test_feature_precedence.py."""
    home_id = await _make_home()
    await _set_plan(home_id, SubscriptionPlan.family)
    await _set_override(home_id, FeatureKey.calendar, enabled=True)
    await _set_override(home_id, FeatureKey.notifications, enabled=True)
    await _set_override(home_id, FeatureKey.external_sharing, enabled=False)
    async with SessionFactory() as db:
        assert await _external_sharing_notification_eligible(db, home_id) is False


@pytest.mark.asyncio
async def test_external_sharing_notification_ineligible_on_free_plan() -> None:
    home_id = await _make_home()
    await _set_override(home_id, FeatureKey.calendar, enabled=True)
    await _set_override(home_id, FeatureKey.external_sharing, enabled=True)
    await _set_override(home_id, FeatureKey.notifications, enabled=True)
    async with SessionFactory() as db:
        # A fresh Home is Free by default — members.external_invites.enabled
        # is False there.
        assert await _external_sharing_notification_eligible(db, home_id) is False


@pytest.mark.asyncio
async def test_external_sharing_notification_eligible_on_family_with_everything_on() -> None:
    await _set_platform_flag(FeatureKey.external_sharing, enabled=True)
    home_id = await _make_home()
    await _set_plan(home_id, SubscriptionPlan.family)
    await _set_override(home_id, FeatureKey.calendar, enabled=True)
    await _set_override(home_id, FeatureKey.external_sharing, enabled=True)
    await _set_override(home_id, FeatureKey.notifications, enabled=True)
    async with SessionFactory() as db:
        assert await _external_sharing_notification_eligible(db, home_id) is True


# ---------------------------------------------------------------------------
# Module isolation: disabling one module must not affect another's
# eligibility check.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabling_wishlists_does_not_affect_nudges_eligibility() -> None:
    home_id = await _make_home()
    await _set_plan(home_id, SubscriptionPlan.family)
    await _set_override(home_id, FeatureKey.wish_lists, enabled=False)
    await _set_override(home_id, FeatureKey.nudges, enabled=True)
    await _set_override(home_id, FeatureKey.notifications, enabled=True)
    async with SessionFactory() as db:
        assert await _wishlists_notification_eligible(db, home_id) is False
        assert await is_nudges_notification_eligible(db, home_id) is True
