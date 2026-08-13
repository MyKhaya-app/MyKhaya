// Pure display logic for the household /settings/billing surface (Phase 3) —
// kept separate from the page component per this repo's convention for
// unit-testable branching (see platform-mfa-logic.test.ts).

export type CheckoutBanner = "success" | "cancelled" | null;

/** Maps the ?checkout= query param Stripe's success/cancel redirect carries
 * to which banner to show. Never used to grant Family access — see
 * docs/security/platform-administration-security.md#checkout — this is
 * purely a "what does the browser show" decision. */
export function checkoutBannerKind(checkoutParam: string | null): CheckoutBanner {
  if (checkoutParam === "success") return "success";
  if (checkoutParam === "cancelled") return "cancelled";
  return null;
}

export function periodLabel(cancelAtPeriodEnd: boolean): "Access ends" | "Renews" {
  return cancelAtPeriodEnd ? "Access ends" : "Renews";
}

export function intervalSuffix(interval: "month" | "year"): "mo" | "yr" {
  return interval === "month" ? "mo" : "yr";
}
