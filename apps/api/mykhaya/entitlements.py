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
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.models import (
    HomeSubscription,
    HomeSubscriptionEvent,
    SubscriptionPlan,
    SubscriptionProvider,
    SubscriptionStatus,
)

# Statuses under which a subscription's own `plan` is actually honoured.
# past_due deliberately still counts as active — MyKhaya doesn't have payment
# retry/dunning logic yet (that's Phase 3 territory), so treating a first
# missed payment as an instant downgrade would be needlessly harsh; a fully
# `cancelled` subscription (or one whose complimentary access has expired)
# resolves to Free.
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
    # Numeric limits, e.g. "calendar.max_calendars". None means unlimited.
    limits: dict[str, int | None]


# The one place plan capabilities are defined. Adding an entitlement later is
# "add a key here" — never `if home.plan == "family"` scattered through
# routers. Modules not yet ready for commercial enforcement (lists/chores/
# notes/wishlists don't exist as real features yet) are declared here as data
# only; nothing currently calls require_entitlement() against them.
PLAN_DEFINITIONS: dict[SubscriptionPlan, PlanDefinition] = {
    SubscriptionPlan.free: PlanDefinition(
        plan=SubscriptionPlan.free,
        booleans={
            "lists.enabled": False,
            "chores.enabled": False,
            "notes.enabled": False,
            "wishlists.enabled": False,
        },
        limits={"calendar.max_calendars": 1},
    ),
    SubscriptionPlan.family: PlanDefinition(
        plan=SubscriptionPlan.family,
        booleans={
            "lists.enabled": True,
            "chores.enabled": True,
            "notes.enabled": True,
            "wishlists.enabled": True,
        },
        limits={"calendar.max_calendars": None},
    ),
}


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


async def effective_plan(db: AsyncSession, home_id: uuid.UUID) -> SubscriptionPlan:
    """The single authoritative resolution. See module docstring for the
    fail-safe rules this enforces."""
    subscription = await get_home_subscription(db, home_id)
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


async def _plan_definition(db: AsyncSession, home_id: uuid.UUID) -> PlanDefinition:
    plan = await effective_plan(db, home_id)
    return PLAN_DEFINITIONS[plan]


async def has_entitlement(db: AsyncSession, home_id: uuid.UUID, key: str) -> bool:
    definition = await _plan_definition(db, home_id)
    return definition.booleans.get(key, False)  # unknown key -> not entitled


async def require_entitlement(db: AsyncSession, home_id: uuid.UUID, key: str) -> None:
    if not await has_entitlement(db, home_id, key):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This feature isn't included in your current plan."
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
    against yet."""
    limit = await get_limit(db, home_id, key)
    if limit is not None and current_count >= limit:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This would exceed what your current plan allows. Upgrade to add more.",
        )
