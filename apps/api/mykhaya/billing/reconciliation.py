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
from mykhaya.entitlements import get_home_subscription
from mykhaya.models import HomeSubscription


class NoStripeSubscriptionError(RuntimeError):
    """This Home has no external_subscription_id to reconcile against."""


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
