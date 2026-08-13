"""Checkout Session and Customer Portal Session creation. The client only
ever sends a constrained intent (plan=family, interval=month|year) — the
Price ID, currency, amount, Stripe Customer and success/cancel/return URLs
are all resolved server-side from configuration, never from the request.
See docs/architecture/commercial-entitlements.md#checkout-lifecycle and
apps/api/mykhaya/routers/billing.py for the endpoint that calls these.
"""

from __future__ import annotations

import time
import uuid

import stripe
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.billing.client import call_stripe
from mykhaya.billing.config import StripeConfig, StripeNotConfiguredError
from mykhaya.config import Settings
from mykhaya.models import (
    BillingInterval,
    Group,
    HomeSubscription,
    SubscriptionProvider,
    SubscriptionStatus,
)

# Statuses under which MyKhaya already considers a Home to have a live,
# paid-or-paying Stripe relationship — starting a second Checkout while any
# of these hold would risk two simultaneous active subscriptions for the
# same Home.
_LIVE_STRIPE_STATUSES = frozenset(
    {
        SubscriptionStatus.active,
        SubscriptionStatus.trialing,
        SubscriptionStatus.past_due,
        SubscriptionStatus.cancel_at_period_end,
    }
)


class DuplicateSubscriptionError(RuntimeError):
    """This Home already has a live Stripe subscription — raised before any
    Stripe API call is made, so a double-click/duplicate-tab never even
    reaches Stripe."""


class NoStripeCustomerError(RuntimeError):
    """No Stripe Customer exists for this Home yet — the Portal only makes
    sense after at least one Checkout attempt has created one."""


async def get_or_create_customer(
    db: AsyncSession,
    config: StripeConfig,
    home: Group,
    subscription: HomeSubscription,
    actor_email: str,
) -> str:
    """Reuses the Home's existing Stripe Customer if one exists — never
    creates a second Customer for the same Home, including across repeated
    Checkout attempts."""
    if subscription.external_customer_id:
        return subscription.external_customer_id
    assert config.secret_key  # noqa: S101 — caller already checked config.configured
    customer = await call_stripe(
        lambda: stripe.Customer.create(
            name=home.name,
            email=actor_email,
            # Only a non-sensitive identifier — no complimentary reason, no
            # internal notes, nothing beyond what's needed to reconcile a
            # Stripe object back to a Home.
            metadata={"mykhaya_group_id": str(home.id)},
            api_key=config.secret_key,
        )
    )
    subscription.external_customer_id = customer["id"]
    await db.flush()
    return str(customer["id"])


async def create_checkout_session(
    db: AsyncSession,
    settings: Settings,
    config: StripeConfig,
    home: Group,
    subscription: HomeSubscription,
    actor_user_id: uuid.UUID,
    actor_email: str,
    interval: BillingInterval,
) -> str:
    if not config.configured or not config.secret_key:
        raise StripeNotConfiguredError("Stripe billing is not configured.")
    if (
        subscription.provider == SubscriptionProvider.stripe
        and subscription.status in _LIVE_STRIPE_STATUSES
    ):
        raise DuplicateSubscriptionError("This Home already has an active Stripe subscription.")

    price_id = (
        config.family_monthly_price_id
        if interval == BillingInterval.month
        else config.family_annual_price_id
    )
    assert price_id  # noqa: S101 — guaranteed by Settings validation when configured=True

    customer_id = await get_or_create_customer(db, config, home, subscription, actor_email)
    subscription.billing_owner_user_id = actor_user_id
    await db.commit()

    # A short time-bucketed idempotency key: a genuine double-click/duplicate
    # tab within the bucket reuses the same Stripe object instead of creating
    # two; a legitimate later purchase attempt (e.g. after abandoning an
    # earlier one) is not permanently blocked. This is defense-in-depth
    # beneath the _LIVE_STRIPE_STATUSES guard above and the per-Home advisory
    # lock the caller (mykhaya.routers.billing) holds around this call.
    idempotency_key = f"mykhaya-checkout:{home.id}:{interval.value}:{int(time.time() // 300)}"

    session = await call_stripe(
        lambda: stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=(
                f"{settings.public_web_url}/settings/billing"
                "?checkout=success&session_id={CHECKOUT_SESSION_ID}"
            ),
            cancel_url=f"{settings.public_web_url}/settings/billing?checkout=cancelled",
            client_reference_id=str(home.id),
            subscription_data={"metadata": {"mykhaya_group_id": str(home.id)}},
            metadata={"mykhaya_group_id": str(home.id)},
            api_key=config.secret_key,
            idempotency_key=idempotency_key,
        )
    )
    return str(session["url"])


async def create_portal_session(
    settings: Settings, config: StripeConfig, subscription: HomeSubscription
) -> str:
    if not config.configured or not config.secret_key:
        raise StripeNotConfiguredError("Stripe billing is not configured.")
    customer_id = subscription.external_customer_id
    if not customer_id:
        raise NoStripeCustomerError("This Home has no Stripe Customer yet.")
    session = await call_stripe(
        lambda: stripe.billing_portal.Session.create(
            customer=customer_id,
            # Always MyKhaya's own configured public URL — never an
            # untrusted request header (e.g. Referer/Origin), which an
            # attacker could otherwise use to redirect a billing manager
            # somewhere unexpected after they finish in the Portal.
            return_url=f"{settings.public_web_url}/settings/billing",
            api_key=config.secret_key,
        )
    )
    return str(session["url"])
