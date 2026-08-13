// Where a public pricing CTA ("Start Free" / "Choose Family") should
// actually send the visitor, once we know whether they're already signed
// in. Kept as one pure decision function so the click handler stays a thin
// wrapper around two already-existing, cheap calls (api.me(), api.homes())
// — see docs/architecture/commercial-entitlements.md#phase-5.
//
// An already-authenticated visitor never gets routed back through
// /register (no duplicate accounts) or straight into a second Checkout (no
// duplicate subscriptions) — Family always lands on the existing
// authenticated Plan & Billing page, which already knows how to show
// Complimentary/active-Stripe state correctly and refuses a second
// Checkout. A signed-in visitor with no Home yet (rare) goes to the normal
// Home-creation step, same as anyone who just registered.

import type { OnboardingIntent } from "./onboarding-intent";

export interface CtaAuthState {
  authenticated: boolean;
  homesCount: number;
}

export function resolveCtaDestination(auth: CtaAuthState, intent: OnboardingIntent): string {
  if (!auth.authenticated) {
    const search = new URLSearchParams({ plan: intent.plan, interval: intent.interval });
    return `/register?${search.toString()}`;
  }
  if (auth.homesCount === 0) return "/onboarding";
  return intent.plan === "family" ? "/settings/billing" : "/home";
}
