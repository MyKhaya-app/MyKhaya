"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import type { User } from "@mykhaya/shared-types";
import { api, ApiError } from "@mykhaya/api-client";
import { AppHeader } from "./app-header";
import { BottomNav } from "./bottom-nav";
import { isNativeShell } from "./native-runtime";
import { useActiveHome } from "./use-active-home";
import { useUserUpdatedListener } from "./user-events";

const AUTH_DIAGNOSTICS_KEY = "mykhaya.auth-diagnostics";
const AUTH_BOOT_ID =
  typeof window === "undefined"
    ? "server"
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;

function recordAuthDiagnostic(event: string, fields: Record<string, unknown> = {}) {
  if (typeof window === "undefined") return;
  const entry = {
    event,
    bootId: AUTH_BOOT_ID,
    origin: window.location.origin,
    pathname: window.location.pathname,
    standalone:
      window.matchMedia("(display-mode: standalone)").matches ||
      ("standalone" in navigator && Boolean(navigator.standalone)),
    at: new Date().toISOString(),
    ...fields,
  };
  console.info("[AUTH_DIAG]", entry);
  try {
    const stored = window.localStorage.getItem(AUTH_DIAGNOSTICS_KEY);
    const previous: unknown = stored ? JSON.parse(stored) : [];
    const entries: unknown[] = Array.isArray(previous)
      ? (previous as unknown[]).slice(-49)
      : [];
    window.localStorage.setItem(AUTH_DIAGNOSTICS_KEY, JSON.stringify([...entries, entry]));
  } catch {
    // Diagnostics must never affect authentication startup.
  }
}

export function AppShell({
  children,
  hero,
}: {
  children: React.ReactNode;
  /** Optional content that visually continues the header's green field
   *  (e.g. the Home screen's greeting). When present, the header itself
   *  renders flush (square bottom) and this slot carries the rounded
   *  bottom edge and shadow instead, so the two read as one block. */
  hero?: React.ReactNode;
}) {
  const path = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [authState, setAuthState] = useState<"loading" | "ready" | "offline" | "signed_out">("loading");
  const { homes, activeHome, setActiveHomeId, loading, error: homesError } = useActiveHome({ enabled: authState === "ready" });

  const bootstrap = useCallback(async () => {
    recordAuthDiagnostic("APP_BOOT");
    setAuthState("loading");
    try {
      recordAuthDiagnostic("ME_REQUEST_STARTED");
      setUser(await api.me());
      setAuthState("ready");
      recordAuthDiagnostic("ME_RESULT_200");
      recordAuthDiagnostic("AUTHENTICATED");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        recordAuthDiagnostic("ME_RESULT_401");
        try {
          recordAuthDiagnostic("RENEW_STARTED");
          setUser(await api.renew());
          setAuthState("ready");
          recordAuthDiagnostic("RENEW_RESULT_200");
          recordAuthDiagnostic("AUTHENTICATED");
          return;
        } catch (renewalCause) {
          if (renewalCause instanceof ApiError) {
            recordAuthDiagnostic(
              renewalCause.status === 401
                ? "RENEW_RESULT_401"
                : renewalCause.status === 403
                ? "RENEW_RESULT_403"
                : renewalCause.status >= 500
                ? "RENEW_RESULT_5XX"
                : "RENEW_FAILED",
              { status: renewalCause.status },
            );
          } else {
            recordAuthDiagnostic("RENEW_NETWORK_ERROR");
          }
          if (renewalCause instanceof ApiError && renewalCause.status === 401) {
            setAuthState("signed_out");
            recordAuthDiagnostic("LOGIN_REDIRECT");
            // Preserve where the user was trying to go (e.g. a calendar-share
            // accept link's ?token=) so login can return them there instead
            // of silently losing it — see app/login/page.tsx's `next` handling.
            // window.location, not useSearchParams(), specifically so AppShell
            // doesn't need a Suspense boundary just for this one redirect.
            const destination =
              typeof window === "undefined"
                ? ""
                : `${window.location.pathname}${window.location.search}`;
            router.replace(
              destination && destination !== "/login"
                ? `/login?next=${encodeURIComponent(destination)}`
                : "/login",
            );
          } else {
            setAuthState("offline");
          }
          return;
        }
      }
      if (cause instanceof ApiError) {
        recordAuthDiagnostic(
          cause.status >= 500
            ? "ME_RESULT_5XX"
            : cause.status === 403
            ? "ME_RESULT_403"
            : "ME_FAILED",
          { status: cause.status },
        );
      } else {
        recordAuthDiagnostic("ME_NETWORK_ERROR");
      }
      setAuthState("offline");
    }
  }, [router]);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    // A Home-less user has a legitimate reason to be here: a brand-new Free
    // account created solely to accept (or manage) an externally shared
    // calendar (see app/calendar-shares/accept/page.tsx and
    // app/calendar/shared/page.tsx) must be able to reach and use that
    // invitation/list, not get bounced into onboarding first — see docs on
    // external Calendar Sharing, "signup preservation" and "Home-less Free
    // account UX." They may still choose "Create your own Home" from there;
    // it's just never forced.
    if (
      authState === "ready" &&
      !homesError &&
      !loading &&
      !homes.length &&
      path !== "/onboarding" &&
      path !== "/calendar-shares/accept" &&
      path !== "/calendar/shared"
    )
      router.replace("/onboarding");
  }, [authState, homes, homesError, loading, path, router]);

  useUserUpdatedListener(setUser);

  // Marks <html> with the class styles.css uses to switch from ordinary
  // document scrolling (browser/PWA) to the bounded native-app-viewport
  // model (fixed header/bottom-nav, one scrollable content region) — see
  // the "Native shell viewport model" block in styles.css. Scoped to
  // AppShell's own mount lifecycle rather than set globally in layout.tsx:
  // pre-auth pages that render no header/bottom-nav (login, register,
  // onboarding, ...) render no AppShell either, and are left with ordinary
  // scrolling either way, native shell or not. Runs regardless of
  // authState (placed before the early returns below, like every other
  // hook here) since even the loading/offline screens should get the
  // stable native viewport rather than flash between two scroll models.
  useEffect(() => {
    if (!isNativeShell()) return;
    document.documentElement.classList.add("native-shell");
    return () => document.documentElement.classList.remove("native-shell");
  }, []);

  if (authState === "loading") {
    return <main className="app-bootstrap-state" role="status">Checking your MyKhaya session…</main>;
  }
  if (authState === "offline") {
    return (
      <main className="app-bootstrap-state" role="alert">
        <h1>MyKhaya is temporarily unavailable</h1>
        <p>Your sign-in is still safe. Check your connection and try again.</p>
        <button onClick={() => void bootstrap()}>Try again</button>
      </main>
    );
  }
  if (authState === "signed_out") return null;

  return (
    <div className="app-shell">
      <AppHeader
        user={user}
        homes={homes}
        activeHome={activeHome}
        onSwitchHome={setActiveHomeId}
        flush={Boolean(hero)}
      />
      <div className="app-content-scroll-region">
        {hero}
        <main className="app-main">{children}</main>
      </div>
      <BottomNav principalType={user?.principal_type} />
    </div>
  );
}
