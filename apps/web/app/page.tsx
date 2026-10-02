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
import { isNativeShell } from "@/components/native-runtime";
import { useAuth } from "@/components/auth-provider";
import { genericUnlockPromptCopy } from "@/components/native-biometric";

function PublicWelcome() {
  return (
    <main className="mk-page">
      <PublicHeader />
      <PublicHero />
      <PublicFeatures />
      <PublicBenefits />
      <PublicPricing />
      <PublicFinalCta />
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
  return <PublicWelcome />;
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
  useEffect(() => {
    setNative(isNativeShell());
  }, []);
  return native ? <NativeRootGate /> : <PublicWelcome />;
}
