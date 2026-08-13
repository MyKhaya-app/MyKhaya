// Pure display logic for the Platform Control Centre Subscriptions area —
// kept separate from the page components so it can be unit-tested directly
// (this repo has no component-rendering test infra; see
// platform-mfa-logic.test.ts for the established pattern). Never
// re-implements entitlement *resolution* — that stays server-side in
// mykhaya.entitlements; this only turns already-resolved values into labels
// and badge classes.

export type SubscriptionPlanValue = "free" | "family";
export type SubscriptionProviderValue = "free" | "complimentary" | "stripe" | "apple" | "google";
export type SubscriptionStatusValue =
  | "active"
  | "trialing"
  | "past_due"
  | "cancel_at_period_end"
  | "cancelled";

const PLAN_LABELS: Record<SubscriptionPlanValue, string> = {
  free: "Free",
  family: "Family",
};

const PROVIDER_LABELS: Record<SubscriptionProviderValue, string> = {
  free: "Free",
  complimentary: "Complimentary",
  stripe: "Stripe",
  apple: "Apple",
  google: "Google",
};

const STATUS_LABELS: Record<SubscriptionStatusValue, string> = {
  active: "Active",
  trialing: "Trialing",
  past_due: "Past due",
  cancel_at_period_end: "Cancels at period end",
  cancelled: "Cancelled",
};

export function planLabel(plan: string): string {
  return PLAN_LABELS[plan as SubscriptionPlanValue] ?? plan;
}

export function providerLabel(provider: string): string {
  return PROVIDER_LABELS[provider as SubscriptionProviderValue] ?? provider;
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status as SubscriptionStatusValue] ?? status;
}

/** "state-healthy" for Family, "state-not-configured" for Free — mirrors the
 * existing state-label badge convention (see platform-mfa-logic.ts). */
export function planBadgeClass(plan: string): string {
  return plan === "family" ? "state-healthy" : "state-not-configured";
}

export function statusBadgeClass(status: string): string {
  if (status === "active" || status === "trialing") return "state-healthy";
  if (status === "past_due" || status === "cancel_at_period_end") return "state-unavailable";
  return "state-unavailable";
}

export function providerBadgeClass(provider: string): string {
  return provider === "complimentary" ? "state-healthy" : "state-not-configured";
}

/** Whether a Home's stored commercial state and its effective state differ —
 * the distinction Phase 2 exists to make visible (e.g. expired complimentary
 * access: stored Family, effective Free). */
export function hasEffectiveDivergence(storedPlan: string, effectivePlan: string): boolean {
  return storedPlan !== effectivePlan;
}

/** A complimentary expiry inside this many days is called out in the UI as
 * "expiring soon" rather than shown as a plain date, so an operator scanning
 * the table notices it before it lapses. Purely a display threshold — the
 * backend's dynamic expiry evaluation is unaffected either way. */
const EXPIRY_SOON_THRESHOLD_DAYS = 7;

export function isExpiringSoon(expiresAt: string | null, now: Date = new Date()): boolean {
  if (!expiresAt) return false;
  const expiry = new Date(expiresAt);
  if (Number.isNaN(expiry.getTime())) return false;
  const daysRemaining = (expiry.getTime() - now.getTime()) / 86_400_000;
  return daysRemaining >= 0 && daysRemaining <= EXPIRY_SOON_THRESHOLD_DAYS;
}

export function isExpired(expiresAt: string | null, now: Date = new Date()): boolean {
  if (!expiresAt) return false;
  const expiry = new Date(expiresAt);
  if (Number.isNaN(expiry.getTime())) return false;
  return expiry.getTime() <= now.getTime();
}

const COMPLIMENTARY_REASON_PRESETS = [
  "Beta tester",
  "Friends & Family",
  "Internal testing",
  "Partner",
  "Promotional",
] as const;

export function complimentaryReasonPresets(): readonly string[] {
  return COMPLIMENTARY_REASON_PRESETS;
}

/** A short, structured label for a HomeSubscriptionEvent's event_type, for
 * the commercial event history timeline. Falls back to the raw type for any
 * value this list doesn't yet know about, rather than hiding the event. */
const EVENT_TYPE_LABELS: Record<string, string> = {
  created: "Home created on Free",
  complimentary_granted: "Complimentary Family access granted",
  downgraded: "Returned to Free",
};

export function eventTypeLabel(eventType: string): string {
  return EVENT_TYPE_LABELS[eventType] ?? eventType.replaceAll("_", " ");
}
