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
from datetime import UTC, datetime
from typing import Any

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


def extract_price_and_interval(
    stripe_subscription: dict[str, Any],
) -> tuple[str | None, BillingInterval | None]:
    items = (stripe_subscription.get("items") or {}).get("data") or []
    if not items:
        return None, None
    price = items[0].get("price") or {}
    price_id = price.get("id")
    recurring = price.get("recurring") or {}
    interval_raw = recurring.get("interval")
    interval = BillingInterval(interval_raw) if interval_raw in ("month", "year") else None
    return price_id, interval


def extract_period(stripe_subscription: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
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
        items = (stripe_subscription.get("items") or {}).get("data") or []
        if items:
            start = start if start is not None else items[0].get("current_period_start")
            end = end if end is not None else items[0].get("current_period_end")
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
) -> HomeSubscription | None:
    """Returns the updated HomeSubscription, or None if the incoming Stripe
    object produced no mutation (unrecognised/unconfirmed status, or a
    stale/out-of-order event — see module docstring and the two guards
    below)."""
    mapped_status = map_stripe_subscription_status(stripe_subscription)
    if mapped_status is None:
        return None

    metadata_group_id_raw = (stripe_subscription.get("metadata") or {}).get("mykhaya_group_id")
    if metadata_group_id_raw:
        try:
            metadata_group_id = uuid.UUID(str(metadata_group_id_raw))
        except ValueError:
            metadata_group_id = None
        if metadata_group_id is not None and metadata_group_id != group_id:
            raise SubscriptionOwnershipMismatchError(
                f"Stripe subscription metadata belongs to Home {metadata_group_id}, not {group_id}."
            )

    subscription = await get_home_subscription(db, group_id)
    if subscription is None:
        subscription = HomeSubscription(group_id=group_id)
        db.add(subscription)
        await db.flush()

    incoming_subscription_id = _stripe_object_id(stripe_subscription.get("id"))
    current_subscription_id = subscription.external_subscription_id

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
        return None

    price_id, interval = extract_price_and_interval(stripe_subscription)
    period_start, period_end = extract_period(stripe_subscription)

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
        return None

    from_plan, from_provider, from_status = (
        subscription.plan,
        subscription.provider,
        subscription.status,
    )
    was_complimentary = subscription.provider == SubscriptionProvider.complimentary
    customer_id = _stripe_object_id(stripe_subscription.get("customer"))

    materially_changed = (
        subscription.provider != SubscriptionProvider.stripe
        or subscription.status != mapped_status
        or subscription.external_price_id != price_id
        or subscription.billing_interval != interval
        or subscription.external_subscription_id != incoming_subscription_id
    )

    subscription.plan = SubscriptionPlan.family
    subscription.provider = SubscriptionProvider.stripe
    subscription.status = mapped_status
    subscription.external_customer_id = subscription.external_customer_id or customer_id
    subscription.external_subscription_id = incoming_subscription_id
    subscription.external_price_id = price_id
    subscription.billing_interval = interval
    subscription.current_period_start = period_start
    subscription.current_period_end = period_end
    if was_complimentary:
        # The transition itself is preserved in HomeSubscriptionEvent history
        # below (from_provider=complimentary); these live fields would
        # otherwise sit stale and misleading once Stripe is authoritative.
        subscription.complimentary_reason = None
        subscription.complimentary_note = None
        subscription.complimentary_expires_at = None

    if not materially_changed:
        return subscription

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
    return subscription
