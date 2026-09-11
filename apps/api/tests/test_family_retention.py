"""Focused Phase 5 retention, restoration and purge regressions."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from mykhaya.db import SessionFactory
from mykhaya.entitlements import ensure_home_subscription, transition_expired_family_home
from mykhaya.family_retention import (
    RETENTION_DAYS,
    purge_family_home,
    restore_family_retention,
    scan_family_retention,
    start_family_retention,
)
from mykhaya.models import (
    Group,
    HomeCalendar,
    HomeEntitlementGrant,
    HomeRetentionLifecycle,
    HomeRetentionState,
    HouseholdList,
    HouseholdRelationship,
    Membership,
    PermissionProfile,
    Role,
    SubscriptionPlan,
    SubscriptionProvider,
    SubscriptionStatus,
    User,
)


async def _home() -> tuple[uuid.UUID, uuid.UUID]:
    async with SessionFactory() as db:
        owner = User(email=f"owner-{uuid.uuid4()}@example.com", display_name="Owner")
        db.add(owner)
        await db.flush()
        home = Group(name="Retention Home", created_by=owner.id)
        db.add(home)
        await db.flush()
        db.add(
            Membership(
                group_id=home.id,
                user_id=owner.id,
                role=Role.owner,
                relationship=HouseholdRelationship.home_admin,
                permission_profile=PermissionProfile.home_admin,
            )
        )
        await db.commit()
        return home.id, owner.id


@pytest.mark.asyncio
async def test_cancellation_before_expiry_does_not_start_retention() -> None:
    home_id, _ = await _home()
    expiry = datetime.now(UTC) + timedelta(days=2)
    async with SessionFactory() as db:
        subscription = await ensure_home_subscription(db, home_id)
        subscription.plan = SubscriptionPlan.family
        subscription.provider = SubscriptionProvider.stripe
        subscription.status = SubscriptionStatus.cancel_at_period_end
        subscription.current_period_end = expiry
        await db.commit()
        assert await start_family_retention(db, home_id, now=datetime.now(UTC)) is None
        assert await db.scalar(
            select(HomeRetentionLifecycle).where(HomeRetentionLifecycle.home_id == home_id)
        ) is None


@pytest.mark.asyncio
async def test_expiry_starts_exact_90_day_retention_once() -> None:
    home_id, _ = await _home()
    expiry = datetime(2026, 1, 1, tzinfo=UTC)
    now = expiry + timedelta(minutes=1)
    async with SessionFactory() as db:
        subscription = await ensure_home_subscription(db, home_id)
        subscription.plan = SubscriptionPlan.family
        subscription.provider = SubscriptionProvider.stripe
        subscription.status = SubscriptionStatus.cancel_at_period_end
        subscription.current_period_end = expiry
        await db.commit()
    async with SessionFactory() as db:
        assert await transition_expired_family_home(db, home_id, now=now) is True
        lifecycle = await start_family_retention(db, home_id, now=now)
        assert lifecycle is not None
        assert lifecycle.state == HomeRetentionState.retained_free
        assert lifecycle.family_expired_at == expiry
        assert lifecycle.retention_deadline == expiry + timedelta(days=RETENTION_DAYS)
        await db.commit()
    async with SessionFactory() as db:
        assert await start_family_retention(db, home_id, now=now) is not None
        assert len((await db.scalars(
            select(HomeRetentionLifecycle).where(HomeRetentionLifecycle.home_id == home_id)
        )).all()) == 1


@pytest.mark.asyncio
async def test_scheduler_scan_starts_retention_without_billing_page_read() -> None:
    home_id, _ = await _home()
    expiry = datetime.now(UTC) - timedelta(minutes=2)
    async with SessionFactory() as db:
        subscription = await ensure_home_subscription(db, home_id)
        subscription.plan = SubscriptionPlan.family
        subscription.provider = SubscriptionProvider.stripe
        subscription.status = SubscriptionStatus.cancel_at_period_end
        subscription.current_period_end = expiry
        await db.commit()
    async with SessionFactory() as db:
        assert await scan_family_retention(db, now=datetime.now(UTC)) >= 1
        await db.commit()
        lifecycle = await db.scalar(
            select(HomeRetentionLifecycle).where(HomeRetentionLifecycle.home_id == home_id)
        )
        assert lifecycle is not None
        assert lifecycle.state == HomeRetentionState.retained_free


@pytest.mark.asyncio
async def test_restore_reactivates_child_and_grants_but_not_former_adult() -> None:
    home_id, _ = await _home()
    async with SessionFactory() as db:
        child = User(email=f"child-{uuid.uuid4()}@example.com", display_name="Child")
        adult = User(email=f"adult-{uuid.uuid4()}@example.com", display_name="Adult")
        db.add_all([child, adult])
        await db.flush()
        db.add_all(
            [
                Membership(
                    group_id=home_id,
                    user_id=child.id,
                    role=Role.member,
                    relationship=HouseholdRelationship.child,
                    permission_profile=PermissionProfile.child_restricted,
                ),
                Membership(
                    group_id=home_id,
                    user_id=adult.id,
                    role=Role.adult_member,
                    relationship=HouseholdRelationship.partner,
                    permission_profile=PermissionProfile.standard_partner,
                    family_sponsorship_decided=True,
                ),
            ]
        )
        subscription = await ensure_home_subscription(db, home_id)
        expiry = datetime.now(UTC) - timedelta(days=1)
        subscription.plan = SubscriptionPlan.family
        subscription.provider = SubscriptionProvider.stripe
        subscription.status = SubscriptionStatus.cancel_at_period_end
        subscription.current_period_end = expiry
        await db.flush()
        db.add(
            HomeEntitlementGrant(
                source_group_id=home_id,
                recipient_user_id=adult.id,
                entitlement_key="family",
                revoked_at=None,
            )
        )
        await db.commit()
    async with SessionFactory() as db:
        await transition_expired_family_home(db, home_id, now=datetime.now(UTC))
        await start_family_retention(db, home_id, now=datetime.now(UTC))
        subscription = await ensure_home_subscription(db, home_id)
        subscription.status = SubscriptionStatus.active
        subscription.current_period_end = datetime.now(UTC) + timedelta(days=30)
        await db.flush()
        await restore_family_retention(db, home_id)
        await db.commit()
    async with SessionFactory() as db:
        memberships = (await db.scalars(select(Membership).where(Membership.group_id == home_id))).all()
        child_row = next(row for row in memberships if row.relationship == HouseholdRelationship.child)
        adult_row = next(row for row in memberships if row.relationship == HouseholdRelationship.partner)
        assert child_row.removed_at is None
        assert adult_row.removed_at is not None
        grant = await db.scalar(select(HomeEntitlementGrant).where(HomeEntitlementGrant.source_group_id == home_id))
        assert grant is not None and grant.revoked_at is None


@pytest.mark.asyncio
async def test_purge_preserves_home_admin_and_personal_calendars() -> None:
    home_id, owner_id = await _home()
    async with SessionFactory() as db:
        primary = HomeCalendar(group_id=home_id, name="Home Calendar", is_primary=True, owner_user_id=None)
        personal = HomeCalendar(group_id=home_id, name="Personal calendar", is_primary=False, owner_user_id=owner_id)
        secondary = HomeCalendar(group_id=home_id, name="Family trips", is_primary=False, owner_user_id=None)
        db.add_all([primary, personal, secondary])
        db.add(HouseholdList(group_id=home_id, name="Family list", created_by=owner_id))
        lifecycle = HomeRetentionLifecycle(
            home_id=home_id,
            state=HomeRetentionState.retained_free,
            family_expired_at=datetime.now(UTC) - timedelta(days=91),
            retention_deadline=datetime.now(UTC) - timedelta(days=1),
        )
        db.add(lifecycle)
        await db.commit()
        secondary_id = secondary.id
        personal_id = personal.id
        primary_id = primary.id
    async with SessionFactory() as db:
        assert await purge_family_home(db, home_id) is True
        await db.commit()
    async with SessionFactory() as db:
        assert await db.get(Group, home_id) is not None
        assert await db.get(Membership, next(
            row.id for row in (await db.scalars(select(Membership).where(Membership.group_id == home_id))).all()
        )) is not None
        assert await db.get(HomeCalendar, primary_id) is not None
        assert await db.get(HomeCalendar, personal_id) is not None
        assert await db.get(HomeCalendar, secondary_id) is None
        lifecycle = await db.scalar(select(HomeRetentionLifecycle).where(HomeRetentionLifecycle.home_id == home_id))
        assert lifecycle is not None and lifecycle.state == HomeRetentionState.purged
