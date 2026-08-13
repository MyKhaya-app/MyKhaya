"use client";

// The public homepage's pricing section (Phase 5) — the pre-login half of
// MyKhaya's commercial journey. Reuses the same public, unauthenticated
// endpoints (`GET /billing/pricing`, `GET /billing/plans`) already exposed
// in Phase 3/4, so the same pricing service feeds this page, the signup
// plan step, and the authenticated Settings -> Plan & Billing page — no
// second amount calculation, no hard-coded £ anywhere. See
// docs/architecture/commercial-entitlements.md#phase-5.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { FamilyPricing, PlanComparison } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { intervalSuffix } from "./billing-logic";
import { isBestValueInterval, pricingOptionFor, savingLabelFor } from "./family-pricing-logic";
import { resolveCtaDestination } from "./cta-destination";
import type { BillingIntervalChoice, OnboardingIntent } from "./onboarding-intent";

export function PublicPricing() {
  const router = useRouter();
  const [pricing, setPricing] = useState<FamilyPricing | null>(null);
  const [pricingError, setPricingError] = useState(false);
  const [comparison, setComparison] = useState<PlanComparison | null>(null);
  const [billingInterval, setBillingInterval] = useState<BillingIntervalChoice>("month");
  const [busy, setBusy] = useState<"free" | "family" | null>(null);

  useEffect(() => {
    api
      .familyPricing()
      .then(setPricing)
      .catch(() => setPricingError(true));
    api
      .planComparison()
      .then(setComparison)
      .catch(() => undefined);
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
      const homesCount = authenticated ? (await api.homes().catch(() => [])).length : 0;
      router.push(resolveCtaDestination({ authenticated, homesCount }, intent));
    } finally {
      setBusy(null);
    }
  }

  const selected = pricing ? pricingOptionFor(pricing, billingInterval) : null;
  const saving = pricing ? savingLabelFor(pricing, billingInterval) : null;
  const bestValue = pricing ? isBestValueInterval(pricing, billingInterval) : false;

  return (
    <section className="pricing-section" aria-labelledby="pricing-heading">
      <div className="pricing-heading">
        <p className="eyebrow">Simple pricing for the whole household</p>
        <h2 id="pricing-heading">Free, or the complete Family experience</h2>
      </div>

      <div className="feature-card-grid pricing-cards">
        <article className="card feature-card">
          <div className="feature-card-heading">
            <h3>Free</h3>
          </div>
          <p className="muted">A simple way to get your Home organised.</p>
          <ul className="plan-points">
            <li>1 calendar</li>
            <li>Core MyKhaya experience</li>
            <li>No payment details required</li>
          </ul>
          <p className="pricing-amount">
            <strong>£0</strong>
          </p>
          <button
            type="button"
            className="secondary"
            disabled={busy !== null}
            onClick={() => choosePlan({ plan: "free", interval: "month" })}
          >
            {busy === "free" ? "One moment…" : "Start Free"}
          </button>
        </article>

        <article className="card feature-card">
          <div className="feature-card-heading">
            <h3>Family</h3>
            {bestValue && <span className="release-badge core">Best value</span>}
          </div>
          <p className="muted">The complete MyKhaya experience for your whole household.</p>
          <ul className="plan-points">
            <li>Monthly or annual billing</li>
            <li>Full Family-plan access</li>
            <li>For everyone in your Home</li>
          </ul>

          <div className="interval-toggle" role="group" aria-label="Billing interval">
            <button
              type="button"
              className={billingInterval === "month" ? "toggle-active" : "secondary"}
              aria-pressed={billingInterval === "month"}
              onClick={() => setBillingInterval("month")}
            >
              Monthly
            </button>
            <button
              type="button"
              className={billingInterval === "year" ? "toggle-active" : "secondary"}
              aria-pressed={billingInterval === "year"}
              onClick={() => setBillingInterval("year")}
            >
              Annual
            </button>
          </div>

          {pricingError ? (
            <p className="notice error" role="alert">
              Family pricing is temporarily unavailable.
              <br />
              You can still create a Free account and upgrade later.
            </p>
          ) : !pricing || !selected ? (
            <p role="status">Loading pricing…</p>
          ) : (
            <>
              <p className="pricing-amount">
                <strong>{selected.formatted_amount}</strong>
                <span aria-hidden="true"> / {intervalSuffix(billingInterval)}</span>
                <span className="sr-only"> per {billingInterval}</span>
              </p>
              <p className="hint">
                Renews {billingInterval === "month" ? "monthly" : "annually"} until cancelled.
                {saving ? ` ${saving}.` : ""}
              </p>
              <p className="hint">One subscription for your whole Home.</p>
            </>
          )}

          <button
            type="button"
            disabled={busy !== null || pricingError || !selected}
            onClick={() => choosePlan({ plan: "family", interval: billingInterval })}
          >
            {busy === "family"
              ? "One moment…"
              : `Choose Family${selected ? ` — ${selected.formatted_amount}/${intervalSuffix(billingInterval)}` : ""}`}
          </button>
        </article>
      </div>

      {comparison && comparison.rows.length > 0 && (
        <div className="card details pricing-comparison">
          <h3>Free vs Family</h3>
          <dl>
            {comparison.rows.map((row) => (
              <div key={row.key}>
                <dt>{row.label}</dt>
                <dd>
                  Free: {row.free_display} · Family: {row.family_display}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </section>
  );
}
