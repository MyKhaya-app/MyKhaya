"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "./auth-provider";
import { AppHeader } from "./app-header";
import { BottomNav } from "./bottom-nav";
import { DesktopNav } from "./desktop-nav";
import { isNativeShell, isPlatformControlCentre } from "./native-runtime";
import { ActiveHomeProvider, useActiveHome } from "./use-active-home";
import { HomeAccessProvider, useHomeAccess } from "./home-access";
import type { FamilyAccessState } from "./primary-nav-destinations";
import { NativeBiometricOffer } from "./native-biometric-offer";
import { genericUnlockPromptCopy } from "./native-biometric";
import { LegalGate } from "./legal-gate";
import { MaintenanceScreen } from "./maintenance";
import { NotificationPermissionPrompt } from "./notification-permission-prompt";
import { AroundHouseDock } from "./around-house-dock";
import { useNativeKeyboardOpen } from "./use-native-keyboard";
import { NotificationProvider } from "./notification-state";
import { useActivityHeartbeat } from "./use-activity-heartbeat";
import { useProductAnalytics } from "./use-product-analytics";

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
  const { user, status, initialSessionLoading, retryInitialSession, legalStatusError, retryLegalStatus } = useAuth();
  const { homes, activeHome, setActiveHomeId, loading, error: homesError } = useActiveHome();
  const { access } = useHomeAccess();
  // Unresolved plan is its own state, not "no family access": the Family tab
  // holds its place (inert) until the Home's plan is known.
  const familyAccess: FamilyAccessState = access.state === "ready" ? access.value.billing.family_access : access.state === "error" ? false : "pending";
  // Sequences the two one-shot native onboarding overlays so they never
  // compete for the screen: NotificationPermissionPrompt isn't mounted at
  // all until the (established, first-run) biometric offer has settled —
  // shown-and-resolved, or determined it had nothing to show. See
  // NativeBiometricOffer's onSettled doc comment.
  const [biometricSettled, setBiometricSettled] = useState(false);
  const keyboardOpen = useNativeKeyboardOpen();
  useActivityHeartbeat(status === "ready");
  useProductAnalytics(status === "ready", path, activeHome?.id);

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
      path !== "/beta/enrol" &&
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
  if (status === "maintenance") return <MaintenanceScreen onRecovered={retryInitialSession} />;
  if (status === "legal_check_error") {
    return (
      <main className="app-bootstrap-state" role="alert">
        <h1>We could not check your legal documents</h1>
        <p>{legalStatusError ?? "Please try again before continuing to MyKhaya."}</p>
        <button onClick={retryLegalStatus}>Try again</button>
      </main>
    );
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
        <p>Authenticate with {genericUnlockPromptCopy()} to continue.</p>
        <button onClick={retryInitialSession}>Try again</button>
        <button className="tertiary" onClick={() => router.replace("/login")}>Sign in with password</button>
      </main>
    );
  }
  if (status === "legal_action_required") return <LegalGate />;
  if (status === "signed_out") {
    return <main className="app-bootstrap-state" role="status">Taking you to sign in…</main>;
  }

  return (
    <NotificationProvider>
      <div className={`app-shell${isNativeShell() ? " native-shell-app" : ""}${keyboardOpen ? " native-keyboard-open" : ""}`}>
      <AppHeader
        user={user}
        homes={homes}
        activeHome={activeHome}
        onSwitchHome={setActiveHomeId}
        flush={Boolean(hero) || path === "/home" || path === "/settings"}
      />
      {!isNativeShell() && (
        <DesktopNav principalType={user?.principal_type} familyAccess={familyAccess} />
      )}
      <div className="app-content-scroll-region">
        {hero}
        <main className="app-main">
          <NativeBiometricOffer onSettled={() => setBiometricSettled(true)} />
          {biometricSettled && <NotificationPermissionPrompt />}
          {children}
        </main>
      </div>
      {!keyboardOpen && <BottomNav principalType={user?.principal_type} familyAccess={familyAccess} />}
      {!isNativeShell() && <AroundHouseDock />}
      </div>
    </NotificationProvider>
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
  // Browser MFA is a short-lived pre-auth route. It must render without the
  // normal application shell/session while the handoff is completed.
  "/mfa",
  // Public legal pages (Terms/Privacy/Children's Privacy/Cookies) must work
  // for a signed-out visitor — linked from the marketing footer and from
  // signup — without ever triggering session bootstrap/redirect. See
  // app/legal/[slug]/page.tsx and AuthProvider's own identical exclusion.
  "/legal",
  "/founding-beta",
  "/signup-choice",
  "/waitlist",
  // Public support landing page for signed-out visitors (the in-app
  // /help-support stays behind sign-in).
  "/support",
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
      <HomeAccessProvider>
        <AppShell>{children}</AppShell>
      </HomeAccessProvider>
    </ActiveHomeProvider>
  );
}
