"use client";

// The public homepage's pricing section — the pre-login half of MyKhaya's
// commercial journey. Reuses the same public, unauthenticated endpoints
// (`GET /billing/pricing`) already exposed for the signup plan step and the
// authenticated Settings -> Plan & Billing page — no second amount
// calculation, no hard-coded £ anywhere. See
// docs/architecture/commercial-entitlements.md#phase-5.
//
// MyKhaya offers three plans: Free, Family and Ultimate. Family remains the
// recommended household plan, while Ultimate adds Budget, Driveway and future
// premium modules.
//
// Family and Ultimate each own an independent billing-cycle selector. There is
// deliberately no shared "billing interval" state: changing one card must never
// move the other.

import { useEffect, useId, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Check,
  House,
  Crown,
  Lock,
  ShieldCheck,
  Star,
  Users,
} from "lucide-react";
import type { FamilyPricing } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { intervalSuffix } from "../billing-logic";
import {
  canStartFamilyCheckout,
  canStartUltimateCheckout,
  pricingOptionFor,
  savingLabelFor,
  ultimatePricingOptionFor,
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
  "1 calendar tag",
  "Up to 3 personal routines",
  "1 person",
];

// Every point here must correspond to a real, released capability — see
// docs/architecture/commercial-entitlements.md#plan-definitions. "Chores"
// and "Family Plans" were removed: neither has any implementation anywhere
// in the codebase (family_plans.enabled is "contract only" data; chores has
// no module, router or entitlement key at all), so advertising them as a
// reason to pay for Family was inaccurate.
const FAMILY_POINTS = [
  "Everything in Free",
  "Whole household",
  "Unlimited calendar tags",
  "Unlimited routines",
  "Household routines",
  "Shared family events",
  "Lists",
  "Gift wishlists",
  "Invite household members",
  "Invite external family/friends",
];

const ULTIMATE_POINTS = [
  "Everything in Family",
  "Budget",
  "Driveway",
  "Future premium modules",
];

const REASSURANCES = [
  {
    tone: "green",
    Icon: House,
    title: "No hidden fees",
    text: "Simple, transparent pricing.",
  },
  {
    tone: "peach",
    Icon: ShieldCheck,
    title: "Cancel anytime",
    text: "You’re always in control.",
  },
  {
    tone: "lavender",
    Icon: Users,
    title: "Built for families",
    text: "Share, organise and do more together.",
  },
  {
    tone: "green",
    Icon: Lock,
    title: "Your data, your home",
    text: "Private, secure and in your control.",
  },
] as const;

function FeatureList({ points }: { points: string[] }) {
  return (
    <ul className="mk-plan-list">
      {points.map((point) => (
        <li key={point}>
          <Check aria-hidden="true" className="mk-plan-tick" strokeWidth={2.5} />
          {point}
        </li>
      ))}
    </ul>
  );
}

// Monthly / Annual segmented control. Each card renders its own, bound to its
// own state — never a shared one.
function BillingToggle({
  label,
  value,
  onChange,
}: {
  label: string;
  value: BillingIntervalChoice;
  onChange: (next: BillingIntervalChoice) => void;
}) {
  return (
    <div className="mk-plan-toggle" role="group" aria-label={label}>
      <button
        type="button"
        className={value === "month" ? "toggle-active" : "toggle-idle"}
        aria-pressed={value === "month"}
        onClick={() => onChange("month")}
      >
        Monthly
      </button>
      <button
        type="button"
        className={value === "year" ? "toggle-active" : "toggle-idle"}
        aria-pressed={value === "year"}
        onClick={() => onChange("year")}
      >
        Annual
      </button>
    </div>
  );
}

function PlanPrice({
  amount,
  interval,
}: {
  amount: string;
  interval: BillingIntervalChoice;
}) {
  return (
    <p className="mk-plan-price">
      <strong>{amount}</strong>
      <span aria-hidden="true"> / {intervalSuffix(interval)}</span>
      <span className="sr-only"> per {interval === "month" ? "month" : "year"}</span>
    </p>
  );
}

function BillingHint({
  interval,
  saving,
}: {
  interval: BillingIntervalChoice;
  saving: string | null;
}) {
  return (
    <p className="mk-plan-hint">
      {interval === "month" ? "Billed monthly" : "Billed annually"} until
      cancelled.
      {saving ? (
        <>
          <br />
          {saving}.
        </>
      ) : null}
    </p>
  );
}

export function PublicPricing() {
  const router = useRouter();
  const ids = useId();
  const [pricing, setPricing] = useState<FamilyPricing | null>(null);
  const [pricingError, setPricingError] = useState(false);
  // Two separate pieces of state on purpose: Family and Ultimate never share a
  // billing cycle. Annual is the default, as in the approved design.
  const [familyInterval, setFamilyInterval] =
    useState<BillingIntervalChoice>("year");
  const [ultimateInterval, setUltimateInterval] =
    useState<BillingIntervalChoice>("year");
  const [busy, setBusy] = useState<"free" | "family" | "ultimate" | null>(null);

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

  const selected = pricing ? pricingOptionFor(pricing, familyInterval) : null;
  const saving = pricing ? savingLabelFor(pricing, familyInterval) : null;
  const ultimate = pricing
    ? ultimatePricingOptionFor(pricing, ultimateInterval)
    : null;
  const ultimateSaving =
    pricing?.ultimate_annual_saving_formatted && ultimateInterval === "year"
      ? `Save ${pricing.ultimate_annual_saving_formatted} per year`
      : null;

  return (
    <section
      id="pricing"
      className="mk-section mk-pricing"
      aria-labelledby="pricing-heading"
    >
      <div className="mk-pricing-heading">
        <h2 id="pricing-heading">Simple plans for modern family life</h2>
        <p>
          Start free and upgrade when you’re ready. All plans include a full set
          of core tools, with more for growing households.
        </p>
      </div>

      <div className="mk-pricing-grid">
        <article
          className="mk-plan mk-plan-free"
          aria-labelledby={`${ids}-free`}
        >
          <div className="mk-plan-top">
            <span className="mk-plan-icon" aria-hidden="true">
              <House />
            </span>
            <div className="mk-plan-header">
              <h3 id={`${ids}-free`}>Free</h3>
              <p className="mk-plan-tagline">For individuals getting organised</p>
            </div>
          </div>
          <p className="mk-plan-price">
            <strong>£0</strong>
            <span> / forever</span>
          </p>
          <FeatureList points={FREE_POINTS} />
          <button
            type="button"
            className="secondary mk-plan-cta"
            disabled={busy !== null}
            onClick={() => choosePlan({ plan: "free", interval: "month" })}
          >
            {busy === "free" ? "One moment…" : "Get started free"}
          </button>
        </article>

        <article
          className="mk-plan mk-plan-family"
          aria-labelledby={`${ids}-family`}
        >
          <span className="mk-plan-badge">
            <Star aria-hidden="true" fill="currentColor" />
            Most popular
          </span>
          <div className="mk-plan-top">
            <span className="mk-plan-icon" aria-hidden="true">
              <Users />
            </span>
            <div className="mk-plan-header">
              <h3 id={`${ids}-family`}>Family</h3>
              <p className="mk-plan-tagline">For the whole household</p>
            </div>
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
            <div className="mk-plan-pricing">
              <PlanPrice
                amount={selected.formatted_amount}
                interval={familyInterval}
              />
              <BillingHint interval={familyInterval} saving={saving} />
            </div>
          )}

          <BillingToggle
            label="Family billing interval"
            value={familyInterval}
            onChange={setFamilyInterval}
          />

          <FeatureList points={FAMILY_POINTS} />

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
                choosePlan({ plan: "family", interval: familyInterval })
              }
            >
              {busy === "family" ? "One moment…" : "Start Family"}
            </button>
          )}
        </article>

        <article
          className="mk-plan mk-plan-ultimate"
          aria-labelledby={`${ids}-ultimate`}
        >
          <div className="mk-plan-top">
            <span className="mk-plan-icon" aria-hidden="true">
              <Crown />
            </span>
            <div className="mk-plan-header">
              <h3 id={`${ids}-ultimate`}>Ultimate</h3>
              <p className="mk-plan-tagline">For the full MyKhaya experience</p>
            </div>
          </div>

          {!pricing || !ultimate ? (
            <p role="status" className="mk-plan-loading">
              {pricingError
                ? "Ultimate pricing is temporarily unavailable."
                : "Loading pricing…"}
            </p>
          ) : (
            <div className="mk-plan-pricing">
              <PlanPrice
                amount={ultimate.formatted_amount}
                interval={ultimateInterval}
              />
              <BillingHint interval={ultimateInterval} saving={ultimateSaving} />
            </div>
          )}

          <BillingToggle
            label="Ultimate billing interval"
            value={ultimateInterval}
            onChange={setUltimateInterval}
          />

          <FeatureList points={ULTIMATE_POINTS} />

          {!pricing || !canStartUltimateCheckout(pricing) ? (
            <p className="notice" role="status">
              New Ultimate sign-ups are temporarily paused.
            </p>
          ) : (
            <button
              type="button"
              className="mk-plan-cta mk-plan-cta-ultimate"
              disabled={busy !== null || !ultimate}
              onClick={() =>
                choosePlan({ plan: "ultimate", interval: ultimateInterval })
              }
            >
              {busy === "ultimate" ? "One moment…" : "Start Ultimate"}
            </button>
          )}
        </article>
      </div>

      <div className="mk-pricing-more">
        <p className="mk-pricing-more-label">More about our plans</p>
        <ul className="mk-pricing-assurances" aria-label="More about our plans">
          {REASSURANCES.map(({ tone, Icon, title, text }) => (
            <li key={title}>
              <span className={`mk-assurance-icon ${tone}`} aria-hidden="true">
                <Icon />
              </span>
              <div>
                <strong>{title}</strong>
                <span>{text}</span>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
