"""Support/operations reconciliation: answers "what does Stripe currently
say this Home's subscription state is?" and applies it through the exact
same normalized transition logic webhooks use (mykhaya.billing.state) — see
docs/architecture/commercial-entitlements.md#reconciliation. There is no
separate mutation path here; this only ever calls apply_stripe_subscription_state
with the authoritative current Stripe object.
"""

from __future__ import annotations

import uuid

import stripe
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.billing.client import call_stripe
from mykhaya.billing.config import StripeConfig, StripeNotConfiguredError
from mykhaya.billing.state import apply_stripe_subscription_state
from mykhaya.entitlements import ensure_home_subscription, get_home_subscription
from mykhaya.models import HomeSubscription


class NoStripeSubscriptionError(RuntimeError):
    """This Home has no external_subscription_id to reconcile against."""


class CheckoutConfirmationError(RuntimeError):
    """The supplied Checkout Session is not valid for this Home."""


class CheckoutNotCompleteError(CheckoutConfirmationError):
    """Stripe has not completed the Checkout Session or its subscription yet."""


def _stripe_id(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        raw_id = value.get("id")
        return str(raw_id) if raw_id else None
    return None


async def confirm_checkout_session(
    db: AsyncSession,
    config: StripeConfig,
    group_id: uuid.UUID,
    session_id: str,
) -> tuple[bool, HomeSubscription]:
    """Validate one Checkout Session and reconcile its current subscription.

    The session ID is only a lookup handle. Home ownership, completion,
    subscription identity, and configured-price membership are verified from
    Stripe's server response before Family state can be applied.
    """
    if not config.configured or not config.secret_key:
        raise StripeNotConfiguredError("Stripe billing is not configured.")

    session = await call_stripe(
        lambda: stripe.checkout.Session.retrieve(
            session_id,
            expand=["subscription", "customer"],
            api_key=config.secret_key,
        )
    )
    session_group_raw = (session.get("metadata") or {}).get("mykhaya_group_id") or session.get(
        "client_reference_id"
    )
    try:
        session_group_id = uuid.UUID(str(session_group_raw))
    except (ValueError, TypeError):
        raise CheckoutConfirmationError(
            "The Checkout Session is not linked to a MyKhaya Home."
        ) from None
    if session_group_id != group_id:
        raise CheckoutConfirmationError("The Checkout Session does not belong to this Home.")
    if session.get("mode") != "subscription":
        raise CheckoutConfirmationError("The Checkout Session is not a subscription checkout.")
    if session.get("status") != "complete":
        subscription = await ensure_home_subscription(db, group_id)
        await db.commit()
        return False, subscription

    session_customer_id = _stripe_id(session.get("customer"))
    session_subscription_id = _stripe_id(session.get("subscription"))
    if not session_subscription_id or not session_customer_id:
        raise CheckoutNotCompleteError("Stripe has not attached the subscription yet.")

    stripe_subscription = await call_stripe(
        lambda: stripe.Subscription.retrieve(
            session_subscription_id,
            expand=["customer"],
            api_key=config.secret_key,
        )
    )
    subscription_id = _stripe_id(stripe_subscription.get("id"))
    customer_id = _stripe_id(stripe_subscription.get("customer"))
    if subscription_id != session_subscription_id or customer_id != session_customer_id:
        raise CheckoutConfirmationError("Stripe returned inconsistent Checkout identifiers.")
    subscription_group_raw = (stripe_subscription.get("metadata") or {}).get("mykhaya_group_id")
    if subscription_group_raw and str(subscription_group_raw) != str(group_id):
        raise CheckoutConfirmationError("The Stripe subscription does not belong to this Home.")

    items = (stripe_subscription.get("items") or {}).get("data") or []
    price_id = ((items[0].get("price") or {}).get("id") if items else None)
    if price_id not in {config.family_monthly_price_id, config.family_annual_price_id}:
        raise CheckoutConfirmationError(
            "The Stripe subscription does not use a configured Family price."
        )

    reconciled = await apply_stripe_subscription_state(
        db,
        group_id=group_id,
        stripe_subscription=stripe_subscription,
        actor_administrator_id=None,
        reason=f"Checkout confirmation {session_id}",
        event_type_hint="stripe_checkout_confirmed",
    )
    subscription = reconciled or await ensure_home_subscription(db, group_id)
    subscription.external_customer_id = session_customer_id
    subscription.external_subscription_id = session_subscription_id
    await db.commit()
    return True, subscription


async def reconcile_home_subscription(
    db: AsyncSession,
    config: StripeConfig,
    group_id: uuid.UUID,
    *,
    actor_administrator_id: uuid.UUID,
) -> HomeSubscription | None:
    if not config.configured or not config.secret_key:
        raise StripeNotConfiguredError("Stripe billing is not configured.")
    subscription = await get_home_subscription(db, group_id)
    subscription_id = subscription.external_subscription_id if subscription else None
    if not subscription_id:
        raise NoStripeSubscriptionError("This Home has no Stripe subscription to reconcile.")

    stripe_subscription = await call_stripe(
        lambda: stripe.Subscription.retrieve(subscription_id, api_key=config.secret_key)
    )
    return await apply_stripe_subscription_state(
        db,
        group_id=group_id,
        stripe_subscription=stripe_subscription,
        actor_administrator_id=actor_administrator_id,
        reason="Manual reconciliation from the Platform Control Centre",
        event_type_hint="stripe_reconciled",
    )
