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
from mykhaya.billing.diagnostics import record_billing_diagnostic
from mykhaya.billing.state import (
    SubscriptionOwnershipMismatchError,
    SubscriptionStateOutcome,
    SubscriptionStateResult,
    apply_stripe_subscription_state,
    select_subscription_item,
)
from mykhaya.entitlements import (
    ensure_home_subscription,
    get_home_subscription,
    resolve_effective_plan,
)
from mykhaya.models import HomeSubscription, SubscriptionPlan


class NoStripeSubscriptionError(RuntimeError):
    """This Home has no external_subscription_id to reconcile against."""


class CheckoutConfirmationError(RuntimeError):
    """The supplied Checkout Session is not valid for this Home."""


class CheckoutNotCompleteError(CheckoutConfirmationError):
    """Stripe has not completed the Checkout Session or its subscription yet."""


class ReconciliationValidationError(RuntimeError):
    """Stripe state is not safe to apply to the Home automatically."""


def _stripe_id(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        raw_id = value.get("id")
        return str(raw_id) if raw_id else None
    return None


def _invoice_subscription_id(invoice: dict[str, object]) -> str | None:
    """Return the subscription reference from legacy or Basil invoices.

    Stripe API 2025-03-31.basil moved the subscription reference to
    ``parent.subscription_details.subscription``.  A legacy top-level
    reference remains authoritative when present, but contradictory fields
    are an integrity failure rather than an opportunity to guess.
    """
    legacy_id = _stripe_id(invoice.get("subscription"))
    parent = invoice.get("parent")
    parent_id: str | None = None
    if isinstance(parent, dict) and parent.get("type") == "subscription_details":
        details = parent.get("subscription_details")
        if isinstance(details, dict):
            parent_id = _stripe_id(details.get("subscription"))
    if legacy_id and parent_id and legacy_id != parent_id:
        raise ReconciliationValidationError(
            "Stripe invoice subscription references contradict each other."
        )
    return legacy_id or parent_id


async def _require_paid_latest_invoice(
    latest_invoice: object,
    *,
    secret_key: str,
    expected_customer_id: str,
    expected_subscription_id: str,
) -> dict[str, object]:
    """Resolve and validate the subscription's authoritative latest invoice.

    Stripe may return ``latest_invoice`` as either an ID or an expanded
    Invoice object.  An expanded object that lacks payment fields is treated
    like an ID and re-fetched, because a subscription snapshot is not itself
    proof of payment.  PaymentIntent presence is deliberately not required:
    paid invoices can legitimately have no usable PaymentIntent field.
    """
    invoice: object = latest_invoice
    invoice_id = _stripe_id(invoice)
    if not invoice_id:
        raise ReconciliationValidationError(
            "The Stripe subscription has no resolvable latest invoice."
        )
    required_fields = ("status", "customer")
    if not isinstance(invoice, dict) or any(field not in invoice for field in required_fields):
        invoice = await call_stripe(
            lambda: stripe.Invoice.retrieve(invoice_id, api_key=secret_key)
        )
    if not isinstance(invoice, dict):
        raise ReconciliationValidationError("Stripe returned an invalid latest invoice.")
    if _stripe_id(invoice.get("id")) != invoice_id:
        raise ReconciliationValidationError("Stripe returned a different latest invoice.")
    if invoice.get("status") != "paid":
        raise ReconciliationValidationError(
            "The latest Stripe invoice is not confirmed paid."
        )
    if "paid" in invoice and invoice.get("paid") is not True:
        raise ReconciliationValidationError(
            "The latest Stripe invoice has contradictory payment fields."
        )
    if _stripe_id(invoice.get("customer")) != expected_customer_id:
        raise SubscriptionOwnershipMismatchError(
            "The latest Stripe invoice belongs to a different customer."
        )
    if _invoice_subscription_id(invoice) != expected_subscription_id:
        raise ReconciliationValidationError(
            "The latest Stripe invoice belongs to a different subscription."
        )
    return invoice


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
        await record_billing_diagnostic(
            db,
            source="checkout_confirmation",
            stage="checkout_validation",
            result="pending",
            stripe_mode=config.mode,
            checkout_session_id=session_id,
            group_id=group_id,
            safe_error_code="checkout_not_complete",
            safe_error_message="Stripe Checkout has not completed yet.",
        )
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

    configured_prices = {
        config.family_monthly_price_id,
        config.family_annual_price_id,
        config.ultimate_monthly_price_id,
        config.ultimate_annual_price_id,
    }
    item = select_subscription_item(stripe_subscription, known_price_ids=configured_prices)
    price_id = _stripe_id(item.get("price")) if item else None
    if price_id not in configured_prices:
        raise CheckoutConfirmationError(
            "The Stripe subscription does not use a configured MyKhaya plan price."
        )

    result = await apply_stripe_subscription_state(
        db,
        group_id=group_id,
        stripe_subscription=stripe_subscription,
        actor_administrator_id=None,
        reason=f"Checkout confirmation {session_id}",
        event_type_hint="stripe_checkout_confirmed",
        plan_by_price={
            price_id: plan
            for price_id, plan in (
                (config.family_monthly_price_id, SubscriptionPlan.family),
                (config.family_annual_price_id, SubscriptionPlan.family),
                (config.ultimate_monthly_price_id, SubscriptionPlan.ultimate),
                (config.ultimate_annual_price_id, SubscriptionPlan.ultimate),
            )
            if price_id
        },
    )
    if (
        result.outcome == SubscriptionStateOutcome.INVALID_STATE
        and result.reason == "unrecognised_or_unconfirmed_stripe_status"
    ):
        # A complete Checkout Session can still have an incomplete first
        # payment (for example, a pending 3DS challenge). Preserve the
        # pending response contract and never activate entitlements.
        subscription = result.subscription or await ensure_home_subscription(db, group_id)
        await db.commit()
        return False, subscription
    if result.outcome not in (
        SubscriptionStateOutcome.APPLIED,
        SubscriptionStateOutcome.UNCHANGED,
    ):
        raise CheckoutConfirmationError(
            f"Stripe subscription state could not be applied: {result.reason or result.outcome}"
        )
    subscription = result.subscription or await ensure_home_subscription(db, group_id)
    subscription.external_customer_id = session_customer_id
    subscription.external_subscription_id = session_subscription_id
    await db.commit()
    db.expire_all()
    fresh_subscription = await get_home_subscription(db, group_id)
    if fresh_subscription is None:
        await record_billing_diagnostic(
            db,
            source="checkout_confirmation",
            stage="subscription_persistence",
            result="failed",
            stripe_mode=config.mode,
            checkout_session_id=session_id,
            stripe_customer_id=session_customer_id,
            stripe_subscription_id=session_subscription_id,
            group_id=group_id,
            stripe_subscription_status=stripe_subscription.get("status"),
            safe_error_code="subscription_not_persisted",
            safe_error_message="The reconciled subscription was not found after commit.",
        )
        raise CheckoutConfirmationError("The subscription could not be persisted.")
    await record_billing_diagnostic(
        db,
        source="checkout_confirmation",
        stage="completed",
        result=(
            "mismatch"
            if stripe_subscription.get("status") in {"active", "trialing"}
            and resolve_effective_plan(fresh_subscription).value == "free"
            else "completed"
        ),
        stripe_mode=config.mode,
        checkout_session_id=session_id,
        stripe_customer_id=session_customer_id,
        stripe_subscription_id=session_subscription_id,
        group_id=group_id,
        stripe_subscription_status=stripe_subscription.get("status"),
        safe_error_code=(
            "entitlement_mismatch"
            if stripe_subscription.get("status") in {"active", "trialing"}
            and resolve_effective_plan(fresh_subscription).value == "free"
            else None
        ),
        safe_error_message=(
            "Stripe reports an active subscription but MyKhaya resolves Free."
            if stripe_subscription.get("status") in {"active", "trialing"}
            and resolve_effective_plan(fresh_subscription).value == "free"
            else None
        ),
    )
    return True, fresh_subscription


async def reconcile_home_subscription(
    db: AsyncSession,
    config: StripeConfig,
    group_id: uuid.UUID,
    *,
    actor_administrator_id: uuid.UUID,
) -> SubscriptionStateResult:
    if not config.configured or not config.secret_key:
        raise StripeNotConfiguredError("Stripe billing is not configured.")
    subscription = await get_home_subscription(db, group_id)
    subscription_id = subscription.external_subscription_id if subscription else None
    if not subscription_id:
        raise NoStripeSubscriptionError("This Home has no Stripe subscription to reconcile.")

    stripe_subscription = await call_stripe(
        lambda: stripe.Subscription.retrieve(
            subscription_id,
            expand=["items.data.price", "latest_invoice"],
            api_key=config.secret_key,
        )
    )
    if _stripe_id(stripe_subscription.get("id")) != subscription_id:
        raise SubscriptionOwnershipMismatchError(
            "Stripe returned a different subscription identifier."
        )
    stripe_customer_id = _stripe_id(stripe_subscription.get("customer"))
    if (
        not subscription.external_customer_id
        or stripe_customer_id != subscription.external_customer_id
    ):
        raise SubscriptionOwnershipMismatchError(
            "Stripe returned a subscription for a different customer."
        )
    metadata_group_id = (stripe_subscription.get("metadata") or {}).get("mykhaya_group_id")
    if metadata_group_id and str(metadata_group_id) != str(group_id):
        raise SubscriptionOwnershipMismatchError(
            "Stripe subscription metadata belongs to a different Home."
        )

    if stripe_subscription.get("status") not in {"active", "trialing", "past_due"}:
        raise ReconciliationValidationError(
            "The Stripe subscription is not in an eligible state."
        )
    if stripe_subscription.get("pending_update"):
        raise ReconciliationValidationError(
            "The Stripe subscription has an unresolved pending update."
        )

    plan_by_price = {
        price_id: plan
        for price_id, plan in (
            (config.family_monthly_price_id, SubscriptionPlan.family),
            (config.family_annual_price_id, SubscriptionPlan.family),
            (config.ultimate_monthly_price_id, SubscriptionPlan.ultimate),
            (config.ultimate_annual_price_id, SubscriptionPlan.ultimate),
        )
        if price_id
    }
    item = select_subscription_item(
        stripe_subscription,
        preferred_price_id=None,
        known_price_ids=set(plan_by_price),
    )
    actual_price_id = _stripe_id(item.get("price")) if item else None
    if item is None:
        raise ReconciliationValidationError(
            "The Stripe subscription does not contain one unique configured plan item."
        )
    if actual_price_id not in plan_by_price:
        raise ReconciliationValidationError(
            "The Stripe subscription Price is not configured for a MyKhaya plan."
        )

    latest_invoice = stripe_subscription.get("latest_invoice")
    await _require_paid_latest_invoice(
        latest_invoice,
        secret_key=config.secret_key,
        expected_customer_id=subscription.external_customer_id,
        expected_subscription_id=subscription_id,
    )

    result = await apply_stripe_subscription_state(
        db,
        group_id=group_id,
        stripe_subscription=stripe_subscription,
        actor_administrator_id=actor_administrator_id,
        reason="Manual reconciliation from the Platform Control Centre",
        event_type_hint="stripe_reconciled",
        plan_by_price=plan_by_price,
    )
    if result.outcome not in (
        SubscriptionStateOutcome.APPLIED,
        SubscriptionStateOutcome.UNCHANGED,
    ):
        raise ReconciliationValidationError(
            f"Stripe state was not applied: {result.reason or result.outcome}"
        )
    return result
