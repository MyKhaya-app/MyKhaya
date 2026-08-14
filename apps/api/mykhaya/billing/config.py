"""Stripe configuration resolution — env-only, unlike SMTP/push (see the
comment on Settings.stripe_secret_key for why). Mirrors the
resolve_smtp_config/resolve_push_config shape (source/configured dataclass)
so callers can distinguish "intentionally disabled" from "fully configured"
the same way the rest of the codebase already does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from mykhaya.config import Settings

StripeSource = Literal["environment", "unconfigured"]


@dataclass(frozen=True)
class StripeConfig:
    source: StripeSource
    configured: bool
    # Phase 7's deliberate go-live gate — separate from `configured`. Stripe
    # being fully set up is necessary but not sufficient to accept a *new*
    # paid signup; this is the one flag routers.billing.checkout_session
    # checks before ever creating a Checkout Session. Existing Stripe-backed
    # Homes, webhooks, renewals, cancellations, the Customer Portal, and
    # reconciliation are never gated by this — only new acquisition is. See
    # docs/architecture/commercial-entitlements.md#billing-acquisition-gate.
    acquisition_enabled: bool = False
    secret_key: str | None = field(default=None, repr=False)
    webhook_secret: str | None = field(default=None, repr=False)
    publishable_key: str | None = None
    family_monthly_price_id: str | None = None
    family_annual_price_id: str | None = None


def resolve_stripe_config(settings: Settings) -> StripeConfig:
    """Settings.validate_stripe_configuration already refuses to start with a
    half-configured MYKHAYA_STRIPE_BILLING_CONFIGURED=true, so "configured"
    here is a simple flag check, not a re-validation."""
    if not settings.stripe_billing_configured:
        return StripeConfig(source="unconfigured", configured=False)
    return StripeConfig(
        source="environment",
        configured=True,
        acquisition_enabled=settings.stripe_billing_acquisition_enabled,
        secret_key=settings.stripe_secret_key.get_secret_value()
        if settings.stripe_secret_key
        else None,
        webhook_secret=settings.stripe_webhook_secret.get_secret_value()
        if settings.stripe_webhook_secret
        else None,
        publishable_key=settings.stripe_publishable_key,
        family_monthly_price_id=settings.stripe_family_monthly_price_id,
        family_annual_price_id=settings.stripe_family_annual_price_id,
    )


class StripeNotConfiguredError(RuntimeError):
    """Raised by any billing operation attempted while Stripe is disabled —
    callers turn this into a 503 "billing is not available" response rather
    than letting an AttributeError on a None secret key leak upward."""
