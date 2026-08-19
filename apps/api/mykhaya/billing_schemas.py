from pydantic import BaseModel, Field

from mykhaya.models import (
    BillingInterval,
    SubscriptionPlan,
    SubscriptionProvider,
    SubscriptionStatus,
)
from mykhaya.schemas import CalendarUsageResponse, StrictModel


class PricingOptionResponse(BaseModel):
    """Deliberately omits the Stripe Price ID — the frontend never needs one
    (Checkout only ever sends an interval; see CheckoutSessionRequest), so
    it is not exposed here. See docs/security/platform-administration-security.md."""

    interval: BillingInterval
    provider: str = "stripe"
    currency: str
    unit_amount: int
    formatted_amount: str


class FamilyPricingResponse(BaseModel):
    plan: str
    options: list[PricingOptionResponse]
    annual_saving_formatted: str | None
    # True only when the current provider prices make annual mathematically
    # cheaper than 12 monthly periods — never a hard-coded assumption. See
    # mykhaya.billing.pricing.get_family_pricing.
    annual_is_best_value: bool
    # Phase 7's billing kill switch. Pricing stays informational even when
    # false — only Checkout creation is actually blocked (server-side, in
    # checkout_session) — so the frontend can show real prices with a
    # "temporarily paused" notice instead of hiding them.
    acquisition_enabled: bool


class CheckoutSessionRequest(StrictModel):
    """Deliberately just an interval — never a Price ID, amount, currency,
    Customer, or subscription identifier. See
    docs/security/platform-administration-security.md#checkout."""

    interval: BillingInterval


class CheckoutSessionResponse(BaseModel):
    checkout_url: str


class CheckoutConfirmationRequest(StrictModel):
    session_id: str = Field(min_length=10, max_length=200, pattern=r"^cs_[A-Za-z0-9_]+$")


class CheckoutConfirmationResponse(BaseModel):
    confirmed: bool
    effective_plan: SubscriptionPlan
    subscription_status: SubscriptionStatus


class PortalSessionResponse(BaseModel):
    portal_url: str


class SubscriptionPriceResponse(BaseModel):
    """The actual amount this Home's own subscription is billed — resolved
    live from Stripe against HomeSubscription.external_price_id, which may
    be an older, grandfathered Price than the one currently offered to new
    signups. Never a hard-coded figure."""

    currency: str
    unit_amount: int
    formatted_amount: str


class BillingStatusResponse(BaseModel):
    """The household-facing Plan & Billing read model (Phase 4). Deliberately
    excludes anything Platform-Admin-only or provider-internal: no
    complimentary_note, no HomeSubscriptionEvent history, no webhook event
    IDs, no raw Stripe Customer/Subscription objects, no secrets. See
    docs/security/platform-administration-security.md#household-billing-response."""

    stored_plan: SubscriptionPlan
    provider: SubscriptionProvider
    status: SubscriptionStatus
    effective_plan: SubscriptionPlan
    # Populated only when effective_plan/status diverges from the stored
    # state in a way worth explaining (e.g. "Complimentary access expired").
    effective_status_reason: str | None
    billing_interval: BillingInterval | None
    price: SubscriptionPriceResponse | None
    current_period_end: str | None
    cancel_at_period_end: bool
    complimentary_expires_at: str | None
    can_manage_billing: bool
    has_stripe_customer: bool
    stripe_billing_available: bool
    # How many calendars this Home currently has vs. what its effective plan
    # allows. Populated for every Home (not just over-limit ones) so the
    # page can show "1 of 1" on a normal Free Home too; see "Household Plan
    # & Billing messaging" in docs/architecture/commercial-entitlements.md.
    calendar_usage: CalendarUsageResponse
    # The actual user-facing "event category" resource (CalendarEventLabel,
    # not HomeCalendar) shown on Settings -> Home settings' "Calendars &
    # categories" page — see mykhaya.entitlements.category_usage.
    category_usage: CalendarUsageResponse
    # Same shape/purpose as calendar_usage, for household member count vs.
    # home.max_members — lets People/Home surfaces gate "Add member"/"Invite
    # family" without duplicating the entitlement lookup themselves.
    member_usage: CalendarUsageResponse
    # Whether this Home's plan currently includes household routines —
    # exposed directly (rather than making the frontend infer it from
    # effective_plan) so the Routines UI can disable the Household scope
    # option before submission, not just handle the resulting 403.
    household_routines_enabled: bool
    # Whether this Home's plan currently includes shared/assigned events —
    # lets the Calendar event form lock the "assign to another member"
    # checkboxes before submission rather than only after a 403. See
    # routers.calendar's events.shared.enabled enforcement.
    shared_events_enabled: bool
    # Whether this Home's plan currently includes inviting an Extended
    # Family/Friend (explicit-sharing) member — lets the People page hide
    # those relationship options before submission. See
    # routers.invitations/routers.groups's members.external_invites.enabled
    # enforcement.
    external_invites_enabled: bool


class PlanComparisonRow(BaseModel):
    """One comparable dimension between Free and Family. Only ever populated
    for capabilities backed by a currently-released module — see
    mykhaya.routers.billing.plan_comparison's docstring for why the
    lists/chores/notes/wishlists entitlement keys never appear here despite
    existing in mykhaya.entitlements.PLAN_DEFINITIONS."""

    key: str
    label: str
    free_display: str
    family_display: str


class PlanComparisonResponse(BaseModel):
    rows: list[PlanComparisonRow]
