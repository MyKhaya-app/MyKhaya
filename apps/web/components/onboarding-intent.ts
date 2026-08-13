// Signup/onboarding "commercial intent" — which plan and billing interval a
// visitor picked on the public pricing section or the direct /signup plan
// step, before an account exists. This is convenience only, never authority:
// worst case it's lost (private browsing, a different device opening an
// email-verification link, an expired window) and the visitor simply lands
// on the normal plan step with Free preselected. See
// docs/architecture/commercial-entitlements.md#phase-5 and
// docs/security/platform-administration-security.md#phase-5 — nothing here
// ever grants Family; only the existing authenticated Checkout endpoint and
// its verified webhook can do that.

export type PlanChoice = "free" | "family";
export type BillingIntervalChoice = "month" | "year";

export interface OnboardingIntent {
  plan: PlanChoice;
  interval: BillingIntervalChoice;
}

const STORAGE_KEY = "mk_onboarding_intent";
const MAX_AGE_MS = 48 * 60 * 60 * 1000;

/** Reads plan/interval query-string values as untrusted hints only —
 * anything outside the two closed enums silently falls back to the safe
 * default (Free / monthly), never rejected loudly or trusted further. */
export function parseIntentFromParams(
  plan: string | null,
  interval: string | null,
): OnboardingIntent {
  return {
    plan: plan === "family" ? "family" : "free",
    interval: interval === "year" ? "year" : "month",
  };
}

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function defaultStorage(): StorageLike | null {
  return typeof window === "undefined" ? null : window.localStorage;
}

export function saveOnboardingIntent(
  intent: OnboardingIntent,
  storage: StorageLike | null = defaultStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify({ ...intent, savedAt: Date.now() }));
  } catch {
    // Storage may be unavailable (private browsing, quota) — losing the
    // hint is safe; it never blocks account/Home creation.
  }
}

export function readOnboardingIntent(
  storage: StorageLike | null = defaultStorage(),
  now: number = Date.now(),
): OnboardingIntent | null {
  if (!storage) return null;
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { plan?: unknown; interval?: unknown; savedAt?: unknown };
    if (typeof parsed.savedAt !== "number" || now - parsed.savedAt > MAX_AGE_MS) return null;
    if (parsed.plan !== "free" && parsed.plan !== "family") return null;
    if (parsed.interval !== "month" && parsed.interval !== "year") return null;
    return { plan: parsed.plan, interval: parsed.interval };
  } catch {
    return null;
  }
}

export function clearOnboardingIntent(storage: StorageLike | null = defaultStorage()): void {
  if (!storage) return;
  try {
    storage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}
