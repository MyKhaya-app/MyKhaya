"""The single function that turns a Stripe Subscription object into
HomeSubscription state (apply_stripe_subscription_state) — called by both
the webhook handler (mykhaya.billing.webhooks) and the Platform Control
Centre's manual reconciliation action (mykhaya.billing.reconciliation), so
there is exactly one place this mapping is written and exactly one place
the out-of-order-event strategy is documented.

Explicit Stripe status -> MyKhaya SubscriptionStatus mapping (never a blind
copy of Stripe's status string):

    active               -> active
    trialing             -> trialing
    past_due             -> past_due
    unpaid               -> past_due   (still within grace — see the dunning
                                         policy note on
                                         mykhaya.entitlements._PLAN_HONOURED_STATUSES)
    paused               -> past_due   (billing paused, not cancelled)
    canceled             -> cancelled
    incomplete_expired   -> cancelled  (first payment never completed in time)
    incomplete           -> no change  (first payment not yet confirmed — see
                                         "Activation rule" below)
    anything unrecognised -> no change (fail safe: never invented, never guessed)

`active`/`trialing` are downgraded to `cancel_at_period_end` when Stripe's own
`cancel_at_period_end` flag is set, since MyKhaya represents that as a status
value rather than a separate boolean (Phase 1's existing SubscriptionStatus
enum already had this member, unused until now).

Activation rule: initial Family activation never happens on
`checkout.session.completed` alone — only once Stripe itself reports a
confirmed billing status (`active`/`trialing` — i.e. the mapped
SubscriptionStatus is in `mykhaya.entitlements._PLAN_HONOURED_STATUSES`).
`checkout.session.completed` only records the customer/subscription IDs for
reconciliation; see docs/architecture/commercial-entitlements.md#checkout-lifecycle.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.entitlements import get_home_subscription, record_subscription_event
from mykhaya.models import (
    BillingInterval,
    HomeSubscription,
    SubscriptionPlan,
    SubscriptionProvider,
    SubscriptionStatus,
)


class SubscriptionOwnershipMismatchError(RuntimeError):
    """The Stripe Subscription object's own mykhaya_group_id metadata (set at
    Checkout time — see mykhaya.billing.checkout.create_checkout_session)
    disagrees with the group_id the caller is applying it to. This should be
    unreachable in the webhook path (group_id there is *derived from* this
    same metadata, or from a HomeSubscription row already scoped to the
    right Home) and in today's reconciliation path (which only ever
    re-fetches a Subscription ID already on file for that Home) — it exists
    as defence-in-depth against a future code path, data-integrity bug, or
    operator error attaching the wrong Stripe object to a Home. See
    "Reconciliation authority" in docs/security/platform-administration-security.md."""


class SubscriptionStateOutcome(StrEnum):
    APPLIED = "applied"
    UNCHANGED = "unchanged"
    STALE_EVENT = "stale_event"
    UNKNOWN_PRICE_ID = "unknown_price_id"
    MISSING_OR_AMBIGUOUS_ITEM = "missing_or_ambiguous_item"
    OWNERSHIP_MISMATCH = "ownership_mismatch"
    INVALID_STATE = "invalid_state"


@dataclass(frozen=True)
class SubscriptionStateResult:
    """Structured result for Stripe state application."""

    outcome: SubscriptionStateOutcome
    subscription: HomeSubscription | None = None
    reason: str | None = None
    retryable: bool = False

    @property
    def status(self) -> SubscriptionStatus | None:
        """Expose the legacy subscription status without losing ``outcome``.

        A number of callers historically treated the return value as the
        ``HomeSubscription`` itself.  Keeping this read-only compatibility
        property makes the result migration safe while ``outcome`` remains
        the authoritative processing classification.
        """
        return self.subscription.status if self.subscription is not None else None

    def __getattr__(self, name: str) -> Any:
        """Keep older internal callers source-compatible during migration."""
        if self.subscription is not None:
            return getattr(self.subscription, name)
        raise AttributeError(name)

    @property
    def outcome_status(self) -> SubscriptionStateOutcome:
        """Short alias for integrations that prefer a status-like name."""
        return self.outcome


_STRIPE_STATUS_MAP: dict[str, SubscriptionStatus] = {
    "active": SubscriptionStatus.active,
    "trialing": SubscriptionStatus.trialing,
    "past_due": SubscriptionStatus.past_due,
    "unpaid": SubscriptionStatus.past_due,
    "paused": SubscriptionStatus.past_due,
    "canceled": SubscriptionStatus.cancelled,
    "incomplete_expired": SubscriptionStatus.cancelled,
}


def _stripe_object_id(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        raw_id = value.get("id")
        return str(raw_id) if raw_id else None
    return None


def map_stripe_subscription_status(
    stripe_subscription: dict[str, Any],
) -> SubscriptionStatus | None:
    """None means "no confirmed, recognised state to apply" — the caller
    must make no mutation, per this module's fail-safe contract."""
    raw_status = stripe_subscription.get("status")
    if raw_status == "incomplete" or raw_status not in _STRIPE_STATUS_MAP:
        return None
    mapped = _STRIPE_STATUS_MAP[raw_status]
    if mapped in (
        SubscriptionStatus.active,
        SubscriptionStatus.trialing,
    ) and stripe_subscription.get("cancel_at_period_end"):
        return SubscriptionStatus.cancel_at_period_end
    return mapped


def select_subscription_item(
    stripe_subscription: dict[str, Any],
    *,
    preferred_price_id: str | None = None,
    known_price_ids: set[str] | None = None,
) -> dict[str, Any] | None:
    """Select the MyKhaya recurring item without assuming Stripe's order.

    A stored current Price ID is the strongest signal. For webhook and
    reconciliation payloads, configured MyKhaya Price IDs are the next-best
    signal. A single-item subscription remains unambiguous even when its
    grandfathered Price is no longer in current configuration. Multiple items
    without exactly one matching signal are rejected safely.
    """
    items = (stripe_subscription.get("items") or {}).get("data") or []
    if not items:
        return None
    if preferred_price_id:
        matches = [
            item for item in items if _stripe_object_id(item.get("price")) == preferred_price_id
        ]
        if len(matches) == 1:
            return matches[0]
    if known_price_ids:
        matches = [
            item
            for item in items
            if (_stripe_object_id(item.get("price")) or "") in known_price_ids
        ]
        if len(matches) == 1:
            return matches[0]
    return items[0] if len(items) == 1 else None


def extract_price_and_interval(
    stripe_subscription: dict[str, Any],
    *,
    preferred_price_id: str | None = None,
    known_price_ids: set[str] | None = None,
) -> tuple[str | None, BillingInterval | None]:
    item = select_subscription_item(
        stripe_subscription,
        preferred_price_id=preferred_price_id,
        known_price_ids=known_price_ids,
    )
    if item is None:
        return None, None
    price = item.get("price") or {}
    price_id = _stripe_object_id(price)
    recurring = price.get("recurring") or {} if isinstance(price, dict) else {}
    interval_raw = recurring.get("interval")
    interval = BillingInterval(interval_raw) if interval_raw in ("month", "year") else None
    return price_id, interval


def extract_period(
    stripe_subscription: dict[str, Any],
    *,
    item: dict[str, Any] | None = None,
) -> tuple[datetime | None, datetime | None]:
    """Stripe's 2025 API versions moved current_period_start/end from the
    subscription object onto its first item for multi-item-subscription
    support. Read the subscription-level fields first (older/simpler
    accounts and API versions), falling back to the first item's fields —
    deliberately defensive rather than pinned to one API shape, since the
    exact fields present depend on the Stripe account's configured API
    version."""
    start = stripe_subscription.get("current_period_start")
    end = stripe_subscription.get("current_period_end")
    if start is None or end is None:
        if item is None:
            item = select_subscription_item(stripe_subscription)
        if item is not None:
            start = start if start is not None else item.get("current_period_start")
            end = end if end is not None else item.get("current_period_end")
    return (
        datetime.fromtimestamp(start, tz=UTC) if start is not None else None,
        datetime.fromtimestamp(end, tz=UTC) if end is not None else None,
    )


def _pick_event_type(
    from_provider: SubscriptionProvider,
    from_status: SubscriptionStatus,
    to_status: SubscriptionStatus,
    hint: str,
) -> str:
    """The caller's `hint` (why it's calling — activation, a routine update,
    a renewal, a manual reconciliation) is used unless the actual before/after
    state transition is one of the specific, named categories Platform
    Control Centre history should call out distinctly (see
    docs/architecture/commercial-entitlements.md#commercial-event-history)."""
    if from_provider != SubscriptionProvider.stripe:
        return "stripe_subscription_activated"
    if to_status == SubscriptionStatus.cancelled:
        return "stripe_subscription_cancelled"
    if (
        to_status == SubscriptionStatus.cancel_at_period_end
        and from_status != SubscriptionStatus.cancel_at_period_end
    ):
        return "stripe_cancellation_scheduled"
    if from_status == SubscriptionStatus.cancel_at_period_end and to_status in (
        SubscriptionStatus.active,
        SubscriptionStatus.trialing,
    ):
        return "stripe_cancellation_reversed"
    if to_status == SubscriptionStatus.past_due and from_status != SubscriptionStatus.past_due:
        return "stripe_payment_failed"
    if from_status == SubscriptionStatus.past_due and to_status in (
        SubscriptionStatus.active,
        SubscriptionStatus.trialing,
    ):
        return "stripe_payment_recovered"
    return hint


async def apply_stripe_subscription_state(
    db: AsyncSession,
    *,
    group_id: uuid.UUID,
    stripe_subscription: dict[str, Any],
    actor_administrator_id: uuid.UUID | None,
    reason: str,
    event_type_hint: str,
    plan_by_price: dict[str, SubscriptionPlan] | None = None,
) -> SubscriptionStateResult:
    """Apply authoritative Stripe state and report why it did or did not apply."""
    mapped_status = map_stripe_subscription_status(stripe_subscription)
    if mapped_status is None:
        return SubscriptionStateResult(
            SubscriptionStateOutcome.INVALID_STATE,
            reason="unrecognised_or_unconfirmed_stripe_status",
            retryable=False,
        )

    # Renewal and purge must serialize on the same Home lifecycle lock.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"family-retention:{group_id}"},
    )

    metadata_group_id_raw = (stripe_subscription.get("metadata") or {}).get("mykhaya_group_id")
    if metadata_group_id_raw:
        try:
            metadata_group_id = uuid.UUID(str(metadata_group_id_raw))
        except ValueError:
            metadata_group_id = None
        if metadata_group_id is not None and metadata_group_id != group_id:
            return SubscriptionStateResult(
                SubscriptionStateOutcome.OWNERSHIP_MISMATCH,
                reason="subscription_metadata_home_mismatch",
                retryable=False,
            )

    subscription = await get_home_subscription(db, group_id)
    if subscription is None:
        subscription = HomeSubscription(group_id=group_id)
        db.add(subscription)
        await db.flush()

    incoming_subscription_id = _stripe_object_id(stripe_subscription.get("id"))
    current_subscription_id = subscription.external_subscription_id
    incoming_customer_id = _stripe_object_id(stripe_subscription.get("customer"))

    if subscription.external_customer_id and not incoming_customer_id:
        return SubscriptionStateResult(
            SubscriptionStateOutcome.OWNERSHIP_MISMATCH,
            reason="subscription_customer_missing",
            retryable=False,
        )
    if (
        subscription.external_customer_id
        and incoming_customer_id != subscription.external_customer_id
    ):
        return SubscriptionStateResult(
            SubscriptionStateOutcome.OWNERSHIP_MISMATCH,
            reason="subscription_customer_mismatch",
            retryable=False,
        )

    # Out-of-order guard 1: an event for a *different* subscription ID than
    # the one currently tracked (and that tracked one hasn't itself already
    # ended) is almost always a stale event for a superseded subscription —
    # never let it override newer known state.
    if (
        current_subscription_id
        and incoming_subscription_id
        and current_subscription_id != incoming_subscription_id
        and subscription.status != SubscriptionStatus.cancelled
    ):
        return SubscriptionStateResult(
            SubscriptionStateOutcome.STALE_EVENT,
            subscription=subscription,
            reason="different_active_subscription_id",
        )

    known_price_ids = set(plan_by_price or {})
    item = select_subscription_item(
        stripe_subscription,
        preferred_price_id=subscription.external_price_id,
        known_price_ids=known_price_ids,
    )
    if item is None:
        return SubscriptionStateResult(
            SubscriptionStateOutcome.MISSING_OR_AMBIGUOUS_ITEM,
            subscription=subscription,
            reason="no_unique_subscription_item",
            retryable=True,
        )
    price = item.get("price") or {}
    price_id = _stripe_object_id(price)
    recurring = price.get("recurring") or {}
    interval_raw = recurring.get("interval")
    interval = BillingInterval(interval_raw) if interval_raw in ("month", "year") else None
    if not price_id or interval is None:
        return SubscriptionStateResult(
            SubscriptionStateOutcome.INVALID_STATE,
            subscription=subscription,
            reason="price_id_or_billing_interval_missing",
            retryable=True,
        )
    requested_plan = (stripe_subscription.get("metadata") or {}).get("mykhaya_plan")
    price_plan = plan_by_price.get(price_id) if plan_by_price and price_id else None
    if plan_by_price is not None and price_plan is None:
        return SubscriptionStateResult(
            SubscriptionStateOutcome.UNKNOWN_PRICE_ID,
            subscription=subscription,
            reason="price_id_not_in_configured_plan_mapping",
            retryable=True,
        )
    try:
        incoming_plan = price_plan or SubscriptionPlan(
            requested_plan or SubscriptionPlan.family.value
        )
    except ValueError:
        return SubscriptionStateResult(
            SubscriptionStateOutcome.INVALID_STATE,
            subscription=subscription,
            reason="invalid_plan_metadata",
            retryable=True,
        )
    period_start, period_end = extract_period(stripe_subscription, item=item)

    # Out-of-order guard 2: for the *same* subscription ID, current_period_end
    # only ever advances forward until cancellation — a delayed/retried event
    # carrying an older period_end than what's already stored is stale.
    # Cancellation events are exempt (a cancellation's period_end is not
    # expected to be later than the last renewal's).
    if (
        current_subscription_id == incoming_subscription_id
        and subscription.current_period_end is not None
        and period_end is not None
        and period_end < subscription.current_period_end
        and mapped_status != SubscriptionStatus.cancelled
    ):
        return SubscriptionStateResult(
            SubscriptionStateOutcome.STALE_EVENT,
            subscription=subscription,
            reason="older_subscription_period_end",
        )

    from_plan, from_provider, from_status = (
        subscription.plan,
        subscription.provider,
        subscription.status,
    )
    was_complimentary = subscription.provider == SubscriptionProvider.complimentary
    customer_id = incoming_customer_id

    materially_changed = (
        subscription.provider != SubscriptionProvider.stripe
        or subscription.status != mapped_status
        or subscription.plan != incoming_plan
        or subscription.external_price_id != price_id
        or subscription.billing_interval != interval
        or subscription.external_subscription_id != incoming_subscription_id
    )

    subscription.plan = incoming_plan
    subscription.provider = SubscriptionProvider.stripe
    subscription.status = mapped_status
    subscription.external_customer_id = subscription.external_customer_id or customer_id
    subscription.external_subscription_id = incoming_subscription_id
    subscription.external_price_id = price_id
    subscription.billing_interval = interval
    subscription.current_period_start = period_start
    subscription.current_period_end = period_end
    pending_matches = (
        subscription.pending_plan is not None
        and subscription.pending_plan == incoming_plan
        and (
            subscription.pending_billing_interval is None
            or subscription.pending_billing_interval == interval
        )
    )
    # A verified Stripe update is the only authority that clears a pending
    # local transition. For a scheduled Free downgrade, Stripe reports the
    # terminal cancellation instead of a Free price, so that status also
    # completes the pending request.
    pending_cleared = pending_matches or (
        subscription.pending_plan == SubscriptionPlan.free
        and mapped_status == SubscriptionStatus.cancelled
    )
    if pending_cleared:
        subscription.pending_plan = None
        subscription.pending_billing_interval = None
        subscription.pending_effective_at = None
        subscription.stripe_schedule_id = None
    if was_complimentary:
        # The transition itself is preserved in HomeSubscriptionEvent history
        # below (from_provider=complimentary); these live fields would
        # otherwise sit stale and misleading once Stripe is authoritative.
        subscription.complimentary_reason = None
        subscription.complimentary_note = None
        subscription.complimentary_expires_at = None

    from mykhaya.family_retention import restore_family_retention

    await restore_family_retention(db, group_id)
    if not materially_changed and not pending_cleared:
        return SubscriptionStateResult(
            SubscriptionStateOutcome.UNCHANGED,
            subscription=subscription,
        )

    event_type = _pick_event_type(from_provider, from_status, mapped_status, event_type_hint)
    await record_subscription_event(
        db,
        group_id,
        event_type=event_type,
        from_plan=from_plan,
        to_plan=subscription.plan,
        from_provider=from_provider,
        to_provider=subscription.provider,
        from_status=from_status,
        to_status=subscription.status,
        actor_administrator_id=actor_administrator_id,
        reason=reason,
    )
    return SubscriptionStateResult(
        SubscriptionStateOutcome.APPLIED,
        subscription=subscription,
    )
