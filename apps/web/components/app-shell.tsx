"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "./auth-provider";
import { AppHeader } from "./app-header";
import { BottomNav } from "./bottom-nav";
import { isNativeShell, isPlatformControlCentre } from "./native-runtime";
import { ActiveHomeProvider, useActiveHome } from "./use-active-home";
import { NativeBiometricOffer } from "./native-biometric-offer";

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
  const { user, status, initialSessionLoading, retryInitialSession } = useAuth();
  const { homes, activeHome, setActiveHomeId, loading, error: homesError } = useActiveHome();

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
      status === "ready" &&
      !homesError &&
      !loading &&
      !homes.length &&
      path !== "/onboarding" &&
      path !== "/calendar-shares/accept" &&
      path !== "/calendar/shared"
    )
      router.replace("/onboarding");
  }, [status, homes, homesError, loading, path, router]);

  // Marks <html> with the class styles.css uses to switch from ordinary
  // document scrolling (browser/PWA) to the bounded native-app-viewport
  // model (fixed header/bottom-nav, one scrollable content region) — see
  // the "Native shell viewport model" block in styles.css. Scoped to
  // AppShell's own mount lifecycle rather than set globally in layout.tsx:
  // pre-auth pages that render no header/bottom-nav (login, register,
  // onboarding, ...) render no AppShell either, and are left with ordinary
  // scrolling either way, native shell or not. Runs regardless of
  // auth status (placed before the early returns below, like every other
  // hook here) since even the loading/offline screens should get the
  // stable native viewport rather than flash between two scroll models.
  useEffect(() => {
    if (!isNativeShell()) return;
    document.documentElement.classList.add("native-shell");
    return () => document.documentElement.classList.remove("native-shell");
  }, []);

  useEffect(() => {
    console.info("[BIOMETRIC DEBUG]", "app_shell_branch", { path, status, initialSessionLoading });
  }, [path, status, initialSessionLoading]);

  if (initialSessionLoading) {
    return <main className="app-bootstrap-state" role="status">Checking your MyKhaya session…</main>;
  }
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
  if (status === "signed_out") return null;

  return (
    <div className="app-shell">
      <AppHeader
        user={user}
        homes={homes}
        activeHome={activeHome}
        onSwitchHome={setActiveHomeId}
        flush={Boolean(hero) || path === "/home"}
      />
      <div className="app-content-scroll-region">
        {hero}
        <main className="app-main"><NativeBiometricOffer />{children}</main>
      </div>
      <BottomNav principalType={user?.principal_type} />
    </div>
  );
}

/** Compatibility wrapper for pages while the authenticated shell is root-owned. */
export function AppShellContent({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

const PUBLIC_PATH_PREFIXES = [
  "/login",
  "/register",
  "/forgot-password",
  "/reset-password",
  "/verify-email",
  "/onboarding",
];
const EXCLUDED_SHELL_PATH_PREFIXES = [
  "/control-centre",
  "/wishlist/share",
  "/offline",
  "/service-status",
];

function isPublicPath(path: string): boolean {
  return PUBLIC_PATH_PREFIXES.some((prefix) => path === prefix || path.startsWith(`${prefix}/`));
}

function usesPersistentShell(path: string): boolean {
  // The Capacitor live URL starts at `/`, which is the public marketing
  // route. It must not be placed inside the authenticated shell while native
  // bearer restoration is still in progress; the native root gate sends a
  // restored session to `/home`.
  return path !== "/" && !isPublicPath(path) && !EXCLUDED_SHELL_PATH_PREFIXES.some(
    (prefix) => path === prefix || path.startsWith(`${prefix}/`),
  );
}

export function PersistentAppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  useEffect(() => {
    console.info("[BIOMETRIC DEBUG]", "persistent_shell_branch", { path, platformControlCentre: isPlatformControlCentre(), mounted: usesPersistentShell(path) });
  }, [path]);
  return isPlatformControlCentre() || !usesPersistentShell(path) ? (
    <>{children}</>
  ) : (
    <ActiveHomeProvider>
      <AppShell>{children}</AppShell>
    </ActiveHomeProvider>
  );
}
