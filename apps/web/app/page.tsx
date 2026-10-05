"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PublicBenefits } from "@/components/marketing/public-benefits";
import { PublicFeatures } from "@/components/marketing/public-features";
import { PublicFinalCta } from "@/components/marketing/public-final-cta";
import { PublicFooter } from "@/components/marketing/public-footer";
import { PublicHeader } from "@/components/marketing/public-header";
import { PublicHero } from "@/components/marketing/public-hero";
import { PublicPricing } from "@/components/marketing/public-pricing";
import { PublicBetaOffer } from "@/components/marketing/public-beta-offer";
import { isNativeShell } from "@/components/native-runtime";
import { useAuth } from "@/components/auth-provider";
import { MaintenanceScreen } from "@/components/maintenance";
import { genericUnlockPromptCopy } from "@/components/native-biometric";
import { api, type PublicSignupState } from "@mykhaya/api-client";

function PublicWelcome({ signupState }: { signupState: PublicSignupState | null }) {
  if (signupState?.signup_mode === "closed") {
    return (
      <main className="mk-page">
        <PublicHeader signupState={signupState} />
        <section className="mk-closed-state" aria-labelledby="signup-closed-heading">
          <p className="eyebrow">MyKhaya</p>
          <h1 id="signup-closed-heading">New sign-ups are currently closed.</h1>
          <p>Existing members can still sign in to their Home.</p>
          <div className="mk-hero-actions">
            {signupState.waitlist_available ? (
              <a className="button" href="/waitlist">Join the waitlist</a>
            ) : null}
            <a className="button secondary" href="/login">Sign in</a>
          </div>
        </section>
        <PublicFooter />
      </main>
    );
  }
  if (signupState?.signup_mode === "beta_only") {
    return (
      <main className="mk-page">
        <PublicHeader signupState={signupState} />
        <PublicHero signupState={signupState} />
        <PublicFeatures />
        <PublicBenefits />
        <PublicBetaOffer signupState={signupState} />
        <PublicFinalCta signupState={signupState} />
        <PublicFooter />
      </main>
    );
  }
  return (
    <main className="mk-page">
      <PublicHeader signupState={signupState} />
      <PublicHero signupState={signupState} />
      <PublicFeatures />
      <PublicBenefits />
      <PublicPricing />
      <PublicFinalCta signupState={signupState} />
      <PublicFooter />
    </main>
  );
}

function NativeRootGate() {
  const router = useRouter();
  const { status, initialSessionLoading, retryInitialSession } = useAuth();

  useEffect(() => {
    console.info("[BIOMETRIC DEBUG]", "root_route_state", { route: "/", status, initialSessionLoading });
  }, [status, initialSessionLoading]);

  useEffect(() => {
    if (status === "ready") router.replace("/home");
  }, [router, status]);

  if (status === "maintenance") return <MaintenanceScreen onRecovered={retryInitialSession} />;
  if (status === "offline") {
    return (
      <main className="app-bootstrap-state" role="alert">
        <h1>MyKhaya is temporarily unavailable</h1>
        <p>Your sign-in is still safe. Check your connection and try again.</p>
        <button onClick={retryInitialSession}>Try again</button>
      </main>
    );
  }
  if (status === "locked") {
    return (
      <main className="app-bootstrap-state" role="alert">
        <h1>Unlock MyKhaya</h1>
        <p>Authenticate with {genericUnlockPromptCopy()} to continue.</p>
        <button onClick={retryInitialSession}>Try again</button>
        <button className="tertiary" onClick={() => router.replace("/login")}>Sign in with password</button>
      </main>
    );
  }
  if (initialSessionLoading || status === "initializing" || status === "ready") {
    return <main className="app-bootstrap-state" role="status">Checking your MyKhaya session…</main>;
  }
  return <PublicWelcome signupState={null} />;
}

export default function Welcome() {
  // isNativeShell() always reads false during SSR (no window/Capacitor
  // there) but can read true on the very first client render inside the
  // native shell — branching on it directly, here, produced a root-level
  // hydration mismatch (React error #418: server rendered <PublicWelcome/>,
  // client attempted to hydrate <NativeRootGate/>), confirmed via Android
  // emulator testing (Android Phase 2). React recovers from this by
  // discarding and re-rendering the whole subtree, which is wasteful at
  // best on every native cold load of "/" and was a contributing factor to
  // an Android WebView renderer crash observed in that testing. Match the
  // SSR-safe pattern used elsewhere (e.g. native-biometric-offer.tsx):
  // render the SSR-identical branch first, flip to the native branch only
  // after mount, once isNativeShell() is safe to read.
  const [native, setNative] = useState(false);
  const [signupState, setSignupState] = useState<PublicSignupState | null>(null);
  useEffect(() => {
    setNative(isNativeShell());
  }, []);
  useEffect(() => {
    if (native) return;
    api.publicSignupState().then(setSignupState).catch(() => setSignupState(null));
  }, [native]);
  return native ? <NativeRootGate /> : <PublicWelcome signupState={signupState} />;
}
