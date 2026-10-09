"use client";

import "@/app/brand-fonts.css";
import "@/app/marketing-site.css";
import { BackToTop } from "./back-to-top";
import { HomeCta } from "./home-cta";
import { HomeHero } from "./home-hero";
import { HomePricingAndFaq } from "./home-pricing";
import { HomeDay, HomePromise, HomeSteps, HomeWho } from "./home-sections";
import { HomeStory } from "./home-story";
import { HomeTour } from "./home-tour";
import { SiteFooter } from "./site-footer";
import { HomeNav } from "./site-nav";

/** The public marketing homepage (mykhaya.app). Rendered as one client
 *  component on purpose: as server components the static sections were
 *  serialised a second time into the RSC payload, doubling the HTML and
 *  measurably slowing first paint on mobile (Lighthouse). Signup-mode-aware
 *  parts read SignupStateProvider (see Welcome). */
export function MarketingHome() {
  return (
    <div className="mks mks-home">
      <HomeNav />
      <main>
        <HomeHero />
        <HomeStory />
        <HomeTour />
        <HomeDay />
        <HomeSteps />
        <HomePromise />
        <HomeWho />
        <HomePricingAndFaq />
        <HomeCta />
      </main>
      <SiteFooter onHome />
      <BackToTop />
    </div>
  );
}
