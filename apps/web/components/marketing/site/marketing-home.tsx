"use client";

import "@/app/marketing-site.css";
import { useEffect, useState } from "react";
import { api } from "@mykhaya/api-client";
import type { SignupStateValue } from "@/components/public-signup";
import { canStartUltimateCheckout } from "@/components/family-pricing-logic";
import { BackToTop } from "./back-to-top";
import { HomeHero, HomeStats } from "./home-hero";
import { HomePricing, type PricingState } from "./home-pricing";
import { HomeCta, HomeDay, HomeFaq, HomePromise, HomeSteps, HomeWho } from "./home-sections";
import { HomeStory } from "./home-story";
import { HomeTour } from "./home-tour";
import { SiteFooter } from "./site-footer";
import { SiteNav } from "./site-nav";

/** The public marketing homepage (mykhaya.app). */
export function MarketingHome({ signupState }: { signupState: SignupStateValue }) {
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
    <div className="mks mks-home">
      <SiteNav signupState={signupState} onHome />
      <main>
        <HomeHero signupState={signupState} />
        <HomeStats />
        <HomeStory />
        <HomeTour />
        <HomeDay />
        <HomeSteps />
        <HomePromise />
        <HomeWho />
        <HomePricing pricingState={pricingState} signupState={signupState} />
        <HomeFaq ultimatePaused={ultimatePaused} />
        <HomeCta signupState={signupState} />
      </main>
      <SiteFooter onHome />
      <BackToTop />
    </div>
  );
}
