"""Safe self-service changes to an existing Stripe subscription.

All prices and subscription identifiers are resolved server-side. Stripe is
the authority for previews, invoices and payment state; MyKhaya entitlements
change only after the existing verified webhook/reconciliation path observes
the resulting subscription state.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import stripe
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.billing.client import StripeRequestError, StripeUnavailableError, call_stripe
from mykhaya.billing.config import StripeConfig, StripeNotConfiguredError
from mykhaya.billing.pricing import fetch_price_amount
from mykhaya.models import BillingInterval, HomeSubscription, SubscriptionPlan, SubscriptionStatus


class SubscriptionChangeError(RuntimeError):
    """A safe, customer-correctable or stale-state transition rejection."""


class SubscriptionOwnershipError(SubscriptionChangeError):
    pass


class InvalidSubscriptionTransition(SubscriptionChangeError):
    pass


def price_id_for(
    config: StripeConfig, plan: SubscriptionPlan, interval: BillingInterval | None
) -> str | None:
    if plan == SubscriptionPlan.free:
        return None
    if interval is None:
        raise InvalidSubscriptionTransition("A paid plan requires a billing interval.")
    if plan == SubscriptionPlan.family:
        return (
            config.family_monthly_price_id
            if interval == BillingInterval.month
            else config.family_annual_price_id
        )
    return (
        config.ultimate_monthly_price_id
        if interval == BillingInterval.month
        else config.ultimate_annual_price_id
    )


def validate_transition(
    current: SubscriptionPlan,
    target: SubscriptionPlan,
    current_interval: BillingInterval | None = None,
    target_interval: BillingInterval | None = None,
    current_status: SubscriptionStatus | None = None,
) -> None:
    if (
        current == target
        and current_status == SubscriptionStatus.cancel_at_period_end
        and current != SubscriptionPlan.free
        and current_interval == target_interval
    ):
        return
    if (
        current == target
        and current != SubscriptionPlan.free
        and current_interval != target_interval
    ):
        return
    if current == target:
        raise InvalidSubscriptionTransition("The Home is already on this plan.")
    allowed = {
        SubscriptionPlan.free: {SubscriptionPlan.family, SubscriptionPlan.ultimate},
        SubscriptionPlan.family: {SubscriptionPlan.free, SubscriptionPlan.ultimate},
        SubscriptionPlan.ultimate: {SubscriptionPlan.family, SubscriptionPlan.free},
    }
    if target not in allowed[current]:
        raise InvalidSubscriptionTransition("This plan change is not supported.")


def _id(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and value.get("id"):
        return str(value["id"])
    return None


def _items(subscription: dict[str, Any]) -> list[dict[str, Any]]:
    return (subscription.get("items") or {}).get("data") or []


def payment_action_url(subscription: dict[str, Any]) -> str | None:
    invoice = subscription.get("latest_invoice")
    if not isinstance(invoice, dict):
        return None
    hosted = invoice.get("hosted_invoice_url")
    if isinstance(hosted, str):
        return hosted
    intent = invoice.get("payment_intent")
    if isinstance(intent, dict):
        redirect = (intent.get("next_action") or {}).get("redirect_to_url") or {}
        url = redirect.get("url")
        if isinstance(url, str):
            return url
    return None


async def retrieve_owned_subscription(
    config: StripeConfig, home: HomeSubscription
) -> dict[str, Any]:
    if not home.external_subscription_id or not home.external_customer_id:
        raise InvalidSubscriptionTransition("This Home has no active Stripe subscription.")
    subscription_id = home.external_subscription_id
    customer_id = home.external_customer_id
    assert config.secret_key  # caller validates configuration
    subscription = await call_stripe(
        lambda: stripe.Subscription.retrieve(
            subscription_id,
            expand=["items.data.price", "latest_invoice.payment_intent"],
            api_key=config.secret_key,
        )
    )
    if _id(subscription.get("id")) != subscription_id:
        raise SubscriptionOwnershipError("Stripe returned a different subscription.")
    if _id(subscription.get("customer")) != customer_id:
        raise SubscriptionOwnershipError("The Stripe subscription belongs to a different customer.")
    return subscription


def current_item(subscription: dict[str, Any]) -> dict[str, Any]:
    items = _items(subscription)
    if len(items) != 1 or not _id(items[0].get("price") or {}):
        raise InvalidSubscriptionTransition("This subscription cannot be changed automatically.")
    return items[0]


async def preview_subscription_change(
    config: StripeConfig,
    home: HomeSubscription,
    target_plan: SubscriptionPlan,
    target_interval: BillingInterval | None,
) -> dict[str, Any]:
    if not config.configured or not config.secret_key:
        raise StripeNotConfiguredError("Stripe billing is not configured.")
    validate_transition(
        home.plan,
        target_plan,
        home.billing_interval,
        target_interval,
        home.status,
    )
    target_price_id = price_id_for(config, target_plan, target_interval)
    if target_plan != SubscriptionPlan.free and not target_price_id:
        raise StripeNotConfiguredError("The selected plan is not configured.")
    customer_id = home.external_customer_id
    subscription_id = home.external_subscription_id
    assert customer_id and subscription_id
    subscription = await retrieve_owned_subscription(config, home)
    item = current_item(subscription)
    item_id = _id(item)
    assert item_id
    if target_plan == SubscriptionPlan.free:
        invoice: dict[str, Any] = {"amount_due": 0, "currency": None, "total": 0}
    else:
        assert target_price_id
        ranks = {
            SubscriptionPlan.free: 0,
            SubscriptionPlan.family: 1,
            SubscriptionPlan.ultimate: 2,
        }
        is_scheduled_downgrade = ranks[target_plan] < ranks[home.plan]
        if is_scheduled_downgrade and home.status != SubscriptionStatus.cancel_at_period_end:
            invoice = {"amount_due": 0, "currency": None, "total": 0}
        else:
            assert config.secret_key
            invoice = await call_stripe(
                lambda: stripe.Invoice.create_preview(
                    customer=customer_id,
                    subscription=subscription_id,
                    subscription_details={
                        "items": [{"id": item_id, "price": target_price_id, "quantity": 1}],
                        "proration_behavior": "always_invoice",
                    },
                    api_key=config.secret_key,
                )
            )
    target_price = (
        await fetch_price_amount(config.secret_key, target_price_id) if target_price_id else None
    )
    period_end = subscription.get("current_period_end")
    return {
        "current_plan": home.plan,
        "target_plan": target_plan,
        "current_interval": home.billing_interval,
        "target_interval": target_interval,
        "amount_due": int(invoice.get("amount_due") or 0),
        "currency": invoice.get("currency") or (target_price.currency if target_price else None),
        "next_amount": target_price.unit_amount if target_price else 0,
        "next_amount_formatted": target_price.formatted_amount if target_price else None,
        "effective_at": datetime.fromtimestamp(period_end, tz=UTC) if period_end else None,
        "period_end": datetime.fromtimestamp(period_end, tz=UTC) if period_end else None,
        "requires_payment": target_plan != SubscriptionPlan.free
        and int(invoice.get("amount_due") or 0) > 0,
    }


async def apply_subscription_change(
    db: AsyncSession,
    config: StripeConfig,
    home: HomeSubscription,
    target_plan: SubscriptionPlan,
    target_interval: BillingInterval | None,
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    if not config.configured or not config.secret_key:
        raise StripeNotConfiguredError("Stripe billing is not configured.")
    validate_transition(
        home.plan,
        target_plan,
        home.billing_interval,
        target_interval,
        home.status,
    )
    target_price_id = price_id_for(config, target_plan, target_interval)
    if target_plan != SubscriptionPlan.free and not target_price_id:
        raise StripeNotConfiguredError("The selected plan is not configured.")
    subscription_id = home.external_subscription_id
    assert subscription_id
    subscription = await retrieve_owned_subscription(config, home)
    item = current_item(subscription)
    item_id = _id(item)
    assert item_id
    period_end = subscription.get("current_period_end")
    start = subscription.get("current_period_start")
    if not period_end or not start:
        raise InvalidSubscriptionTransition("Stripe did not return a billing period end.")
    assert config.secret_key

    plan_rank = {
        SubscriptionPlan.free: 0,
        SubscriptionPlan.family: 1,
        SubscriptionPlan.ultimate: 2,
    }
    is_upgrade = plan_rank[target_plan] > plan_rank[home.plan]
    is_interval_change = target_plan == home.plan and target_interval != home.billing_interval
    is_immediate = is_upgrade or is_interval_change or (
        target_plan != SubscriptionPlan.free
        and home.status == SubscriptionStatus.cancel_at_period_end
    )

    existing_schedule_id = _id(subscription.get("schedule")) or home.stripe_schedule_id
    if existing_schedule_id:
        schedule_id = existing_schedule_id
        schedule = await call_stripe(
            lambda: stripe.SubscriptionSchedule.retrieve(
                schedule_id,
                api_key=config.secret_key,
            )
        )
        if schedule.get("status") != "active":
            existing_schedule_id = None
        elif is_immediate or target_plan == SubscriptionPlan.free:
            # An immediate change cannot safely coexist with a pending phase.
            # Releasing it preserves the current subscription and lets the
            # new, server-owned request become the sole authority.
            await call_stripe(
                lambda: stripe.SubscriptionSchedule.release(
                    schedule_id,
                    preserve_cancel_date=False,
                    api_key=config.secret_key,
                )
            )
            home.stripe_schedule_id = None

    # Any paid upgrade, including a cancellation reversal, changes the same
    # Stripe subscription immediately. `pending_if_incomplete` preserves the
    # existing paid state when payment authentication or payment itself fails.
    if is_immediate:
        assert target_price_id
        updated = await call_stripe(
            lambda: stripe.Subscription.modify(
                subscription_id,
                items=[{"id": item_id, "price": target_price_id, "quantity": 1}],
                cancel_at_period_end=False,
                proration_behavior="always_invoice",
                payment_behavior="pending_if_incomplete",
                api_key=config.secret_key,
                idempotency_key=idempotency_key,
            )
        )
        pending = updated.get("pending_update")
        home.pending_plan = target_plan if pending else None
        home.pending_billing_interval = target_interval if pending else None
        home.pending_effective_at = datetime.fromtimestamp(period_end, tz=UTC) if pending else None
        home.stripe_schedule_id = None
        await db.flush()
        return {
            "kind": "immediate",
            "pending_payment": bool(pending),
            "payment_action_url": payment_action_url(updated),
            "subscription": updated,
        }

    # Free is represented by ending the existing Stripe subscription at the
    # paid period boundary. Paid access remains effective until the webhook
    # reports the terminal cancellation.
    if target_plan == SubscriptionPlan.free:
        updated = await call_stripe(
            lambda: stripe.Subscription.modify(
                subscription_id,
                cancel_at_period_end=True,
                api_key=config.secret_key,
                idempotency_key=idempotency_key,
            )
        )
        home.pending_plan = SubscriptionPlan.free
        home.pending_billing_interval = None
        home.pending_effective_at = datetime.fromtimestamp(period_end, tz=UTC)
        home.stripe_schedule_id = None
        await db.flush()
        return {
            "kind": "scheduled",
            "pending_payment": False,
            "payment_action_url": None,
            "subscription": updated,
        }

    # A paid downgrade uses one Stripe Subscription Schedule with the current
    # phase ending at the already-paid boundary and a future target phase.
    assert target_price_id
    current_price_id = _id(item.get("price") or {})
    assert current_price_id
    created_schedule_id: str | None = None
    if existing_schedule_id:
        schedule_id = existing_schedule_id
    else:
        schedule = await call_stripe(
            lambda: stripe.SubscriptionSchedule.create(
                from_subscription=subscription_id,
                api_key=config.secret_key,
                idempotency_key=idempotency_key,
            )
        )
        created_id = _id(schedule)
        assert created_id
        schedule_id = created_id
        created_schedule_id = created_id
    phases = [
        {
            "items": [{"price": current_price_id, "quantity": 1}],
            "start_date": start,
            "end_date": period_end,
        },
        {"items": [{"price": target_price_id, "quantity": 1}], "start_date": period_end},
    ]
    try:
        updated_schedule = await call_stripe(
            lambda: stripe.SubscriptionSchedule.modify(
                schedule_id,
                phases=phases,  # type: ignore[arg-type]
                end_behavior="release",
                api_key=config.secret_key,
            )
        )
    except (StripeUnavailableError, StripeRequestError):
        if created_schedule_id:
            try:
                await call_stripe(
                    lambda: stripe.SubscriptionSchedule.release(
                        created_schedule_id,
                        preserve_cancel_date=False,
                        api_key=config.secret_key,
                    )
                )
            except (StripeUnavailableError, StripeRequestError):
                # The original failure remains the customer-facing result;
                # Stripe reconciliation can surface any provider-side residue.
                pass
        raise
    home.pending_plan = target_plan
    home.pending_billing_interval = target_interval
    home.pending_effective_at = datetime.fromtimestamp(period_end, tz=UTC)
    home.stripe_schedule_id = _id(updated_schedule)
    await db.flush()
    return {
        "kind": "scheduled",
        "pending_payment": False,
        "payment_action_url": None,
        "subscription": subscription,
    }


async def lock_home_for_change(db: AsyncSession, group_id: uuid.UUID) -> None:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"billing-change:{group_id}"},
    )
