from pydantic import BaseModel

from mykhaya.models import (
    BillingInterval,
    SubscriptionPlan,
    SubscriptionProvider,
    SubscriptionStatus,
)
from mykhaya.schemas import StrictModel


class PricingOptionResponse(BaseModel):
    interval: BillingInterval
    provider: str = "stripe"
    provider_price_id: str
    currency: str
    unit_amount: int
    formatted_amount: str


class FamilyPricingResponse(BaseModel):
    plan: str
    options: list[PricingOptionResponse]
    annual_saving_formatted: str | None


class CheckoutSessionRequest(StrictModel):
    """Deliberately just an interval — never a Price ID, amount, currency,
    Customer, or subscription identifier. See
    docs/security/platform-administration-security.md#checkout."""

    interval: BillingInterval


class CheckoutSessionResponse(BaseModel):
    checkout_url: str


class PortalSessionResponse(BaseModel):
    portal_url: str


class BillingStatusResponse(BaseModel):
    """The minimal household-facing billing surface for Phase 3 — enough to
    test starting Checkout, opening the Portal, and seeing confirmation
    state. The polished Plan & Billing experience is a later phase."""

    stored_plan: SubscriptionPlan
    provider: SubscriptionProvider
    status: SubscriptionStatus
    effective_plan: SubscriptionPlan
    billing_interval: BillingInterval | None
    current_period_end: str | None
    cancel_at_period_end: bool
    can_manage_billing: bool
    has_stripe_customer: bool
    stripe_billing_available: bool
