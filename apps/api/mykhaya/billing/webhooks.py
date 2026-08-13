"""Stripe webhook verification and processing — the sole authoritative path
for Stripe-driven commercial state changes (see
docs/architecture/commercial-entitlements.md#webhooks). Nothing here trusts
a browser redirect or any ordinary authenticated API call as a substitute.

Idempotency: a StripeWebhookEvent row (unique on stripe_event_id) is
inserted in the *same* transaction as any resulting HomeSubscription
mutation, committed together. A duplicate delivery of an already-processed
event is detected before any mutation is attempted and short-circuits to a
no-op. A processing *failure* deliberately does NOT commit a dedup row —
the whole transaction rolls back so Stripe's automatic retry can succeed
later, rather than the event being silently and permanently dropped.

Event scope: only the lifecycle events MyKhaya actually acts on are
processed (see _HANDLED_EVENT_TYPES). Anything else Stripe might send is
acknowledged (200) and recorded as "ignored" — never a hard failure, since
an unrecognised-but-valid event is not an error on MyKhaya's part.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import stripe
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.billing.client import call_stripe
from mykhaya.billing.config import StripeConfig
from mykhaya.billing.state import apply_stripe_subscription_state
from mykhaya.models import HomeSubscription, StripeWebhookEvent

_HANDLED_EVENT_TYPES = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.payment_succeeded",
        "invoice.payment_failed",
    }
)


class WebhookSignatureError(RuntimeError):
    """Signature verification failed — the request is rejected outright
    (400) before any database work happens."""


def verify_and_parse_event(payload: bytes, signature_header: str, webhook_secret: str) -> Any:
    try:
        event: Any = stripe.Webhook.construct_event(  # type: ignore[no-untyped-call]
            payload, signature_header, webhook_secret
        )
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise WebhookSignatureError("Invalid Stripe webhook signature.") from exc
    return event


async def _resolve_group_id(
    db: AsyncSession, event_type: str, data_object: dict[str, Any]
) -> uuid.UUID | None:
    """Prefers the mykhaya_group_id metadata/client_reference_id MyKhaya
    itself attached at Checkout time. Invoice events (and any Subscription
    object that, for whatever reason, arrives without that metadata) fall
    back to looking the Home up by whichever Stripe identifier the payload
    does carry — the same identifiers already stored uniquely on
    HomeSubscription from a prior event."""
    raw = (data_object.get("metadata") or {}).get("mykhaya_group_id") or data_object.get(
        "client_reference_id"
    )
    if raw:
        try:
            return uuid.UUID(str(raw))
        except ValueError:
            pass

    subscription_id = data_object.get("subscription") or (
        data_object.get("id") if event_type.startswith("customer.subscription.") else None
    )
    customer_id = data_object.get("customer")
    conditions = []
    if subscription_id:
        conditions.append(HomeSubscription.external_subscription_id == subscription_id)
    if customer_id:
        conditions.append(HomeSubscription.external_customer_id == customer_id)
    if not conditions:
        return None
    subscription = await db.scalar(select(HomeSubscription).where(or_(*conditions)))
    return subscription.group_id if subscription else None


async def _lock_home(db: AsyncSession, group_id: uuid.UUID) -> None:
    """Serialises concurrent webhook processing for the same Home within
    this transaction — matches the pg_advisory_xact_lock pattern already
    used elsewhere in the codebase (see routers.platform's
    OWNER_MEMBERSHIP_LOCK_KEY) rather than inventing a second locking
    convention."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"billing:{group_id}"}
    )


async def _handle_checkout_completed(
    db: AsyncSession, group_id: uuid.UUID, session_obj: dict[str, Any]
) -> None:
    """Records the customer/subscription IDs for reconciliation only —
    never grants Family here. See module docstring and
    docs/architecture/commercial-entitlements.md#checkout-lifecycle for why
    checkout completion is not the activation signal."""
    from mykhaya.entitlements import ensure_home_subscription

    subscription = await ensure_home_subscription(db, group_id)
    customer_id = session_obj.get("customer")
    subscription_id = session_obj.get("subscription")
    if customer_id and not subscription.external_customer_id:
        subscription.external_customer_id = customer_id
    if subscription_id and not subscription.external_subscription_id:
        subscription.external_subscription_id = subscription_id


async def _handle_subscription_event(
    db: AsyncSession,
    group_id: uuid.UUID,
    subscription_obj: dict[str, Any],
    *,
    event_id: str,
    event_type: str,
    hint: str,
) -> None:
    await apply_stripe_subscription_state(
        db,
        group_id=group_id,
        stripe_subscription=subscription_obj,
        actor_administrator_id=None,
        reason=f"Stripe webhook {event_type} ({event_id})",
        event_type_hint=hint,
    )


async def _handle_invoice_event(
    db: AsyncSession,
    group_id: uuid.UUID,
    invoice_obj: dict[str, Any],
    config: StripeConfig,
    *,
    event_id: str,
    event_type: str,
    hint: str,
) -> None:
    """Refetches the current Stripe Subscription object rather than trusting
    the invoice payload's own snapshot of subscription state — the
    out-of-order-safe pattern documented in
    docs/architecture/commercial-entitlements.md#out-of-order-events."""
    subscription_id = invoice_obj.get("subscription")
    if not subscription_id or not config.secret_key:
        return
    stripe_subscription = await call_stripe(
        lambda: stripe.Subscription.retrieve(subscription_id, api_key=config.secret_key)
    )
    await apply_stripe_subscription_state(
        db,
        group_id=group_id,
        stripe_subscription=stripe_subscription,
        actor_administrator_id=None,
        reason=f"Stripe webhook {event_type} ({event_id})",
        event_type_hint=hint,
    )


async def process_webhook_event(
    db: AsyncSession, event: dict[str, Any], config: StripeConfig
) -> str:
    """Returns "processed" or "ignored" on success. Raises on a genuine
    processing failure — the caller (mykhaya.routers.billing) rolls back and
    returns a non-2xx so Stripe retries; no StripeWebhookEvent row is
    committed for a failed attempt, so the retry is not deduplicated away."""
    event_id = event["id"]
    event_type = event["type"]

    existing = await db.scalar(
        select(StripeWebhookEvent).where(StripeWebhookEvent.stripe_event_id == event_id)
    )
    if existing is not None:
        return str(existing.outcome)

    data_object = event["data"]["object"]
    group_id = await _resolve_group_id(db, event_type, data_object)
    if group_id is not None:
        await _lock_home(db, group_id)
        # Re-check after acquiring the lock — a concurrent delivery of the
        # same event could have committed between the check above and the
        # lock being granted.
        existing = await db.scalar(
            select(StripeWebhookEvent).where(StripeWebhookEvent.stripe_event_id == event_id)
        )
        if existing is not None:
            return str(existing.outcome)

    outcome = "ignored"
    if event_type not in _HANDLED_EVENT_TYPES or group_id is None:
        outcome = "ignored"
    elif event_type == "checkout.session.completed":
        await _handle_checkout_completed(db, group_id, data_object)
        outcome = "processed"
    elif event_type == "customer.subscription.created":
        await _handle_subscription_event(
            db,
            group_id,
            data_object,
            event_id=event_id,
            event_type=event_type,
            hint="stripe_subscription_activated",
        )
        outcome = "processed"
    elif event_type == "customer.subscription.updated":
        await _handle_subscription_event(
            db,
            group_id,
            data_object,
            event_id=event_id,
            event_type=event_type,
            hint="stripe_subscription_updated",
        )
        outcome = "processed"
    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_event(
            db,
            group_id,
            data_object,
            event_id=event_id,
            event_type=event_type,
            hint="stripe_subscription_cancelled",
        )
        outcome = "processed"
    elif event_type == "invoice.payment_succeeded":
        await _handle_invoice_event(
            db,
            group_id,
            data_object,
            config,
            event_id=event_id,
            event_type=event_type,
            hint="stripe_subscription_renewed",
        )
        outcome = "processed"
    elif event_type == "invoice.payment_failed":
        await _handle_invoice_event(
            db,
            group_id,
            data_object,
            config,
            event_id=event_id,
            event_type=event_type,
            hint="stripe_payment_failed",
        )
        outcome = "processed"

    db.add(
        StripeWebhookEvent(
            stripe_event_id=event_id,
            event_type=event_type,
            group_id=group_id,
            processed_at=datetime.now(UTC),
            outcome=outcome,
        )
    )
    await db.commit()
    return outcome
