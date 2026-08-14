"""mykhaya.entitlements — the single authoritative Home -> effective plan ->
entitlements/limits resolution path. Service-level tests, independent of any
HTTP endpoint (see docs/architecture/commercial-entitlements.md "Calendar as
proof of architecture": there is no user-facing multi-calendar endpoint yet
to test the limit against, so the service is tested directly).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from mykhaya.db import SessionFactory
from mykhaya.entitlements import (
    effective_plan,
    effective_plan_sql_filter,
    ensure_home_subscription,
    get_home_subscription,
    get_limit,
    has_entitlement,
    require_entitlement,
    require_within_limit,
    resolve_effective_plan,
    resolve_effective_state,
)
from mykhaya.models import (
    Group,
    HomeSubscription,
    HomeSubscriptionEvent,
    SubscriptionPlan,
    SubscriptionProvider,
    SubscriptionStatus,
    User,
)


async def _make_home(name: str = "Test Home") -> uuid.UUID:
    async with SessionFactory() as db:
        user = User(email=f"owner-{uuid.uuid4()}@example.com", display_name="Owner")
        db.add(user)
        await db.flush()
        group = Group(name=name, created_by=user.id)
        db.add(group)
        await db.commit()
        return group.id


async def _set_subscription(home_id: uuid.UUID, **fields: object) -> None:
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        for key, value in fields.items():
            setattr(subscription, key, value)
        await db.commit()


# ---------------------------------------------------------------------------
# Default behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_home_receives_free_commercial_state() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        await ensure_home_subscription(db, home_id)
        await db.commit()
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        assert subscription.plan == SubscriptionPlan.free
        assert subscription.provider == SubscriptionProvider.free
        assert subscription.status == SubscriptionStatus.active


@pytest.mark.asyncio
async def test_ensure_home_subscription_is_idempotent_and_records_one_created_event() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        await ensure_home_subscription(db, home_id)
        await ensure_home_subscription(db, home_id)
        await db.commit()
    async with SessionFactory() as db:
        rows = (
            await db.scalars(select(HomeSubscription).where(HomeSubscription.group_id == home_id))
        ).all()
        assert len(rows) == 1
        events = (
            await db.scalars(
                select(HomeSubscriptionEvent).where(HomeSubscriptionEvent.group_id == home_id)
            )
        ).all()
        assert len([e for e in events if e.event_type == "created"]) == 1


@pytest.mark.asyncio
async def test_missing_subscription_record_resolves_to_free() -> None:
    """A Home with literally no HomeSubscription row (shouldn't happen after
    the migration backfill, but must still fail safe) resolves Free, never
    Family."""
    home_id = await _make_home()
    async with SessionFactory() as db:
        assert await get_home_subscription(db, home_id) is None
        assert await effective_plan(db, home_id) == SubscriptionPlan.free
        assert await has_entitlement(db, home_id, "lists.enabled") is False


@pytest.mark.asyncio
async def test_free_resolves_free_entitlements_and_calendar_limit_of_one() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        await ensure_home_subscription(db, home_id)
        await db.commit()
    async with SessionFactory() as db:
        assert await effective_plan(db, home_id) == SubscriptionPlan.free
        assert await has_entitlement(db, home_id, "lists.enabled") is False
        assert await get_limit(db, home_id, "calendar.max_categories") == 1


@pytest.mark.asyncio
async def test_family_resolves_family_entitlements_and_unlimited_calendars() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        await ensure_home_subscription(db, home_id)
        await db.commit()
    await _set_subscription(
        home_id,
        plan=SubscriptionPlan.family,
        provider=SubscriptionProvider.stripe,
        status=SubscriptionStatus.active,
    )
    async with SessionFactory() as db:
        assert await effective_plan(db, home_id) == SubscriptionPlan.family
        assert await has_entitlement(db, home_id, "lists.enabled") is True
        assert await get_limit(db, home_id, "calendar.max_categories") is None


# ---------------------------------------------------------------------------
# Commercial plan cleanup: the full Free vs Family capability matrix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_free_resolves_the_full_agreed_capability_matrix() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        await ensure_home_subscription(db, home_id)
        await db.commit()
    async with SessionFactory() as db:
        assert await get_limit(db, home_id, "home.max_members") == 1
        assert await get_limit(db, home_id, "calendar.max_categories") == 1
        assert await get_limit(db, home_id, "routines.personal.max_active") == 3
        # Included on both plans — not a Family differentiator.
        assert await has_entitlement(db, home_id, "notes.enabled") is True
        assert await has_entitlement(db, home_id, "routines.household.enabled") is False
        assert await has_entitlement(db, home_id, "events.shared.enabled") is False
        assert await has_entitlement(db, home_id, "lists.enabled") is False
        assert await has_entitlement(db, home_id, "chores.enabled") is False
        assert await has_entitlement(db, home_id, "wishlists.enabled") is False
        assert await has_entitlement(db, home_id, "members.external_invites.enabled") is False
        assert await has_entitlement(db, home_id, "family_plans.enabled") is False
        assert await has_entitlement(db, home_id, "support.priority.enabled") is False


@pytest.mark.asyncio
async def test_family_resolves_the_full_agreed_capability_matrix() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        await ensure_home_subscription(db, home_id)
        await db.commit()
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    async with SessionFactory() as db:
        assert await get_limit(db, home_id, "home.max_members") is None
        assert await get_limit(db, home_id, "calendar.max_categories") is None
        assert await get_limit(db, home_id, "routines.personal.max_active") is None
        assert await has_entitlement(db, home_id, "notes.enabled") is True
        assert await has_entitlement(db, home_id, "routines.household.enabled") is True
        assert await has_entitlement(db, home_id, "events.shared.enabled") is True
        assert await has_entitlement(db, home_id, "lists.enabled") is True
        assert await has_entitlement(db, home_id, "chores.enabled") is True
        assert await has_entitlement(db, home_id, "wishlists.enabled") is True
        assert await has_entitlement(db, home_id, "members.external_invites.enabled") is True
        assert await has_entitlement(db, home_id, "family_plans.enabled") is True
        assert await has_entitlement(db, home_id, "support.priority.enabled") is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "configure",
    [
        pytest.param(
            lambda home_id: _set_subscription(
                home_id,
                plan=SubscriptionPlan.family,
                provider=SubscriptionProvider.complimentary,
                status=SubscriptionStatus.active,
                complimentary_expires_at=None,
            ),
            id="complimentary",
        ),
        pytest.param(
            lambda home_id: _set_subscription(
                home_id,
                plan=SubscriptionPlan.family,
                provider=SubscriptionProvider.stripe,
                status=SubscriptionStatus.active,
            ),
            id="stripe_active",
        ),
        pytest.param(
            lambda home_id: _set_subscription(
                home_id,
                plan=SubscriptionPlan.family,
                provider=SubscriptionProvider.stripe,
                status=SubscriptionStatus.past_due,
            ),
            id="stripe_past_due",
        ),
        pytest.param(
            lambda home_id: _set_subscription(
                home_id,
                plan=SubscriptionPlan.family,
                provider=SubscriptionProvider.stripe,
                status=SubscriptionStatus.cancel_at_period_end,
            ),
            id="stripe_cancel_at_period_end",
        ),
    ],
)
async def test_every_family_provider_variant_resolves_identical_capabilities(configure) -> None:
    """Complimentary Family and every honoured Stripe status must resolve
    the exact same Family capability set — provider is never a second,
    reduced Family model."""
    home_id = await _make_home()
    async with SessionFactory() as db:
        await ensure_home_subscription(db, home_id)
        await db.commit()
    await configure(home_id)
    async with SessionFactory() as db:
        assert await get_limit(db, home_id, "home.max_members") is None
        assert await get_limit(db, home_id, "calendar.max_categories") is None
        assert await get_limit(db, home_id, "routines.personal.max_active") is None
        assert await has_entitlement(db, home_id, "routines.household.enabled") is True
        assert await has_entitlement(db, home_id, "lists.enabled") is True


# ---------------------------------------------------------------------------
# Complimentary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complimentary_family_with_no_expiry_resolves_family() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        await ensure_home_subscription(db, home_id)
        await db.commit()
    await _set_subscription(
        home_id,
        plan=SubscriptionPlan.family,
        provider=SubscriptionProvider.complimentary,
        status=SubscriptionStatus.active,
        complimentary_expires_at=None,
    )
    async with SessionFactory() as db:
        assert await effective_plan(db, home_id) == SubscriptionPlan.family


@pytest.mark.asyncio
async def test_complimentary_family_with_future_expiry_remains_active() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        await ensure_home_subscription(db, home_id)
        await db.commit()
    await _set_subscription(
        home_id,
        plan=SubscriptionPlan.family,
        provider=SubscriptionProvider.complimentary,
        status=SubscriptionStatus.active,
        complimentary_expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    async with SessionFactory() as db:
        assert await effective_plan(db, home_id) == SubscriptionPlan.family


@pytest.mark.asyncio
async def test_complimentary_family_with_past_expiry_resolves_free() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        await ensure_home_subscription(db, home_id)
        await db.commit()
    await _set_subscription(
        home_id,
        plan=SubscriptionPlan.family,
        provider=SubscriptionProvider.complimentary,
        status=SubscriptionStatus.active,
        complimentary_expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    async with SessionFactory() as db:
        assert await effective_plan(db, home_id) == SubscriptionPlan.free
        assert await has_entitlement(db, home_id, "lists.enabled") is False


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_numeric_limit_resolution() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        await ensure_home_subscription(db, home_id)
        await db.commit()
    async with SessionFactory() as db:
        assert await get_limit(db, home_id, "calendar.max_categories") == 1


@pytest.mark.asyncio
async def test_unlimited_entitlement_resolution() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        await ensure_home_subscription(db, home_id)
        await db.commit()
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    async with SessionFactory() as db:
        assert await get_limit(db, home_id, "calendar.max_categories") is None


@pytest.mark.asyncio
async def test_missing_unknown_entitlement_or_limit_fails_safe() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        await ensure_home_subscription(db, home_id)
        await db.commit()
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    async with SessionFactory() as db:
        assert await has_entitlement(db, home_id, "nonexistent.feature") is False
        assert await get_limit(db, home_id, "nonexistent.limit") == 0
        with pytest.raises(Exception):  # noqa: B017 - HTTPException, deliberately generic here
            await require_entitlement(db, home_id, "nonexistent.feature")


@pytest.mark.asyncio
async def test_require_within_limit_raises_at_the_limit_and_allows_below_it() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        await ensure_home_subscription(db, home_id)
        await db.commit()
    async with SessionFactory() as db:
        await require_within_limit(db, home_id, "calendar.max_categories", current_count=0)
        with pytest.raises(Exception):  # noqa: B017
            await require_within_limit(db, home_id, "calendar.max_categories", current_count=1)


# ---------------------------------------------------------------------------
# Separation from feature flags / permissions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entitlement_resolution_is_independent_of_feature_flags() -> None:
    """A globally-enabled FeatureKey (e.g. calendar) and a commercial
    entitlement are different layers — has_entitlement never consults
    FeatureFlag/FeatureOverride at all."""
    home_id = await _make_home()
    async with SessionFactory() as db:
        await ensure_home_subscription(db, home_id)
        await db.commit()
    async with SessionFactory() as db:
        # Free Home, calendar feature flag state is irrelevant here — the
        # commercial layer only knows about calendar.max_categories, not
        # about FeatureKey.calendar at all.
        assert await has_entitlement(db, home_id, "lists.enabled") is False


# ---------------------------------------------------------------------------
# Downgrade / data safety
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_downgrading_plan_does_not_delete_the_home_or_its_subscription_row() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        await ensure_home_subscription(db, home_id)
        await db.commit()
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    await _set_subscription(home_id, plan=SubscriptionPlan.free)
    async with SessionFactory() as db:
        assert await db.get(Group, home_id) is not None
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        assert subscription.plan == SubscriptionPlan.free


# ---------------------------------------------------------------------------
# Phase 2: effective-state resolution / reason, and the SQL filter mirror
# used by the Platform Control Centre summary/list endpoints.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_effective_state_has_no_reason_when_stored_matches_effective() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        await ensure_home_subscription(db, home_id)
        await db.commit()
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        resolution = resolve_effective_state(subscription)
        assert resolution.plan == SubscriptionPlan.free
        assert resolution.reason is None


@pytest.mark.asyncio
async def test_resolve_effective_state_explains_expired_complimentary_access() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        await ensure_home_subscription(db, home_id)
        await db.commit()
    await _set_subscription(
        home_id,
        plan=SubscriptionPlan.family,
        provider=SubscriptionProvider.complimentary,
        status=SubscriptionStatus.active,
        complimentary_expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        resolution = resolve_effective_state(subscription)
        assert resolution.plan == SubscriptionPlan.free
        assert resolution.reason == "Complimentary access expired"


@pytest.mark.asyncio
async def test_resolve_effective_state_explains_cancelled_subscription() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        await ensure_home_subscription(db, home_id)
        await db.commit()
    await _set_subscription(
        home_id,
        plan=SubscriptionPlan.family,
        provider=SubscriptionProvider.stripe,
        status=SubscriptionStatus.cancelled,
    )
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        resolution = resolve_effective_state(subscription)
        assert resolution.plan == SubscriptionPlan.free
        assert resolution.reason == "Subscription cancelled"


@pytest.mark.asyncio
async def test_effective_plan_sql_filter_matches_python_resolution() -> None:
    """Guards against the SQL mirror (used by the Platform Control Centre
    summary/list endpoints for scalable filtering) drifting from the
    authoritative Python resolver."""
    scenarios = [
        {"plan": SubscriptionPlan.free, "provider": SubscriptionProvider.free},
        {"plan": SubscriptionPlan.family, "provider": SubscriptionProvider.stripe},
        {
            "plan": SubscriptionPlan.family,
            "provider": SubscriptionProvider.complimentary,
            "complimentary_expires_at": None,
        },
        {
            "plan": SubscriptionPlan.family,
            "provider": SubscriptionProvider.complimentary,
            "complimentary_expires_at": datetime.now(UTC) + timedelta(days=1),
        },
        {
            "plan": SubscriptionPlan.family,
            "provider": SubscriptionProvider.complimentary,
            "complimentary_expires_at": datetime.now(UTC) - timedelta(days=1),
        },
        {
            "plan": SubscriptionPlan.family,
            "provider": SubscriptionProvider.stripe,
            "status": SubscriptionStatus.cancelled,
        },
        {
            "plan": SubscriptionPlan.family,
            "provider": SubscriptionProvider.stripe,
            "status": SubscriptionStatus.past_due,
        },
    ]
    home_ids: list[uuid.UUID] = []
    for scenario in scenarios:
        home_id = await _make_home()
        async with SessionFactory() as db:
            await ensure_home_subscription(db, home_id)
            await db.commit()
        await _set_subscription(home_id, **scenario)
        home_ids.append(home_id)

    async with SessionFactory() as db:
        for plan in (SubscriptionPlan.free, SubscriptionPlan.family):
            sql_matches = (
                await db.scalars(
                    select(HomeSubscription.group_id)
                    .where(HomeSubscription.group_id.in_(home_ids))
                    .where(effective_plan_sql_filter(plan))
                )
            ).all()
            for home_id in home_ids:
                subscription = await get_home_subscription(db, home_id)
                python_plan = resolve_effective_plan(subscription)
                assert (home_id in sql_matches) == (python_plan == plan)
