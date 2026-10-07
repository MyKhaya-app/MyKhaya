"use client";

// Homepage pricing. Prices come from the same public endpoint every other
// pricing surface uses (`GET /billing/pricing` via api.familyPricing()) — no
// amount is hard-coded here. The Family/Ultimate "paused" notes follow the
// billing kill switches on that response (acquisition_enabled /
// ultimate_acquisition_enabled), never a hard-coded flag. Plan buttons keep
// the previous site's sign-in-aware routing (resolveCtaDestination).

import { useEffect, useState, type MouseEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { FamilyPricing } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import {
  canStartFamilyCheckout,
  canStartUltimateCheckout,
  pricingOptionFor,
  ultimatePricingOptionFor,
} from "@/components/family-pricing-logic";
import { resolveCtaDestination } from "@/components/cta-destination";
import type { BillingIntervalChoice, OnboardingIntent } from "@/components/onboarding-intent";
import type { SignupStateValue } from "@/components/public-signup";
import { HomeFaq } from "./home-sections";
import { SignupLink } from "./signup-link";
import { useSignupStateContext } from "./signup-state-context";

const PLACEHOLDER = "£—";

const FREE_POINTS = ["Calendar", "Events", "Notes", "1 calendar tag", "Up to 3 personal routines", "1 person"];
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
  "Invite external family and friends",
];
const ULTIMATE_POINTS = ["Everything in Family", "Budget", "Driveway", "Future premium modules"];

export type PricingState = { pricing: FamilyPricing | null; error: boolean };

function Points({ points }: { points: string[] }) {
  return (
    <ul>
      {points.map((point) => (
        <li key={point}>{point}</li>
      ))}
    </ul>
  );
}

function Price({ monthly, annual, interval }: { monthly: string; annual: string; interval: BillingIntervalChoice }) {
  return (
    <div className="price">
      <strong className="js-price" data-monthly={monthly} data-annual={annual}>
        {interval === "month" ? monthly : annual}
      </strong>
      <span className="per js-per" aria-hidden="true">
        {interval === "month" ? "/ month" : "/ year"}
      </span>
      <span className="sr-only">{interval === "month" ? " per month" : " per year"}</span>
    </div>
  );
}

export function registerHref(intent: OnboardingIntent) {
  return resolveCtaDestination({ authenticated: false, homesCount: 0 }, intent);
}

export function HomePricing({ pricingState, signupState }: { pricingState: PricingState; signupState: SignupStateValue }) {
  const router = useRouter();
  const [interval, setBilling] = useState<BillingIntervalChoice>("month");
  const [busy, setBusy] = useState(false);
  const { pricing, error } = pricingState;

  if (signupState?.signup_mode === "beta_only") return <BetaOffer signupState={signupState} />;
  // Sign-ups closed: prices stay visible, but every plan action follows the
  // signup mode (waitlist / sign in) instead of starting a registration.
  const closed = signupState?.signup_mode === "closed";

  const family = {
    monthly: pricing ? pricingOptionFor(pricing, "month")?.formatted_amount ?? PLACEHOLDER : PLACEHOLDER,
    annual: pricing ? pricingOptionFor(pricing, "year")?.formatted_amount ?? PLACEHOLDER : PLACEHOLDER,
  };
  const ultimate = {
    monthly: pricing ? ultimatePricingOptionFor(pricing, "month")?.formatted_amount ?? PLACEHOLDER : PLACEHOLDER,
    annual: pricing ? ultimatePricingOptionFor(pricing, "year")?.formatted_amount ?? PLACEHOLDER : PLACEHOLDER,
  };
  const familyPaused = pricing !== null && !canStartFamilyCheckout(pricing);
  const ultimatePaused = pricing !== null && !canStartUltimateCheckout(pricing);

  // Same decision as the previous site: a signed-in visitor goes to the app
  // (billing / onboarding), never back through registration. The link's href
  // is the signed-out destination, so it also works before JS runs.
  async function choose(event: MouseEvent<HTMLAnchorElement>, intent: OnboardingIntent) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      const authenticated = await api.me().then(() => true).catch(() => false);
      const homesCount = authenticated ? (await api.homes().catch(() => [])).length : 0;
      router.push(resolveCtaDestination({ authenticated, homesCount }, intent));
    } finally {
      setBusy(false);
    }
  }

  function planAction(intent: OnboardingIntent, label: string, className: string) {
    if (closed) return <SignupLink className={className} state={signupState} />;
    return (
      <a className={className} href={registerHref(intent)} onClick={(event) => void choose(event, intent)} aria-disabled={busy || undefined}>
        {label}
      </a>
    );
  }

  return (
    <section id="pricing">
      <div className="wrap">
        <div className="section-head center">
          <span className="eyebrow">Pricing</span>
          <h2>Simple plans for modern family life.</h2>
          <p className="lede">
            Start free and upgrade when you&apos;re ready. Every plan includes the core tools, with more for growing
            households.
          </p>
          <div className="billing" role="group" aria-label="Billing period">
            <button type="button" aria-pressed={interval === "month"} onClick={() => setBilling("month")}>
              Monthly
            </button>
            <button type="button" aria-pressed={interval === "year"} onClick={() => setBilling("year")}>
              Annual
            </button>
          </div>
        </div>
        <div className="plans">
          <div className="plan">
            <div>
              <h3>Free</h3>
              <p className="for">For individuals getting organised</p>
            </div>
            <div className="price">
              <strong>£0</strong>
              <span className="per">/ forever</span>
            </div>
            <Points points={FREE_POINTS} />
            {planAction({ plan: "free", interval: "month" }, "Get started free", "btn btn-ghost")}
          </div>

          <div className="plan pop">
            <span className="badge">Most popular</span>
            <div>
              <h3>Family</h3>
              <p className="for">For the whole household</p>
            </div>
            <Price {...family} interval={interval} />
            <Points points={FAMILY_POINTS} />
            {error && <p className="paused" role="status">Pricing is temporarily unavailable. You can still start free and upgrade later.</p>}
            {familyPaused ? (
              <p className="paused" role="status">New Family sign-ups are temporarily paused. You can still create a Free account.</p>
            ) : (
              planAction({ plan: "family", interval }, "Start Family", "btn btn-primary")
            )}
          </div>

          <div className="plan">
            <div>
              <h3>Ultimate</h3>
              <p className="for">For the full MyKhaya experience</p>
            </div>
            <Price {...ultimate} interval={interval} />
            <Points points={ULTIMATE_POINTS} />
            {ultimatePaused && <p className="paused" role="status">New Ultimate sign-ups are temporarily paused.</p>}
            {pricing && !ultimatePaused ? (
              planAction({ plan: "ultimate", interval }, "Start Ultimate", "btn btn-ghost")
            ) : (
              <a className="btn btn-ghost" href="#faq">
                More about our plans
              </a>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

/** Beta-only mode: there is no normal registration to send plan buttons to,
 *  so — as on the previous site — the pricing slot offers the Founding Beta. */
function BetaOffer({ signupState }: { signupState: NonNullable<SignupStateValue> }) {
  return (
    <section id="pricing">
      <div className="wrap">
        <div className="section-head center">
          <span className="eyebrow">Founding Beta</span>
          <h2>Join MyKhaya at no cost during our Founding Beta.</h2>
          <p className="lede">We&apos;re inviting a limited number of households to help us test and improve MyKhaya.</p>
        </div>
        <div className="plans plans-single">
          <div className="plan pop">
            <div>
              <h3>Founding Beta</h3>
              <p className="for">Founding Beta Homes receive</p>
            </div>
            <ul>
              <li>Complimentary Ultimate access for the lifetime of their Home</li>
              <li>All Ultimate features</li>
              <li>No payment or card required</li>
              <li>An opportunity to help shape MyKhaya</li>
            </ul>
            {signupState.joinable_count !== null && signupState.beta_joining_available ? (
              <p className="for" role="status">{signupState.joinable_count} places currently available</p>
            ) : null}
            {signupState.beta_joining_available ? (
              <Link className="btn btn-primary" href="/founding-beta">Join the Beta</Link>
            ) : signupState.waitlist_available ? (
              <Link className="btn btn-primary" href="/waitlist">Join the waitlist</Link>
            ) : (
              <p className="paused" role="status">Founding Beta joining is currently unavailable.</p>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

/** Loads pricing once and renders the pricing section and the FAQ, whose
 *  Ultimate question follows the same acquisition setting. */
export function HomePricingAndFaq() {
  const signupState = useSignupStateContext();
  const [pricingState, setPricingState] = useState<PricingState>({ pricing: null, error: false });
  useEffect(() => {
    let cancelled = false;
    api
      .familyPricing()
      .then((pricing) => {
        if (!cancelled) setPricingState({ pricing, error: false });
      })
      .catch(() => {
        if (!cancelled) setPricingState({ pricing: null, error: true });
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const ultimatePaused = pricingState.pricing !== null && !canStartUltimateCheckout(pricingState.pricing);
  return (
    <>
      <HomePricing pricingState={pricingState} signupState={signupState} />
      <HomeFaq ultimatePaused={ultimatePaused} />
    </>
  );
}
