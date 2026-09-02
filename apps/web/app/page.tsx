"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { PublicBenefits } from "@/components/marketing/public-benefits";
import { PublicFeatures } from "@/components/marketing/public-features";
import { PublicFinalCta } from "@/components/marketing/public-final-cta";
import { PublicFooter } from "@/components/marketing/public-footer";
import { PublicHeader } from "@/components/marketing/public-header";
import { PublicHero } from "@/components/marketing/public-hero";
import { PublicHowItWorks } from "@/components/marketing/public-how-it-works";
import { PublicPricing } from "@/components/marketing/public-pricing";
import { isNativeShell } from "@/components/native-runtime";
import { useAuth } from "@/components/auth-provider";

function PublicWelcome() {
  return (
    <main className="mk-page">
      <PublicHeader />
      <PublicHero />
      <PublicBenefits />
      <PublicFeatures />
      <PublicHowItWorks />
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
        <p>Authenticate with Face ID, Touch ID, or your device passcode to continue.</p>
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
  return isNativeShell() ? <NativeRootGate /> : <PublicWelcome />;
}
