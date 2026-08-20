"""The single authoritative path from a Home to its effective commercial plan
and entitlements. See docs/architecture/commercial-entitlements.md.

    Home -> HomeSubscription -> effective plan -> PlanDefinition -> entitlements/limits

Deliberately provider-agnostic: nothing here mentions Stripe. The application
asks "does this Home have entitlement X" / "what's this Home's limit for Y" —
never "does this Home have a stripe_subscription_id". See "API/domain
separation" in the architecture doc.

Fails safe throughout: a missing HomeSubscription row, an unrecognised
plan/provider/status, or expired complimentary access all resolve to Free,
never to Family. An unknown entitlement/limit key resolves to "not entitled" /
zero, never to unlimited.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.models import (
    CalendarEventLabel,
    HomeCalendar,
    HomeSubscription,
    HomeSubscriptionEvent,
    HouseholdRoutine,
    Membership,
    RoutineScope,
    SubscriptionPlan,
    SubscriptionProvider,
    SubscriptionStatus,
)
from mykhaya.schemas import CalendarUsageResponse

# Statuses under which a subscription's own `plan` is actually honoured.
# past_due deliberately still counts as active — this is Phase 3's explicit
# dunning policy, not a placeholder: Stripe's own Smart Retries handle
# reattempting payment, and MyKhaya only reacts to the terminal outcome
# (customer.subscription.deleted -> cancelled) rather than running a second,
# competing downgrade timer of its own. A single missed payment never causes
# an instant downgrade; retain access, let the customer fix their payment
# method via the Stripe Customer Portal, and downgrade only once Stripe
# itself gives up. See "past_due and dunning" in
# docs/architecture/commercial-entitlements.md. A fully `cancelled`
# subscription (or one whose complimentary access has expired) resolves to
# Free.
_PLAN_HONOURED_STATUSES = frozenset(
    {
        SubscriptionStatus.active,
        SubscriptionStatus.trialing,
        SubscriptionStatus.past_due,
        SubscriptionStatus.cancel_at_period_end,
    }
)


@dataclass(frozen=True)
class PlanDefinition:
    plan: SubscriptionPlan
    # Boolean feature entitlements, e.g. "lists.enabled".
    booleans: dict[str, bool]
    # Numeric limits, e.g. "calendar.max_categories". None means unlimited.
    limits: dict[str, int | None]


# The one place plan capabilities are defined. Adding an entitlement later is
# "add a key here" — never `if home.plan == "family"` scattered through
# routers.
#
# Enforced today (a real endpoint calls require_entitlement/require_within_limit
# against it): calendar.max_categories, home.max_members,
# routines.personal.max_active, routines.household.enabled.
#
# Declared as commercial data only — no live enforcement, because either the
# underlying module doesn't exist/isn't released yet (lists/chores/wishlists/
# notes — see mykhaya.module_registry), or the correct enforcement design is
# a deliberate follow-up task rather than something to improvise here
# (events.shared.enabled, members.external_invites.enabled,
# family_plans.enabled, support.priority.enabled — see "Deferred enforcement"
# in docs/architecture/commercial-entitlements.md):
PLAN_DEFINITIONS: dict[SubscriptionPlan, PlanDefinition] = {
    SubscriptionPlan.free: PlanDefinition(
        plan=SubscriptionPlan.free,
        booleans={
            # Notes is included on both plans (it's a core-organiser feature,
            # not a household-coordination one) — the module itself is still
            # unreleased (mykhaya.module_registry), so this is data only
            # until it ships.
            "notes.enabled": True,
            "lists.enabled": False,
            "chores.enabled": False,
            "wishlists.enabled": False,
            "routines.household.enabled": False,
            "events.shared.enabled": False,
            "members.external_invites.enabled": False,
            "family_plans.enabled": False,
            "support.priority.enabled": False,
            # Meal Plans (mykhaya.routers.meal_plans) — Family-only, per
            # docs/architecture/meal-plans.md.
            "meals.enabled": False,
        },
        limits={
            "calendar.max_categories": 1,
            "home.max_members": 1,
            "routines.personal.max_active": 3,
        },
    ),
    SubscriptionPlan.family: PlanDefinition(
        plan=SubscriptionPlan.family,
        booleans={
            "notes.enabled": True,
            "lists.enabled": True,
            "chores.enabled": True,
            "wishlists.enabled": True,
            "routines.household.enabled": True,
            "events.shared.enabled": True,
            "members.external_invites.enabled": True,
            "family_plans.enabled": True,
            "support.priority.enabled": True,
            "meals.enabled": True,
        },
        limits={
            "calendar.max_categories": None,
            "home.max_members": None,
            "routines.personal.max_active": None,
        },
    ),
}


class CommercialRestrictionCode(StrEnum):
    """Stable, provider-neutral codes a frontend can branch on without
    parsing human-readable text. See "Future module enforcement standard" in
    docs/architecture/commercial-entitlements.md — every module that gates a
    boolean entitlement or a numeric limit should raise through
    `commercial_restriction_error` with one of these, rather than inventing
    its own error shape."""

    plan_feature_unavailable = "plan_feature_unavailable"
    plan_limit_reached = "plan_limit_reached"
    resource_restricted_by_plan = "resource_restricted_by_plan"


def commercial_restriction_error(
    code: CommercialRestrictionCode, message: str, **metadata: Any
) -> HTTPException:
    """Builds the one standard shape for a commercial-restriction response:
    `{"detail": {"code": ..., "message": ..., ...metadata}}`. `metadata` is
    safe, provider-neutral context only (an entitlement key, a numeric
    limit) — never a subscription/provider implementation detail (no Stripe
    status, no Complimentary reason/note, no internal IDs). The existing
    `detail: str` convention used everywhere else in this codebase keeps
    working unchanged; `packages/api-client`'s error handling additively
    recognises this richer shape without breaking that convention."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": code.value, "message": message, **metadata},
    )


def classify_ordered_resources(
    ordered_ids: Sequence[uuid.UUID], limit: int | None
) -> dict[uuid.UUID, bool]:
    """Given resource ids already placed in the caller's own deterministic
    priority order (e.g. a Home's primary calendar first, then its other
    calendars oldest-first), returns which ids fall within `limit` — `True`
    for the ones a Free-limited Home keeps full access to, `False` for the
    excess ones a downgrade leaves over the limit. `limit=None` means
    unlimited (every id is `True`). Pure and reusable: any future
    numeric-limited resource (a second calendar today, something else
    later) can reuse this instead of re-deriving the same "first N stay
    normal" rule. This never deletes or mutates anything — it only answers
    "is this one within the entitled count right now."""
    if limit is None:
        return {resource_id: True for resource_id in ordered_ids}
    return {resource_id: index < limit for index, resource_id in enumerate(ordered_ids)}


async def get_home_subscription(db: AsyncSession, home_id: uuid.UUID) -> HomeSubscription | None:
    result: HomeSubscription | None = await db.scalar(
        select(HomeSubscription).where(HomeSubscription.group_id == home_id)
    )
    return result


async def ensure_home_subscription(db: AsyncSession, home_id: uuid.UUID) -> HomeSubscription:
    """Idempotent: returns the existing row if present, otherwise creates the
    Free/free/active default and records the "created" history event. Called
    at Home-creation time (routers.groups.create_group) and safe to call
    again for a pre-existing Home (the migration backfill uses the same
    default for every existing Group — see migration 0020)."""
    existing = await get_home_subscription(db, home_id)
    if existing is not None:
        return existing
    subscription = HomeSubscription(group_id=home_id)
    db.add(subscription)
    await db.flush()
    await record_subscription_event(
        db,
        home_id,
        event_type="created",
        to_plan=SubscriptionPlan.free,
        to_provider=SubscriptionProvider.free,
        to_status=SubscriptionStatus.active,
    )
    return subscription


async def record_subscription_event(
    db: AsyncSession,
    home_id: uuid.UUID,
    *,
    event_type: str,
    from_plan: SubscriptionPlan | None = None,
    to_plan: SubscriptionPlan | None = None,
    from_provider: SubscriptionProvider | None = None,
    to_provider: SubscriptionProvider | None = None,
    from_status: SubscriptionStatus | None = None,
    to_status: SubscriptionStatus | None = None,
    actor_administrator_id: uuid.UUID | None = None,
    reason: str | None = None,
) -> None:
    db.add(
        HomeSubscriptionEvent(
            group_id=home_id,
            event_type=event_type,
            from_plan=from_plan,
            to_plan=to_plan,
            from_provider=from_provider,
            to_provider=to_provider,
            from_status=from_status,
            to_status=to_status,
            actor_administrator_id=actor_administrator_id,
            reason=reason,
        )
    )


def _complimentary_active(subscription: HomeSubscription) -> bool:
    if subscription.complimentary_expires_at is None:
        return True
    return subscription.complimentary_expires_at > datetime.now(UTC)


def resolve_effective_plan(subscription: HomeSubscription | None) -> SubscriptionPlan:
    """The pure resolution rule — no DB access — shared by `effective_plan()`
    (single Home) and any bulk listing/summary query that has already fetched
    a batch of `HomeSubscription` rows and wants to resolve each one without
    an extra query per row. This is still the one place the rule is written;
    `effective_plan()` is a thin fetch-then-call-this wrapper, not a second
    implementation. See module docstring for the fail-safe rules enforced
    here."""
    if subscription is None:
        return SubscriptionPlan.free
    if subscription.status not in _PLAN_HONOURED_STATUSES:
        return SubscriptionPlan.free
    if subscription.provider == SubscriptionProvider.complimentary and not _complimentary_active(
        subscription
    ):
        return SubscriptionPlan.free
    if subscription.plan not in PLAN_DEFINITIONS:
        return SubscriptionPlan.free  # unrecognised/corrupt value — never trust it
    return subscription.plan


@dataclass(frozen=True)
class EffectiveStateResolution:
    plan: SubscriptionPlan
    # None when the effective plan matches the stored plan exactly (the
    # common case). Populated with a short, human-readable explanation
    # whenever they diverge — e.g. expired complimentary access, a
    # cancelled/lapsed status — for display in the Platform Control Centre.
    reason: str | None


def resolve_effective_state(subscription: HomeSubscription | None) -> EffectiveStateResolution:
    """Like resolve_effective_plan, but also explains *why* when the
    effective plan differs from the stored one — for Platform Control Centre
    diagnostics (mykhaya.routers.platform's subscription detail endpoint).
    Never used for authorization; only for display."""
    plan = resolve_effective_plan(subscription)
    if subscription is None:
        return EffectiveStateResolution(plan=plan, reason=None)
    if plan == subscription.plan:
        return EffectiveStateResolution(plan=plan, reason=None)
    if subscription.provider == SubscriptionProvider.complimentary and not _complimentary_active(
        subscription
    ):
        return EffectiveStateResolution(plan=plan, reason="Complimentary access expired")
    if subscription.status == SubscriptionStatus.cancelled:
        return EffectiveStateResolution(plan=plan, reason="Subscription cancelled")
    if subscription.status not in _PLAN_HONOURED_STATUSES:
        return EffectiveStateResolution(plan=plan, reason="Subscription not currently active")
    if subscription.plan not in PLAN_DEFINITIONS:
        return EffectiveStateResolution(plan=plan, reason="Unrecognised stored plan value")
    return EffectiveStateResolution(plan=plan, reason=None)


def effective_plan_sql_filter(plan: SubscriptionPlan) -> ColumnElement[bool]:
    """A SQL-expressible mirror of resolve_effective_plan's Free/Family split,
    for filtering a listing query (mykhaya.routers.platform's subscription
    list/summary endpoints) without fetching every row into Python first.

    This is a *filter*, never an authorization decision — resolve_effective_plan
    (via effective_plan()) remains the only authoritative per-Home resolution.
    Query against an outer join of Group -> HomeSubscription, since a Home
    with no subscription row must count as Free here exactly as it does in
    resolve_effective_plan. Kept in sync with resolve_effective_plan by
    test_effective_plan_sql_filter_matches_python_resolution."""
    complimentary_expired = and_(
        HomeSubscription.provider == SubscriptionProvider.complimentary,
        HomeSubscription.complimentary_expires_at.is_not(None),
        HomeSubscription.complimentary_expires_at <= func.now(),
    )
    is_effectively_free = or_(
        HomeSubscription.id.is_(None),
        HomeSubscription.status.not_in(_PLAN_HONOURED_STATUSES),
        complimentary_expired,
        HomeSubscription.plan == SubscriptionPlan.free,
    )
    if plan == SubscriptionPlan.free:
        return is_effectively_free
    return and_(HomeSubscription.id.is_not(None), not_(is_effectively_free))


def complimentary_expired_sql_filter() -> ColumnElement[bool]:
    """SQL mirror of the complimentary-expiry check in resolve_effective_plan,
    for the "expired complimentary" summary count and list filter."""
    return and_(
        HomeSubscription.provider == SubscriptionProvider.complimentary,
        HomeSubscription.complimentary_expires_at.is_not(None),
        HomeSubscription.complimentary_expires_at <= func.now(),
    )


async def effective_plan(db: AsyncSession, home_id: uuid.UUID) -> SubscriptionPlan:
    """The single authoritative resolution. See module docstring for the
    fail-safe rules this enforces."""
    subscription = await get_home_subscription(db, home_id)
    return resolve_effective_plan(subscription)


def plan_definition_for(plan: SubscriptionPlan) -> PlanDefinition:
    return PLAN_DEFINITIONS.get(plan, PLAN_DEFINITIONS[SubscriptionPlan.free])


async def _plan_definition(db: AsyncSession, home_id: uuid.UUID) -> PlanDefinition:
    plan = await effective_plan(db, home_id)
    return plan_definition_for(plan)


async def has_entitlement(db: AsyncSession, home_id: uuid.UUID, key: str) -> bool:
    definition = await _plan_definition(db, home_id)
    return definition.booleans.get(key, False)  # unknown key -> not entitled


async def require_entitlement(db: AsyncSession, home_id: uuid.UUID, key: str) -> None:
    if not await has_entitlement(db, home_id, key):
        raise commercial_restriction_error(
            CommercialRestrictionCode.plan_feature_unavailable,
            "This feature isn't included in your current plan.",
            entitlement=key,
        )


async def get_limit(db: AsyncSession, home_id: uuid.UUID, key: str) -> int | None:
    """Returns the numeric limit, or None for unlimited. An unrecognised key
    fails safe to 0 (not unlimited) — see has_entitlement's docstring."""
    definition = await _plan_definition(db, home_id)
    if key not in definition.limits:
        return 0
    return definition.limits[key]


async def require_within_limit(
    db: AsyncSession, home_id: uuid.UUID, key: str, current_count: int
) -> None:
    """Raises if `current_count` (the count *before* adding one more) has
    already reached the Home's limit for `key`.

    Concurrency note: this function only compares numbers — it does not
    itself protect against two concurrent requests both reading the same
    `current_count` and both proceeding. A caller enforcing a limit on
    resource *creation* must take the same precaution the codebase already
    uses for other Home-scoped invariants that can't be expressed as a plain
    unique constraint (see routers.platform's
    `SELECT pg_advisory_xact_lock(...)` around the last-Owner check): acquire
    an advisory lock (or `SELECT ... FOR UPDATE` on the parent Home row)
    before counting and inserting, within the same transaction, so the count
    this function checks can't go stale before the insert commits. No caller
    does this yet in Phase 1 — MyKhaya has no user-facing "create another
    calendar" endpoint at all (see docs/architecture/commercial-entitlements.md
    "Calendar as proof of architecture"), so there is nothing to enforce this
    against yet.

    Phase 6 note: this is now used — see routers.calendar's calendar-creation
    endpoint, which wraps the count-then-call sequence in a
    `pg_advisory_xact_lock` per this docstring's own precaution."""
    limit = await get_limit(db, home_id, key)
    if limit is not None and current_count >= limit:
        raise commercial_restriction_error(
            CommercialRestrictionCode.plan_limit_reached,
            "This would exceed what your current plan allows. Upgrade to add more.",
            entitlement=key,
            limit=limit,
        )


async def calendar_usage(db: AsyncSession, home_id: uuid.UUID) -> CalendarUsageResponse:
    """How many HomeCalendar rows a Home currently has vs. its plan's
    calendar.max_categories. HomeCalendar itself is *not* the resource
    customers manage as "event categories" day to day — see category_usage
    below for that — but it shares the same limit key and is independently
    enforced (routers.calendar's create_calendar), so this stays accurate
    for the Platform Control Centre's commercial-detail diagnostics.

    Personal Calendars (owner_user_id IS NOT NULL) are excluded — they are a
    core per-member capability, not a Home-administered/entitlement-gated
    resource, and must never count against a Free Home's single shared
    calendar allowance just because it has members. See
    routers.calendar._ordered_calendars for the matching exclusion on the
    enforcement side."""
    count = (
        await db.scalar(
            select(func.count())
            .select_from(HomeCalendar)
            .where(HomeCalendar.group_id == home_id, HomeCalendar.owner_user_id.is_(None))
        )
        or 0
    )
    limit = await get_limit(db, home_id, "calendar.max_categories")
    return CalendarUsageResponse(
        count=count, limit=limit, over_limit=limit is not None and count > limit
    )


async def category_usage(db: AsyncSession, home_id: uuid.UUID) -> CalendarUsageResponse:
    """How many *active* CalendarEventLabel rows a Home currently has vs.
    calendar.max_categories. This is the actual resource shown on Settings
    -> Home settings' "Calendars & categories" page — the one customers
    experience as "event categories" (every event belongs to one; its
    colour is what Calendar renders) — see "Event categories are
    CalendarEventLabel, not HomeCalendar" in
    docs/architecture/commercial-entitlements.md. Shares the same limit key
    as calendar_usage/HomeCalendar by design (one entitlement, two
    independently-tracked resources), not a second plan-checking system."""
    count = (
        await db.scalar(
            select(func.count())
            .select_from(CalendarEventLabel)
            .where(CalendarEventLabel.group_id == home_id, CalendarEventLabel.is_active.is_(True))
        )
        or 0
    )
    limit = await get_limit(db, home_id, "calendar.max_categories")
    return CalendarUsageResponse(
        count=count, limit=limit, over_limit=limit is not None and count > limit
    )


async def member_usage(db: AsyncSession, home_id: uuid.UUID) -> CalendarUsageResponse:
    """How many active members a Home currently has vs. its plan's
    home.max_members. Same shared-diagnostic role as calendar_usage — see
    its docstring."""
    count = (
        await db.scalar(
            select(func.count(Membership.id)).where(
                Membership.group_id == home_id, Membership.removed_at.is_(None)
            )
        )
        or 0
    )
    limit = await get_limit(db, home_id, "home.max_members")
    return CalendarUsageResponse(
        count=count, limit=limit, over_limit=limit is not None and count > limit
    )


async def personal_routine_usage(
    db: AsyncSession, home_id: uuid.UUID, user_id: uuid.UUID
) -> CalendarUsageResponse:
    """How many *enabled* personal routines a specific member currently owns
    vs. the Home's plan limit for routines.personal.max_active — the limit
    is per person (see mykhaya.routers.household_routines.create_routine),
    not per Home, so this always takes a user_id rather than aggregating
    across the whole Home."""
    count = (
        await db.scalar(
            select(func.count(HouseholdRoutine.id)).where(
                HouseholdRoutine.group_id == home_id,
                HouseholdRoutine.scope == RoutineScope.personal,
                HouseholdRoutine.owner_user_id == user_id,
                HouseholdRoutine.enabled.is_(True),
            )
        )
        or 0
    )
    limit = await get_limit(db, home_id, "routines.personal.max_active")
    return CalendarUsageResponse(
        count=count, limit=limit, over_limit=limit is not None and count > limit
    )


async def personal_routines_total(db: AsyncSession, home_id: uuid.UUID) -> int:
    """Total enabled personal routines across every member of a Home — an
    informational aggregate for Platform Control Centre display only (the
    limit itself is per person, so this number is never compared directly
    against the limit — see personal_routine_usage for the per-person
    check that's actually enforced)."""
    return (
        await db.scalar(
            select(func.count(HouseholdRoutine.id)).where(
                HouseholdRoutine.group_id == home_id,
                HouseholdRoutine.scope == RoutineScope.personal,
                HouseholdRoutine.enabled.is_(True),
            )
        )
        or 0
    )
