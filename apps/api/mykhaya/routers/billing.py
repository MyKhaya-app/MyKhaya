"""Stripe billing: public read-only pricing, per-Home Checkout/Portal
session creation (household-authenticated, billing_manage capability
required), a minimal billing-status surface, and the Stripe webhook
endpoint. See docs/architecture/commercial-entitlements.md#stripe-provider-boundary.

The webhook route is deliberately NOT under mykhaya.routers.platform — it
must be reachable without the admin-subdomain/admin-network restrictions
that gate the Platform Control Centre, since Stripe calls it directly from
Stripe's own infrastructure. Its only trust mechanism is Stripe's
cryptographic signature (see mykhaya.billing.webhooks).
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.billing.checkout import (
    DuplicateSubscriptionError,
    NoStripeCustomerError,
    create_checkout_session,
    create_portal_session,
)
from mykhaya.billing.client import StripeRequestError, StripeUnavailableError
from mykhaya.billing.config import StripeNotConfiguredError, resolve_stripe_config
from mykhaya.billing.pricing import StripePriceConfigurationError, format_amount, get_family_pricing
from mykhaya.billing.webhooks import (
    WebhookSignatureError,
    process_webhook_event,
    verify_and_parse_event,
)
from mykhaya.billing_schemas import (
    BillingStatusResponse,
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    FamilyPricingResponse,
    PortalSessionResponse,
    PricingOptionResponse,
)
from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context, membership_for
from mykhaya.entitlements import effective_plan, ensure_home_subscription, get_home_subscription
from mykhaya.household_permissions import Capability, capabilities_for, require_capability
from mykhaya.models import SubscriptionProvider, SubscriptionStatus
from mykhaya.rate_limit import enforce_rate_limit

router = APIRouter(prefix="/billing", tags=["billing"])
group_router = APIRouter(prefix="/groups/{group_id}/billing", tags=["billing"])
log = structlog.get_logger()


@router.get("/pricing", response_model=FamilyPricingResponse)
async def pricing(
    request: Request, settings: Settings = Depends(get_settings)
) -> FamilyPricingResponse:
    await enforce_rate_limit(request, settings, "billing-pricing", 60, 60)
    try:
        family_pricing = await get_family_pricing(settings)
    except StripeNotConfiguredError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Billing is not available."
        ) from exc
    except StripePriceConfigurationError as exc:
        await log.aerror("stripe_price_configuration_error", detail=str(exc))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Billing is not available."
        ) from exc
    except (StripeUnavailableError, StripeRequestError) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Billing is not available."
        ) from exc

    monthly, annual = family_pricing.options
    saving = None
    if (
        family_pricing.annual_saving_unit_amount is not None
        and family_pricing.annual_saving_unit_amount > 0
    ):
        saving = format_amount(family_pricing.annual_saving_unit_amount, annual.currency)
    return FamilyPricingResponse(
        plan=family_pricing.plan,
        options=[
            PricingOptionResponse(
                interval=option.interval,
                provider_price_id=option.provider_price_id,
                currency=option.currency,
                unit_amount=option.unit_amount,
                formatted_amount=option.formatted_amount,
            )
            for option in (monthly, annual)
        ],
        annual_saving_formatted=saving,
    )


@group_router.get("", response_model=BillingStatusResponse)
async def billing_status(
    group_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BillingStatusResponse:
    """Minimal household-facing billing surface for Phase 3 — enough to
    confirm Checkout/Portal/webhook activation actually worked end to end.
    The polished Plan & Billing page is a later phase."""
    membership = await membership_for(group_id, auth, db)
    subscription = await get_home_subscription(db, group_id)
    resolved_plan = await effective_plan(db, group_id)
    capabilities = await capabilities_for(db, membership)
    return BillingStatusResponse(
        stored_plan=subscription.plan if subscription else resolved_plan,
        provider=subscription.provider if subscription else SubscriptionProvider.free,
        status=subscription.status if subscription else SubscriptionStatus.active,
        effective_plan=resolved_plan,
        billing_interval=subscription.billing_interval if subscription else None,
        current_period_end=subscription.current_period_end.isoformat()
        if subscription and subscription.current_period_end
        else None,
        cancel_at_period_end=bool(
            subscription and subscription.status == SubscriptionStatus.cancel_at_period_end
        ),
        can_manage_billing=Capability.billing_manage in capabilities,
        has_stripe_customer=bool(subscription and subscription.external_customer_id),
        stripe_billing_available=resolve_stripe_config(settings).configured,
    )


@group_router.post("/checkout-session", response_model=CheckoutSessionResponse)
async def checkout_session(
    group_id: uuid.UUID,
    body: CheckoutSessionRequest,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CheckoutSessionResponse:
    await enforce_rate_limit(request, settings, "billing-checkout", 10, 300)
    membership = await require_capability(group_id, Capability.billing_manage, auth, db)
    config = resolve_stripe_config(settings)
    if not config.configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Billing is not available.")

    # Serialises concurrent checkout attempts for the same Home (double-click,
    # multiple tabs, monthly+annual submitted together) — see
    # mykhaya.billing.checkout's module docstring.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"billing:{group_id}"}
    )
    subscription = await ensure_home_subscription(db, group_id)
    await db.commit()

    try:
        checkout_url = await create_checkout_session(
            db,
            settings,
            config,
            membership.group,
            subscription,
            auth.user.id,
            auth.user.email,
            body.interval,
        )
    except DuplicateSubscriptionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except (StripeUnavailableError, StripeRequestError) as exc:
        await log.aerror("stripe_checkout_session_error", group_id=str(group_id), detail=str(exc))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Billing is not available."
        ) from exc
    return CheckoutSessionResponse(checkout_url=checkout_url)


@group_router.post("/portal-session", response_model=PortalSessionResponse)
async def portal_session(
    group_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PortalSessionResponse:
    await enforce_rate_limit(request, settings, "billing-portal", 20, 300)
    await require_capability(group_id, Capability.billing_manage, auth, db)
    config = resolve_stripe_config(settings)
    if not config.configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Billing is not available.")
    subscription = await get_home_subscription(db, group_id)
    if subscription is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This Home has no billing account yet.")
    try:
        portal_url = await create_portal_session(settings, config, subscription)
    except NoStripeCustomerError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except (StripeUnavailableError, StripeRequestError) as exc:
        await log.aerror("stripe_portal_session_error", group_id=str(group_id), detail=str(exc))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Billing is not available."
        ) from exc
    return PortalSessionResponse(portal_url=portal_url)


@router.post("/stripe/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    config = resolve_stripe_config(settings)
    if not config.configured or not config.webhook_secret:
        # Not "not found" (which would confirm/deny the route's existence to
        # a prober) — a clear, static 503 either way, no signature-dependent
        # branching in the response.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Billing is not configured.")

    payload = await request.body()
    signature_header = request.headers.get("stripe-signature", "")
    try:
        event = verify_and_parse_event(payload, signature_header, config.webhook_secret)
    except WebhookSignatureError as exc:
        await log.awarning("stripe_webhook_signature_rejected")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid signature.") from exc

    try:
        outcome = await process_webhook_event(db, event, config)
    except Exception:
        await db.rollback()
        # Deliberately generic — Stripe retries on a non-2xx, and no detail
        # about *why* processing failed should be observable from the
        # response. Full context goes to the sanitised server log only.
        await log.aerror(
            "stripe_webhook_processing_failed",
            event_id=event.get("id"),
            event_type=event.get("type"),
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not process this event."
        ) from None

    await log.ainfo(
        "stripe_webhook_processed",
        event_id=event.get("id"),
        event_type=event.get("type"),
        outcome=outcome,
    )
    return Response(status_code=status.HTTP_200_OK)
