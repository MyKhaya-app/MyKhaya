"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { SignupStateProvider } from "@/components/marketing/site/signup-state-context";
import { isNativeShell } from "@/components/native-runtime";
import { useAuth } from "@/components/auth-provider";
import { MaintenanceScreen } from "@/components/maintenance";
import { LegalGate } from "@/components/legal-gate";
import { genericUnlockPromptCopy } from "@/components/native-biometric";
import { api, type PublicSignupState } from "@mykhaya/api-client";

function NativeRootGate({ fallback }: { fallback: React.ReactNode }) {
  const router = useRouter();
  const { status, initialSessionLoading, retryInitialSession, legalStatusError, retryLegalStatus } = useAuth();
  const [signupState, setSignupState] = useState<PublicSignupState | null | undefined>(undefined);

  useEffect(() => {
    console.info("[BIOMETRIC DEBUG]", "root_route_state", { route: "/", status, initialSessionLoading });
  }, [status, initialSessionLoading]);

  useEffect(() => {
    if (status === "ready") router.replace("/home");
  }, [router, status]);

  useEffect(() => {
    if (status !== "signed_out") return;
    let cancelled = false;
    void api.publicSignupState().then((state) => {
      if (!cancelled) setSignupState(state);
    }).catch(() => {
      if (!cancelled) setSignupState(null);
    });
    return () => {
      cancelled = true;
    };
  }, [status]);

  useEffect(() => {
    if (status !== "signed_out" || signupState === undefined) return;
    const destination = signupState && (
      signupState.signup_mode === "beta_only" ||
      signupState.beta_joining_available ||
      signupState.waitlist_available
    ) && (signupState.registration_open || signupState.waitlist_available)
      ? "/founding-beta"
      : signupState && !signupState.registration_open
        ? "/register"
        : "/login";
    if (process.env.NODE_ENV !== "production") {
      console.info("[NATIVE_ACQUISITION]", {
        event: "signup_state_decision",
        native: true,
        auth_state: status,
        signup_mode: signupState?.signup_mode ?? null,
        beta_joining_available: signupState?.beta_joining_available ?? null,
        waitlist_available: signupState?.waitlist_available ?? null,
        registration_open: signupState?.registration_open ?? null,
        destination,
      });
    }
    router.replace(destination);
  }, [router, signupState, status]);

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
  if (status === "legal_check_error") {
    return (
      <main className="app-bootstrap-state" role="alert">
        <h1>We could not check your legal documents</h1>
        <p>{legalStatusError ?? "Please try again before continuing to MyKhaya."}</p>
        <button onClick={retryLegalStatus}>Try again</button>
      </main>
    );
  }
  if (status === "legal_action_required") return <LegalGate />;
  if (status === "signed_out") {
    return <main className="app-bootstrap-state" role="status">Taking you to sign in…</main>;
  }
  if (initialSessionLoading || status === "initializing" || status === "ready") {
    return <main className="app-bootstrap-state" role="status">Checking your MyKhaya session…</main>;
  }
  return <>{fallback}</>;
}

/** The root route. In a browser it is the marketing homepage (`children`,
 *  server-rendered by app/page.tsx); inside the native shell it is an auth
 *  gate that forwards to /home, the server-selected acquisition path, or
 *  normal sign-in. */
export default function Welcome({ children }: { children: React.ReactNode }) {
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
  // The signup mode is never fetched inside the native shell, whose root is
  // an auth gate.
  return native ? (
    <NativeRootGate fallback={children} />
  ) : (
    <SignupStateProvider enabled={!native}>{children}</SignupStateProvider>
  );
}
