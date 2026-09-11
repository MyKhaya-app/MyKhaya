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
    EntitlementSource,
    effective_plan,
    effective_plan_sql_filter,
    ensure_home_subscription,
    explain_resource_access,
    explain_user_entitlement,
    grant_home_family_sponsorship,
    get_home_subscription,
    get_limit,
    has_entitlement,
    has_user_entitlement,
    revoke_home_family_sponsorship,
    require_entitlement,
    require_within_limit,
    resolve_effective_plan,
    resolve_effective_state,
    retained_member_id,
)
from mykhaya.models import (
    CalendarShare,
    CalendarSharePermission,
    CalendarShareStatus,
    Group,
    HomeCalendar,
    HomeSubscription,
    HomeSubscriptionEvent,
    HouseholdRelationship,
    Membership,
    PermissionProfile,
    Role,
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


async def _add_membership(
    home_id: uuid.UUID,
    *,
    relationship: HouseholdRelationship = HouseholdRelationship.review_required,
    removed: bool = False,
) -> uuid.UUID:
    """A minimal Membership row for retained_member_id tests — colour is
    left unset (nullable) to avoid depending on the full ColourToken/
    assign_member_colour flow, which is irrelevant to retention ordering."""
    async with SessionFactory() as db:
        user = User(email=f"member-{uuid.uuid4()}@example.com", display_name="Member")
        db.add(user)
        await db.flush()
        db.add(
            Membership(
                group_id=home_id,
                user_id=user.id,
                role=Role.member,
                relationship=relationship,
                permission_profile=PermissionProfile.review_required,
                removed_at=datetime.now(UTC) if removed else None,
            )
        )
        await db.commit()
        return user.id


async def _make_personal_home(*, family: bool = False) -> tuple[uuid.UUID, uuid.UUID]:
    async with SessionFactory() as db:
        user = User(email=f"personal-{uuid.uuid4()}@example.com", display_name="Personal")
        db.add(user)
        await db.flush()
        group = Group(name="Personal Home", created_by=user.id)
        db.add(group)
        await db.flush()
        db.add(
            Membership(
                group_id=group.id,
                user_id=user.id,
                role=Role.owner,
                relationship=HouseholdRelationship.home_admin,
                permission_profile=PermissionProfile.home_admin,
            )
        )
        await db.flush()
        subscription = await ensure_home_subscription(db, group.id)
        if family:
            subscription.plan = SubscriptionPlan.family
            subscription.provider = SubscriptionProvider.stripe
        await db.commit()
        return user.id, group.id


async def _add_member(
    home_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    family_sponsorship_decided: bool | None = False,
) -> None:
    async with SessionFactory() as db:
        db.add(
            Membership(
                group_id=home_id,
                user_id=user_id,
                role=Role.adult_member,
                relationship=HouseholdRelationship.partner,
                permission_profile=PermissionProfile.standard_partner,
                family_sponsorship_decided=family_sponsorship_decided,
            )
        )
        await db.commit()


async def _sponsor(home_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async with SessionFactory() as db:
        await grant_home_family_sponsorship(db, home_id, user_id)
        await db.commit()


# ---------------------------------------------------------------------------
# Default behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scoped_entitlement_matrix_keeps_personal_and_home_access_separate() -> None:
    user_id, own_home = await _make_personal_home()
    _, family_home = await _make_personal_home(family=True)
    await _add_member(family_home, user_id)

    async with SessionFactory() as db:
        assert await has_user_entitlement(db, user_id, own_home, "meals.enabled") is False
        assert await has_user_entitlement(db, user_id, family_home, "meals.enabled") is False

    await _sponsor(family_home, user_id)
    async with SessionFactory() as db:
        decision = await explain_user_entitlement(db, user_id, family_home, "meals.enabled")
        assert decision is not None
        assert decision.source is EntitlementSource.home_sponsored
        assert await has_user_entitlement(db, user_id, own_home, "meals.enabled") is False


@pytest.mark.asyncio
async def test_personal_family_entitlement_is_scoped_to_the_personal_home() -> None:
    user_id, own_home = await _make_personal_home(family=True)
    _, other_home = await _make_personal_home()
    await _add_member(other_home, user_id)

    async with SessionFactory() as db:
        decision = await explain_user_entitlement(db, user_id, own_home, "meals.enabled")
        assert decision is not None
        assert decision.source is EntitlementSource.personal
        assert await has_user_entitlement(db, user_id, other_home, "meals.enabled") is False


@pytest.mark.asyncio
async def test_sponsorship_requires_current_family_source_and_active_membership() -> None:
    user_id, source_home = await _make_personal_home(family=True)
    recipient_id, recipient_home = await _make_personal_home()
    await _add_member(source_home, recipient_id)
    await _sponsor(source_home, recipient_id)

    async with SessionFactory() as db:
        assert await has_user_entitlement(db, recipient_id, source_home, "meals.enabled") is True
        source_subscription = await get_home_subscription(db, source_home)
        assert source_subscription is not None
        source_subscription.plan = SubscriptionPlan.free
        assert await has_user_entitlement(db, recipient_id, source_home, "meals.enabled") is False
        source_subscription.plan = SubscriptionPlan.family
        membership = await db.scalar(
            select(Membership).where(
                Membership.group_id == source_home,
                Membership.user_id == recipient_id,
            )
        )
        assert membership is not None
        membership.removed_at = datetime.now(UTC)
        assert await has_user_entitlement(db, recipient_id, source_home, "meals.enabled") is False
        assert await has_user_entitlement(db, recipient_id, recipient_home, "meals.enabled") is False


@pytest.mark.asyncio
async def test_explicit_sponsorship_decision_is_home_scoped_and_legacy_members_are_preserved() -> None:
    recipient_id, personal_home = await _make_personal_home()
    _, family_home = await _make_personal_home(family=True)
    await _add_member(family_home, recipient_id, family_sponsorship_decided=None)

    async with SessionFactory() as db:
        membership = await db.scalar(
            select(Membership).where(
                Membership.group_id == family_home,
                Membership.user_id == recipient_id,
            )
        )
        assert membership is not None
        # Existing paid members have NULL and retain transitional legacy access
        # without creating a HomeEntitlementGrant row.
        assert membership.family_sponsorship_decided is None
        assert await has_user_entitlement(db, recipient_id, family_home, "family_plans.enabled")
        assert await has_user_entitlement(db, recipient_id, personal_home, "family_plans.enabled") is False

        membership.family_sponsorship_decided = False
        await db.flush()
        assert await has_user_entitlement(db, recipient_id, family_home, "family_plans.enabled") is False


@pytest.mark.asyncio
async def test_revoking_one_home_sponsorship_keeps_another_source_and_membership_intact() -> None:
    recipient_id, _ = await _make_personal_home()
    _, first_home = await _make_personal_home(family=True)
    _, second_home = await _make_personal_home(family=True)
    await _add_member(first_home, recipient_id)
    await _add_member(second_home, recipient_id)
    await _sponsor(first_home, recipient_id)
    await _sponsor(second_home, recipient_id)

    async with SessionFactory() as db:
        assert await revoke_home_family_sponsorship(db, first_home, recipient_id) is True
        first_membership = await db.scalar(
            select(Membership).where(
                Membership.group_id == first_home,
                Membership.user_id == recipient_id,
            )
        )
        assert first_membership is not None
        assert first_membership.removed_at is None
        assert await has_user_entitlement(db, recipient_id, first_home, "family_plans.enabled") is False
        assert await has_user_entitlement(db, recipient_id, second_home, "family_plans.enabled") is True


@pytest.mark.asyncio
async def test_legacy_member_loses_home_family_access_after_paid_period_expiry() -> None:
    recipient_id, _ = await _make_personal_home()
    _, home_id = await _make_personal_home(family=True)
    await _add_member(home_id, recipient_id, family_sponsorship_decided=None)

    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        subscription.provider = SubscriptionProvider.stripe
        subscription.status = SubscriptionStatus.cancel_at_period_end
        subscription.current_period_end = datetime.now(UTC) - timedelta(minutes=1)
        assert await has_user_entitlement(db, recipient_id, home_id, "family_plans.enabled") is False


@pytest.mark.asyncio
async def test_resource_share_is_explicit_and_does_not_grant_family_entitlement() -> None:
    owner_id, source_home = await _make_personal_home()
    recipient_id, recipient_home = await _make_personal_home()
    async with SessionFactory() as db:
        calendar = HomeCalendar(group_id=source_home, name="Shared")
        db.add(calendar)
        await db.flush()
        db.add(
            CalendarShare(
                resource_type="calendar",
                calendar_id=calendar.id,
                source_group_id=source_home,
                requested_by_user_id=owner_id,
                recipient_email=f"recipient-{recipient_id}@example.com",
                recipient_user_id=recipient_id,
                permission=CalendarSharePermission.view,
                status=CalendarShareStatus.accepted,
                token_hash=f"token-{uuid.uuid4()}",
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        resource = await explain_resource_access(db, recipient_id, "calendar", calendar.id)
        assert resource is not None
        assert resource.source is EntitlementSource.resource_share
        assert resource.home_id == source_home
        assert await has_user_entitlement(db, recipient_id, recipient_home, "meals.enabled") is False


@pytest.mark.asyncio
async def test_multiple_sponsorship_sources_recalculate_independently() -> None:
    recipient_id, own_home = await _make_personal_home()
    _, first_home = await _make_personal_home(family=True)
    _, second_home = await _make_personal_home(family=True)
    await _add_member(first_home, recipient_id)
    await _add_member(second_home, recipient_id)
    await _sponsor(first_home, recipient_id)
    await _sponsor(second_home, recipient_id)

    async with SessionFactory() as db:
        assert await has_user_entitlement(db, recipient_id, first_home, "meals.enabled") is True
        assert await has_user_entitlement(db, recipient_id, second_home, "meals.enabled") is True
        assert await has_user_entitlement(db, recipient_id, own_home, "meals.enabled") is False
        assert await revoke_home_family_sponsorship(db, first_home, recipient_id) is True
        assert await has_user_entitlement(db, recipient_id, first_home, "meals.enabled") is False
        assert await has_user_entitlement(db, recipient_id, second_home, "meals.enabled") is True


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
        # Lists is included on Free (Phase 2B) — bounded by lists.max_lists,
        # not a boolean gate.
        assert await has_entitlement(db, home_id, "lists.enabled") is True
        assert await has_entitlement(db, home_id, "nudges.enabled") is False


@pytest.mark.asyncio
async def test_free_resolves_free_entitlements_and_calendar_limit_of_one() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        await ensure_home_subscription(db, home_id)
        await db.commit()
    async with SessionFactory() as db:
        assert await effective_plan(db, home_id) == SubscriptionPlan.free
        assert await has_entitlement(db, home_id, "lists.enabled") is True
        assert await get_limit(db, home_id, "lists.max_lists") == 2
        assert await get_limit(db, home_id, "calendar.max_categories") == 1
        # Phase 2C: a *separate* limit from calendar.max_categories — see its
        # PLAN_DEFINITIONS docstring. Combined personal+shared calendar count.
        assert await get_limit(db, home_id, "calendar.max_calendars") == 1


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
        assert await get_limit(db, home_id, "lists.max_lists") is None
        assert await get_limit(db, home_id, "calendar.max_categories") is None
        assert await get_limit(db, home_id, "calendar.max_calendars") is None


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
        assert await get_limit(db, home_id, "lists.max_lists") == 2
        # Included on both plans — not a Family differentiator.
        assert await has_entitlement(db, home_id, "notes.enabled") is True
        # Lists is included on Free too (Phase 2B) — see lists.max_lists
        # above for the actual Free/Family differentiator.
        assert await has_entitlement(db, home_id, "lists.enabled") is True
        assert await has_entitlement(db, home_id, "routines.household.enabled") is False
        assert await has_entitlement(db, home_id, "events.shared.enabled") is False
        assert await has_entitlement(db, home_id, "chores.enabled") is False
        assert await has_entitlement(db, home_id, "wishlists.enabled") is False
        assert await has_entitlement(db, home_id, "members.external_invites.enabled") is False
        assert await has_entitlement(db, home_id, "family_plans.enabled") is False
        assert await has_entitlement(db, home_id, "support.priority.enabled") is False
        assert await has_entitlement(db, home_id, "nudges.enabled") is False


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
        assert await get_limit(db, home_id, "lists.max_lists") is None
        assert await has_entitlement(db, home_id, "notes.enabled") is True
        assert await has_entitlement(db, home_id, "routines.household.enabled") is True
        assert await has_entitlement(db, home_id, "events.shared.enabled") is True
        assert await has_entitlement(db, home_id, "lists.enabled") is True
        assert await has_entitlement(db, home_id, "chores.enabled") is True
        assert await has_entitlement(db, home_id, "wishlists.enabled") is True
        assert await has_entitlement(db, home_id, "members.external_invites.enabled") is True
        assert await has_entitlement(db, home_id, "family_plans.enabled") is True
        assert await has_entitlement(db, home_id, "support.priority.enabled") is True
        assert await has_entitlement(db, home_id, "nudges.enabled") is True


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
        # lists.enabled no longer differentiates Free/Family (Phase 2B —
        # both plans include it, differentiated by lists.max_lists
        # instead), so nudges.enabled is the Family-only proxy here.
        assert await has_entitlement(db, home_id, "nudges.enabled") is False


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
        assert await has_entitlement(db, home_id, "nudges.enabled") is False


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


# ---------------------------------------------------------------------------
# Phase 2C: retained_member_id — deterministic Free-downgrade member policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retained_member_id_is_none_for_a_home_with_no_membership() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        assert await retained_member_id(db, home_id) is None


@pytest.mark.asyncio
async def test_retained_member_id_is_the_sole_member_of_a_new_home() -> None:
    home_id = await _make_home()
    member = await _add_membership(home_id, relationship=HouseholdRelationship.home_admin)
    async with SessionFactory() as db:
        assert await retained_member_id(db, home_id) == member


@pytest.mark.asyncio
async def test_retained_member_id_prefers_home_admin_over_older_members() -> None:
    home_id = await _make_home()
    oldest = await _add_membership(home_id, relationship=HouseholdRelationship.partner)
    admin = await _add_membership(home_id, relationship=HouseholdRelationship.home_admin)
    async with SessionFactory() as db:
        assert await retained_member_id(db, home_id) != oldest
        assert await retained_member_id(db, home_id) == admin


@pytest.mark.asyncio
async def test_retained_member_id_falls_back_to_oldest_membership_without_a_home_admin() -> None:
    home_id = await _make_home()
    oldest = await _add_membership(home_id, relationship=HouseholdRelationship.partner)
    await _add_membership(home_id, relationship=HouseholdRelationship.child)
    async with SessionFactory() as db:
        assert await retained_member_id(db, home_id) == oldest


@pytest.mark.asyncio
async def test_retained_member_id_ignores_removed_memberships() -> None:
    home_id = await _make_home()
    await _add_membership(home_id, relationship=HouseholdRelationship.home_admin, removed=True)
    survivor = await _add_membership(home_id, relationship=HouseholdRelationship.partner)
    async with SessionFactory() as db:
        assert await retained_member_id(db, home_id) == survivor
