// Pure presentation helpers shared by every surface that shows Family
// pricing (public homepage, signup/onboarding plan step, Settings -> Plan &
// Billing) — see docs/architecture/commercial-entitlements.md#phase-5. All
// of these read already-resolved values off FamilyPricing (itself sourced
// from mykhaya.billing.pricing at request time); none of them compute or
// guess a monetary amount, so no hard-coded price ever needs to live here.

import type { BillingInterval, FamilyPricing, PricingOption } from "@mykhaya/shared-types";

export function pricingOptionFor(
  pricing: FamilyPricing,
  interval: BillingInterval,
): PricingOption | null {
  return pricing.options.find((option) => option.interval === interval) ?? null;
}

/** "Best value" only ever applies to annual, and only when the backend has
 * actually computed it as mathematically true for the currently configured
 * Stripe prices — never assumed. */
export function isBestValueInterval(pricing: FamilyPricing, interval: BillingInterval): boolean {
  return interval === "year" && pricing.annual_is_best_value;
}

export function savingLabelFor(pricing: FamilyPricing, interval: BillingInterval): string | null {
  if (interval !== "year" || !pricing.annual_saving_formatted) return null;
  return `Save ${pricing.annual_saving_formatted} per year`;
}

/** Phase 7's billing kill switch (mykhaya.billing.config.StripeConfig's
 * acquisition_enabled). Pricing stays visible either way — this only
 * decides whether the "Choose Family" / "Upgrade to Family" action is
 * offered or replaced with a paused notice. Never hides the price itself. */
export function canStartFamilyCheckout(pricing: FamilyPricing): boolean {
  return pricing.acquisition_enabled;
}
