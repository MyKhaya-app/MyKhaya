"use client";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { FamilyPricing } from "@mykhaya/shared-types";
import { api, ApiError } from "@mykhaya/api-client";
import { Logo } from "@/components/logo";
import { FormStatus } from "@/components/form-status";
import { intervalSuffix } from "@/components/billing-logic";
import { isBestValueInterval, pricingOptionFor, savingLabelFor } from "@/components/family-pricing-logic";
import { clearOnboardingIntent, readOnboardingIntent } from "@/components/onboarding-intent";
import type { BillingIntervalChoice } from "@/components/onboarding-intent";

// Home creation always establishes the normal Free/free/active default
// first (see mykhaya.entitlements.ensure_home_subscription, called from
// POST /groups) — the plan step below only ever offers to *upgrade* an
// already-Free Home via the existing authenticated Checkout endpoint. A
// visitor who never reaches this page (an invited member joining an
// existing Home via /invitations/accept) never sees it either — see
// docs/architecture/commercial-entitlements.md#phase-5.
export default function Onboarding() {
  const router = useRouter();
  const [step, setStep] = useState<"home" | "plan">("home");
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [homeId, setHomeId] = useState<string | null>(null);
  const [pricing, setPricing] = useState<FamilyPricing | null>(null);
  const [pricingError, setPricingError] = useState(false);
  const [billingInterval, setBillingInterval] = useState<BillingIntervalChoice>("month");

  useEffect(() => {
    if (step !== "plan") return;
    const intent = readOnboardingIntent();
    if (intent) setBillingInterval(intent.interval);
    api
      .familyPricing()
      .then(setPricing)
      .catch(() => setPricingError(true));
  }, [step]);

  async function submitHome(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const d = new FormData(e.currentTarget);
    try {
      const group = await api.post<{ id: string }>("/groups", { name: d.get("name") });
      setHomeId(group.id);
      setStep("plan");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We couldn’t create your Home.");
    } finally {
      setBusy(false);
    }
  }

  function continueWithFree() {
    clearOnboardingIntent();
    router.push("/home");
  }

  async function upgradeToFamily() {
    if (!homeId || busy) return;
    setBusy(true);
    setError("");
    try {
      const { checkout_url: checkoutUrl } = await api.createCheckoutSession(homeId, billingInterval);
      clearOnboardingIntent();
      window.location.href = checkoutUrl;
    } catch (err) {
      if (err instanceof ApiError && err.status === 503) {
        setError("Billing is not available right now. You can continue on Free and try again later.");
      } else if (err instanceof ApiError && err.status === 409) {
        setError("This Home already has an active subscription.");
      } else {
        setError("We couldn’t start checkout. You can continue on Free and try again later.");
      }
      setBusy(false);
    }
  }

  if (step === "plan") {
    const selected = pricing ? pricingOptionFor(pricing, billingInterval) : null;
    const saving = pricing ? savingLabelFor(pricing, billingInterval) : null;
    const bestValue = pricing ? isBestValueInterval(pricing, billingInterval) : false;
    return (
      <main className="onboarding">
        <Logo />
        <section>
          <p className="step">Your plan</p>
          <h1>How would you like to use MyKhaya?</h1>
          <p className="muted">You can change this at any time from Settings.</p>

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
              <button type="button" disabled={busy} onClick={continueWithFree}>
                Continue with Free
              </button>
            </article>

            <article className="card feature-card">
              <div className="feature-card-heading">
                <h3>Family</h3>
                {bestValue && <span className="release-badge core">Best value</span>}
              </div>
              <p className="muted">The complete MyKhaya experience for your whole household.</p>
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
                  You can still continue on Free and upgrade later.
                </p>
              ) : !selected ? (
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
                </>
              )}
              <FormStatus error={error} />
              <button type="button" disabled={busy || pricingError || !selected} onClick={upgradeToFamily}>
                {busy ? "One moment…" : "Upgrade to Family"}
              </button>
            </article>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="onboarding">
      <Logo />
      <section>
        <p className="step">Your first Home</p>
        <h1>What do you call home?</h1>
        <p className="muted">
          Choose a warm, familiar name. You can change it later.
        </p>
        <form onSubmit={submitHome}>
          <label>
            Home name
            <input
              name="name"
              placeholder="Our Home"
              maxLength={100}
              required
              autoFocus
            />
          </label>
          <FormStatus error={error} />
          <button disabled={busy}>
            {busy ? "Creating Home…" : "Create our Home"}
          </button>
        </form>
      </section>
    </main>
  );
}
