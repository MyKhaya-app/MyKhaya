// Pure display logic for the household Settings -> Plan & Billing page
// (Phase 4, replacing Phase 3's minimal test surface) — kept separate from
// the page component per this repo's convention for unit-testable branching
// (see platform-mfa-logic.test.ts). Never re-implements entitlement
// *resolution* — mykhaya.entitlements remains the only authority for what a
// Home can actually do; this only decides which card/copy to show for an
// already-resolved BillingStatus.

import type { BillingStatus } from "@mykhaya/shared-types";

export type CheckoutBanner = "success" | "cancelled" | null;

export type BillingStatusLoader = () => Promise<BillingStatus | null>;

export async function pollForFamilyBillingStatus(
  load: BillingStatusLoader,
  options: {
    intervalMs?: number;
    timeoutMs?: number;
    sleep?: (milliseconds: number) => Promise<void>;
    now?: () => number;
  } = {},
): Promise<BillingStatus | null> {
  const intervalMs = options.intervalMs ?? 2_000;
  const timeoutMs = options.timeoutMs ?? 30_000;
  const sleep = options.sleep ?? ((milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)));
  const now = options.now ?? (() => Date.now());
  const startedAt = now();
  let result = await load();
  while (result?.effective_plan !== "family" && now() - startedAt < timeoutMs) {
    await sleep(Math.min(intervalMs, timeoutMs - (now() - startedAt)));
    result = await load();
  }
  return result;
}

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

export function intervalName(interval: "month" | "year"): "Monthly" | "Annual" {
  return interval === "month" ? "Monthly" : "Annual";
}

/** Every distinct Plan & Billing card state — one BillingStatus resolves to
 * exactly one of these, so the page renders one coherent card rather than
 * several overlapping conditionals. */
export type PlanCardKind =
  | "free"
  | "free_expired_complimentary"
  | "free_ended_stripe"
  | "complimentary_no_expiry"
  | "complimentary_with_expiry"
  | "stripe_active"
  | "stripe_past_due"
  | "stripe_cancelling";

export function resolvePlanCardKind(status: BillingStatus): PlanCardKind {
  if (status.effective_plan === "free") {
    if (status.stored_plan === "family" && status.provider === "complimentary") {
      return "free_expired_complimentary";
    }
    if (status.stored_plan === "family" && status.provider === "stripe") {
      return "free_ended_stripe";
    }
    return "free";
  }
  // effective_plan === "family" from here on.
  if (status.provider === "complimentary") {
    return status.complimentary_expires_at ? "complimentary_with_expiry" : "complimentary_no_expiry";
  }
  if (status.provider === "stripe") {
    if (status.status === "past_due") return "stripe_past_due";
    if (status.status === "cancel_at_period_end") return "stripe_cancelling";
    return "stripe_active";
  }
  // Fail safe: an unrecognised combination is treated as the plain Free
  // card rather than guessing at a paid/complimentary state.
  return "free";
}

/** Whether the "Manage billing" / "Update payment method" action (opens the
 * Stripe Customer Portal) should ever be offered — Stripe-backed Homes with
 * a Customer on record and an authorised billing manager only. Never shown
 * for Complimentary access, which has no Stripe relationship at all. */
export function canShowPortalAction(
  status: Pick<BillingStatus, "provider" | "has_stripe_customer" | "can_manage_billing">,
): boolean {
  return status.provider === "stripe" && status.has_stripe_customer && status.can_manage_billing;
}

/** Whether Family upgrade options (Checkout) should be offered — only when
 * the Home is actually eligible (effective Free) and the viewer can manage
 * billing. A Home mid-complimentary-access or already Stripe-active is not
 * shown a second "upgrade" path. */
export function canShowUpgradeOptions(
  status: Pick<BillingStatus, "effective_plan" | "can_manage_billing" | "stripe_billing_available">,
): boolean {
  return (
    status.effective_plan === "free" && status.can_manage_billing && status.stripe_billing_available
  );
}

/** Whether the Current Plan card's "All Family features included" strip
 * should show — every PlanCardKind where the Home genuinely has full,
 * working Family access right now. Deliberately excludes stripe_past_due:
 * access is still being *maintained* while payment is fixed, not a settled
 * "you have everything" state, so that card keeps its own attention-getting
 * copy instead. Free/ended states obviously never qualify. */
export function hasFullFamilyAccess(cardKind: PlanCardKind): boolean {
  return (
    cardKind === "complimentary_no_expiry" ||
    cardKind === "complimentary_with_expiry" ||
    cardKind === "stripe_active" ||
    cardKind === "stripe_cancelling"
  );
}
