"use client";

// The public homepage's pricing section — the pre-login half of MyKhaya's
// commercial journey. Reuses the same public, unauthenticated endpoints
// (`GET /billing/pricing`) already exposed for the signup plan step and the
// authenticated Settings -> Plan & Billing page — no second amount
// calculation, no hard-coded £ anywhere. See
// docs/architecture/commercial-entitlements.md#phase-5.
//
// Free and Family are the only two plans MyKhaya has — this is
// deliberately two cards, not three stretched to look "balanced". Family
// is visually promoted (larger, on the brand's own forest green) the same
// way a single recommended plan is promoted on any well-designed pricing
// page; Free sits calmly on the page's normal paper surface next to it.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { FamilyPricing } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { intervalSuffix } from "../billing-logic";
import {
  canStartFamilyCheckout,
  isBestValueInterval,
  pricingOptionFor,
  savingLabelFor,
} from "../family-pricing-logic";
import { resolveCtaDestination } from "../cta-destination";
import type {
  BillingIntervalChoice,
  OnboardingIntent,
} from "../onboarding-intent";

const FREE_POINTS = [
  "Calendar",
  "Events",
  "Notes",
  "1 Calendar Tag",
  "Up to 3 personal routines",
  "1 person",
];

const FAMILY_POINTS = [
  "Everything in Free",
  "Whole household",
  "Unlimited Calendar Tags",
  "Unlimited routines",
  "Household routines",
  "Shared family events",
  "Lists",
  "Chores",
  "Gift wishlists",
  "Family Plans",
  "Invite household members",
  "Invite external family/friends",
];

export function PublicPricing() {
  const router = useRouter();
  const [pricing, setPricing] = useState<FamilyPricing | null>(null);
  const [pricingError, setPricingError] = useState(false);
  const [billingInterval, setBillingInterval] =
    useState<BillingIntervalChoice>("month");
  const [busy, setBusy] = useState<"free" | "family" | null>(null);

  useEffect(() => {
    api
      .familyPricing()
      .then(setPricing)
      .catch(() => setPricingError(true));
  }, []);

  // Plan choice here is intent only — it can only ever pre-fill /register's
  // query string or pick which authenticated page a signed-in visitor lands
  // on. It never sets commercial state itself; only the existing
  // authenticated Checkout endpoint and its verified webhook can do that.
  async function choosePlan(intent: OnboardingIntent) {
    if (busy) return;
    setBusy(intent.plan);
    try {
      const authenticated = await api
        .me()
        .then(() => true)
        .catch(() => false);
      const homesCount = authenticated
        ? (await api.homes().catch(() => [])).length
        : 0;
      router.push(resolveCtaDestination({ authenticated, homesCount }, intent));
    } finally {
      setBusy(null);
    }
  }

  const selected = pricing ? pricingOptionFor(pricing, billingInterval) : null;
  const saving = pricing ? savingLabelFor(pricing, billingInterval) : null;
  const bestValue = pricing
    ? isBestValueInterval(pricing, billingInterval)
    : false;

  return (
    <section
      className="mk-section mk-pricing"
      aria-labelledby="pricing-heading"
    >
      <div className="mk-section-heading">
        <p className="eyebrow">Simple pricing</p>
        <h2 id="pricing-heading">Free, or the complete Family experience</h2>
      </div>

      <div className="mk-pricing-grid">
        <article className="mk-plan mk-plan-free">
          <div className="mk-plan-header">
            <h3>Free</h3>
            <p className="mk-plan-tagline">For individuals getting organised</p>
          </div>
          <p className="mk-plan-price">
            <strong>£0</strong>
          </p>
          <ul className="mk-plan-list">
            {FREE_POINTS.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
          <button
            type="button"
            className="secondary mk-plan-cta"
            disabled={busy !== null}
            onClick={() => choosePlan({ plan: "free", interval: "month" })}
          >
            {busy === "free" ? "One moment…" : "Get started free"}
          </button>
        </article>

        <article className="mk-plan mk-plan-family">
          {bestValue && <span className="mk-plan-badge">Best value</span>}
          <div className="mk-plan-header">
            <h3>Family</h3>
            <p className="mk-plan-tagline">For the whole household</p>
          </div>

          {pricingError ? (
            <p className="notice error" role="alert">
              Family pricing is temporarily unavailable.
              <br />
              You can still create a Free account and upgrade later.
            </p>
          ) : !pricing || !selected ? (
            <p role="status" className="mk-plan-loading">
              Loading pricing…
            </p>
          ) : (
            <>
              <p className="mk-plan-price">
                <strong>{selected.formatted_amount}</strong>
                <span aria-hidden="true">
                  {" "}
                  / {intervalSuffix(billingInterval)}
                </span>
                <span className="sr-only"> per {billingInterval}</span>
              </p>
              <p className="mk-plan-hint">
                {billingInterval === "month"
                  ? "Billed monthly"
                  : "Billed annually"}{" "}
                until cancelled.
                {saving ? ` ${saving}.` : ""}
              </p>
            </>
          )}

          <div
            className="mk-plan-toggle"
            role="group"
            aria-label="Billing interval"
          >
            <button
              type="button"
              className={
                billingInterval === "month" ? "toggle-active" : "secondary"
              }
              aria-pressed={billingInterval === "month"}
              onClick={() => setBillingInterval("month")}
            >
              Monthly
            </button>
            <button
              type="button"
              className={
                billingInterval === "year" ? "toggle-active" : "secondary"
              }
              aria-pressed={billingInterval === "year"}
              onClick={() => setBillingInterval("year")}
            >
              Annual
            </button>
          </div>

          <ul className="mk-plan-list">
            {FAMILY_POINTS.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>

          {pricing && !canStartFamilyCheckout(pricing) ? (
            <p className="notice" role="status">
              New Family sign-ups are temporarily paused. You can still create a
              Free account.
            </p>
          ) : (
            <button
              type="button"
              className="mk-plan-cta mk-plan-cta-family"
              disabled={busy !== null || pricingError || !selected}
              onClick={() =>
                choosePlan({ plan: "family", interval: billingInterval })
              }
            >
              {busy === "family" ? "One moment…" : "Start Family"}
            </button>
          )}
        </article>
      </div>
    </section>
  );
}
