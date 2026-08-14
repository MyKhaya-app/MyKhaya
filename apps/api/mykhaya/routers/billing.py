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
from mykhaya.billing.pricing import (
    StripePriceConfigurationError,
    fetch_price_amount,
    format_amount,
    get_family_pricing,
)
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
    PlanComparisonResponse,
    PlanComparisonRow,
    PortalSessionResponse,
    PricingOptionResponse,
    SubscriptionPriceResponse,
)
from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context, membership_for
from mykhaya.entitlements import (
    calendar_usage,
    effective_plan,
    ensure_home_subscription,
    get_home_subscription,
    plan_definition_for,
    resolve_effective_state,
)
from mykhaya.household_permissions import Capability, capabilities_for, require_capability
from mykhaya.models import (
    StripeWebhookFailure,
    SubscriptionPlan,
    SubscriptionProvider,
    SubscriptionStatus,
)
from mykhaya.rate_limit import enforce_rate_limit

router = APIRouter(prefix="/billing", tags=["billing"])
group_router = APIRouter(prefix="/groups/{group_id}/billing", tags=["billing"])
log = structlog.get_logger()


@router.get("/pricing", response_model=FamilyPricingResponse)
async def pricing(
    request: Request, settings: Settings = Depends(get_settings)
) -> FamilyPricingResponse:
    await enforce_rate_limit(request, settings, "billing-pricing", 60, 60)
    # Pricing stays informational even while new acquisition is disabled
    # (the billing kill switch) — a visitor can still see what Family
    # costs; only actually starting Checkout is blocked (see
    # checkout_session below). The frontend uses acquisition_enabled to
    # decide whether to show "Choose Family" or a "temporarily paused"
    # notice, never by treating a pricing-fetch failure as the signal.
    acquisition_enabled = resolve_stripe_config(settings).acquisition_enabled
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
    is_best_value = (
        family_pricing.annual_saving_unit_amount is not None
        and family_pricing.annual_saving_unit_amount > 0
    )
    saving = (
        format_amount(family_pricing.annual_saving_unit_amount, annual.currency)
        if is_best_value and family_pricing.annual_saving_unit_amount is not None
        else None
    )
    return FamilyPricingResponse(
        plan=family_pricing.plan,
        options=[
            PricingOptionResponse(
                interval=option.interval,
                currency=option.currency,
                unit_amount=option.unit_amount,
                formatted_amount=option.formatted_amount,
            )
            for option in (monthly, annual)
        ],
        annual_saving_formatted=saving,
        annual_is_best_value=is_best_value,
        acquisition_enabled=acquisition_enabled,
    )


def _people_display(max_members: int | None) -> str:
    return "1 person" if max_members == 1 else "Whole household"


def _categories_display(max_categories: int | None) -> str:
    return f"{max_categories} category" if max_categories is not None else "Unlimited"


def _personal_routines_display(max_active: int | None) -> str:
    return f"Up to {max_active}" if max_active is not None else "Unlimited"


def _included_display(enabled: bool) -> str:
    return "Included" if enabled else "Not included"


@router.get("/plans", response_model=PlanComparisonResponse)
async def plan_comparison(
    request: Request, settings: Settings = Depends(get_settings)
) -> PlanComparisonResponse:
    """Free vs Family, sourced from mykhaya.entitlements.PLAN_DEFINITIONS —
    never duplicated by hand in the frontend. Deliberately limited to
    dimensions that are both (a) genuinely enforced today and (b) backed by
    a released/reachable module — PLAN_DEFINITIONS carries several other
    keys (lists/chores/wishlists/notes, shared family events, external
    invites, Family Plans, priority support) that are either unreleased
    modules or intentionally-unenforced commercial data pending a focused
    follow-up (see "Deferred enforcement" in
    docs/architecture/commercial-entitlements.md) — surfacing any of those
    here would market something that doesn't actually exist/work yet.
    Preserves Platform Feature Flag -> Commercial Entitlement -> Home/User
    Permission: an entitlement being technically "on" for Family is not
    enough to advertise it."""
    await enforce_rate_limit(request, settings, "billing-plans", 60, 60)
    free = plan_definition_for(SubscriptionPlan.free)
    family = plan_definition_for(SubscriptionPlan.family)
    free_members = free.limits.get("home.max_members")
    family_members = family.limits.get("home.max_members")
    free_categories = free.limits.get("calendar.max_categories")
    family_categories = family.limits.get("calendar.max_categories")
    free_personal_routines = free.limits.get("routines.personal.max_active")
    family_personal_routines = family.limits.get("routines.personal.max_active")
    return PlanComparisonResponse(
        rows=[
            PlanComparisonRow(
                key="home.max_members",
                label="People",
                free_display=_people_display(free_members),
                family_display=_people_display(family_members),
            ),
            PlanComparisonRow(
                key="calendar.max_categories",
                label="Event categories",
                free_display=_categories_display(free_categories),
                family_display=_categories_display(family_categories),
            ),
            PlanComparisonRow(
                key="routines.personal.max_active",
                label="Personal routines",
                free_display=_personal_routines_display(free_personal_routines),
                family_display=_personal_routines_display(family_personal_routines),
            ),
            PlanComparisonRow(
                key="routines.household.enabled",
                label="Household routines",
                free_display=_included_display(
                    free.booleans.get("routines.household.enabled", False)
                ),
                family_display=_included_display(
                    family.booleans.get("routines.household.enabled", False)
                ),
            ),
        ]
    )


@group_router.get("", response_model=BillingStatusResponse)
async def billing_status(
    group_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BillingStatusResponse:
    """The household-facing Plan & Billing read model (Phase 4) — a single
    backend-prepared, display-safe view of the Home's commercial state, so
    the frontend never has to infer Stripe semantics itself. See
    docs/architecture/commercial-entitlements.md#household-plan-billing."""
    membership = await membership_for(group_id, auth, db)
    subscription = await get_home_subscription(db, group_id)
    resolved_plan = await effective_plan(db, group_id)
    resolution = resolve_effective_state(subscription)
    capabilities = await capabilities_for(db, membership)
    config = resolve_stripe_config(settings)

    price: SubscriptionPriceResponse | None = None
    if (
        subscription
        and subscription.provider == SubscriptionProvider.stripe
        and subscription.external_price_id
    ):
        if config.configured and config.secret_key:
            price_option = await fetch_price_amount(
                config.secret_key, subscription.external_price_id
            )
            if price_option is not None:
                price = SubscriptionPriceResponse(
                    currency=price_option.currency,
                    unit_amount=price_option.unit_amount,
                    formatted_amount=price_option.formatted_amount,
                )

    return BillingStatusResponse(
        stored_plan=subscription.plan if subscription else resolved_plan,
        provider=subscription.provider if subscription else SubscriptionProvider.free,
        status=subscription.status if subscription else SubscriptionStatus.active,
        effective_plan=resolved_plan,
        effective_status_reason=resolution.reason,
        billing_interval=subscription.billing_interval if subscription else None,
        price=price,
        current_period_end=subscription.current_period_end.isoformat()
        if subscription and subscription.current_period_end
        else None,
        cancel_at_period_end=bool(
            subscription and subscription.status == SubscriptionStatus.cancel_at_period_end
        ),
        complimentary_expires_at=subscription.complimentary_expires_at.isoformat()
        if subscription and subscription.complimentary_expires_at
        else None,
        can_manage_billing=Capability.billing_manage in capabilities,
        has_stripe_customer=bool(subscription and subscription.external_customer_id),
        # Whether *starting a new Checkout* is actually possible right now —
        # Stripe configured AND new acquisition enabled (Phase 7's kill
        # switch). Deliberately not just "configured": Settings -> Plan &
        # Billing's upgrade section (canShowUpgradeOptions) reads this to
        # decide whether to show Checkout at all, so a disabled kill switch
        # correctly hides it there too, not only at the API layer.
        stripe_billing_available=config.configured and config.acquisition_enabled,
        calendar_usage=await calendar_usage(db, group_id),
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
    if not config.acquisition_enabled:
        # The Phase 7 kill switch — deliberately separate from "configured".
        # Existing Stripe-backed Homes, webhooks, renewals, cancellations,
        # the Portal, and reconciliation are all unaffected by this; only a
        # *new* Checkout Session is refused. See
        # docs/architecture/commercial-entitlements.md#billing-acquisition-gate.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "New Family sign-ups are temporarily unavailable. Please try again later.",
        )

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
    except Exception as exc:
        await db.rollback()
        # Deliberately generic — Stripe retries on a non-2xx, and no detail
        # about *why* processing failed should be observable from the
        # response. Full context goes to the sanitised server log only.
        await log.aerror(
            "stripe_webhook_processing_failed",
            event_id=event.get("id"),
            event_type=event.get("type"),
        )
        # Observability only — never a dedup mechanism (see
        # StripeWebhookFailure's docstring). Recorded *after* the rollback
        # above, in a fresh transaction on the same session, so it survives
        # even though the failed processing attempt itself was discarded.
        db.add(
            StripeWebhookFailure(
                stripe_event_id=event.get("id"),
                event_type=event.get("type"),
                error_message=f"{type(exc).__name__}: {exc}"[:500],
            )
        )
        await db.commit()
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
