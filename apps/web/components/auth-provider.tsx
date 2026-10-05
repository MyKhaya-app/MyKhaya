"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { App } from "@capacitor/app";
import type { User } from "@mykhaya/shared-types";
import { api, ApiError, type LegalStatusResponse } from "@mykhaya/api-client";
import { recordAuthDiagnostic } from "./auth-diagnostics";
import { bootstrapNativeSession } from "./native-auth";
import { hasEverBeenBackgrounded, markUnlocked, startAppLockTracking, wasBackgroundedLongEnoughToLock } from "./native-app-lock";
import { initializeNativePush, reconcileNativePush } from "./native-push";
import { isMaintenanceError } from "./maintenance";
import { isNativeShell, isPlatformControlCentre } from "./native-runtime";
import { useUserUpdatedListener } from "./user-events";

// legal_action_required sits between a fully-authenticated session and
// ordinary app access — modelled on the existing "locked" (native biometric
// re-lock/MFA) interrupt AppShell already renders full-screen for, not as a
// second application shell. The backend's GET /legal/status is always the
// source of truth for whether this status applies; nothing here re-derives
// compliance rules client-side. See components/legal-gate.tsx.
type AuthStatus =
  | "initializing"
  | "ready"
  | "offline"
  | "locked"
  | "maintenance"
  | "legal_check_error"
  | "legal_action_required"
  | "signed_out";
type AuthContextValue = {
  user: User | null;
  status: AuthStatus;
  initialSessionLoading: boolean;
  sessionRefreshing: boolean;
  /** The legal status snapshot behind the current `status` — populated
   *  whenever an auth transition resolves it (login, session restore,
   *  renewal), and refreshed on demand via `refreshLegalStatus` (e.g. after
   *  the legal gate records an acceptance). Never null while `status` is
   *  "legal_action_required"; may be null otherwise (not yet checked, or the
   *  check failed and the gate fails open — see `refreshLegalStatus`). */
  legalStatus: LegalStatusResponse | null;
  legalStatusError: string | null;
  /** Re-fetches GET /legal/status and updates `status`/`legalStatus`
   *  accordingly — released back to "ready" only once the backend itself
   *  reports full compliance, never optimistically from client-side state.
   *  Fails open to "ready" on a network error: the legal gate is a
   *  compliance UX nudge on top of a session that is already fully
   *  authenticated, not a second security boundary, so a transient failure
   *  here must never behave like a lost/expired session. */
  refreshLegalStatus: () => Promise<LegalStatusResponse | null>;
  retryLegalStatus: () => void;
  retryInitialSession: () => void;
  refreshSession: () => Promise<boolean>;
  setAuthenticatedUser: (user: User) => Promise<void>;
  /** Sign-out's client-state counterpart to setAuthenticatedUser: clears the
   *  in-memory user/status so no previously-authenticated route can keep
   *  rendering (or be restored via browser Back) after the server session is
   *  gone — AppShell already treats "signed_out" as "render nothing" (see
   *  its own early return), so flipping status here is what makes that
   *  protection apply immediately, not just on the next full page load. */
  clearSession: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function isPublicPath(path: string) {
  // "/legal" (Terms/Privacy/Children's Privacy/Cookies) must never trigger
  // session bootstrap for a signed-out visitor — see app-shell.tsx's
  // identical PUBLIC_PATH_PREFIXES entry.
  return [
    "/login",
    "/register",
    "/forgot-password",
    "/reset-password",
    "/verify-email",
    "/mfa",
    "/legal",
    "/founding-beta",
    "/signup-choice",
    "/waitlist",
  ].some(
    (prefix) => path === prefix || path.startsWith(`${prefix}/`),
  );
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const platformControlCentre = isPlatformControlCentre();
  // Capacitor is unavailable during SSR and may only become observable after
  // the first client render. Keep the root route in a neutral restoring state
  // until that answer is known.
  const [runtimeNative, setRuntimeNative] = useState<boolean | null>(null);
  useEffect(() => {
    setRuntimeNative(isNativeShell());
  }, []);
  // Native shells start at the live frontend origin (`/`) and restore their
  // bearer session asynchronously. Start in restoring state in that case so
  // the first render cannot be mistaken for an anonymous browser session.
  // `/` is the public marketing homepage in a browser, but it is the native
  // shell's startup entry point. Keep those two meanings separate so a
  // browser visit never triggers cookie renewal/redirects while Capacitor
  // still restores its bearer session from the same root URL.
  const nativeStartup = runtimeNative === true && (!isPublicPath(path) || path === "/") && !platformControlCentre;
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<AuthStatus>(path === "/" || nativeStartup ? "initializing" : "signed_out");
  const [initialSessionLoading, setInitialSessionLoading] = useState(path === "/" || nativeStartup);
  const [sessionRefreshing, setSessionRefreshing] = useState(false);
  const [legalStatus, setLegalStatus] = useState<LegalStatusResponse | null>(null);
  const [legalStatusError, setLegalStatusError] = useState<string | null>(null);
  const bootstrapped = useRef(false);

  // The single place that turns "session is authenticated" into either
  // "ready" or "legal_action_required" — every auth-success path below
  // (native restore, cookie `/users/me`, cookie renewal, and a fresh
  // password/MFA sign-in via setAuthenticatedUser) calls this instead of
  // setting "ready" directly, so the legal gate can never be bypassed by a
  // path that forgets to check it.
  const applyLegalStatus = useCallback(async (): Promise<LegalStatusResponse | null> => {
    try {
      const result = await api.legalStatus();
      setLegalStatus(result);
      setLegalStatusError(null);
      setStatus(result.action_required ? "legal_action_required" : "ready");
      return result;
    } catch {
      setLegalStatus(null);
      setLegalStatusError("We could not check the required legal documents.");
      setStatus("legal_check_error");
      return null;
    }
  }, []);

  useEffect(() => {
    console.info("[BIOMETRIC DEBUG]", "auth_state", { route: path, native: nativeStartup, status, initialSessionLoading });
  }, [path, nativeStartup, status, initialSessionLoading]);

  type AuthRedirectReason = "no_session_after_restore" | "session_expired";
  const redirectToLogin = useCallback((reason: AuthRedirectReason) => {
    const destination = typeof window === "undefined" ? "" : `${window.location.pathname}${window.location.search}`;
    if (process.env.NODE_ENV !== "production") {
      console.info("[AUTH_NAV]", {
        event: "auth_redirect_to_login",
        reason,
        pathname: typeof window === "undefined" ? path : window.location.pathname,
        native: isNativeShell(),
        userPresent: Boolean(user),
      });
    }
    router.replace(destination && destination !== "/login" ? `/login?next=${encodeURIComponent(destination)}` : "/login");
  }, [path, router, user]);

  const loadSession = useCallback(async (initial: boolean) => {
    if (initial) setInitialSessionLoading(true);
    else setSessionRefreshing(true);
    recordAuthDiagnostic("APP_BOOT");
    try {
      if (isNativeShell()) {
        recordAuthDiagnostic("NATIVE_BOOTSTRAP_STARTED");
        const restored = await bootstrapNativeSession();
        if (!restored) {
          setUser(null);
          setStatus("signed_out");
          recordAuthDiagnostic("NATIVE_BOOTSTRAP_RESULT_SIGNED_OUT");
          redirectToLogin("no_session_after_restore");
          return false;
        }
        setUser(restored);
        // Phase 4: whether this call originated from cold-launch bootstrap
        // or a Phase-4 resume re-lock, reaching "ready" here means whatever
        // the last background period was has just been fully accounted
        // for — the *next* one must be judged on its own elapsed time, not
        // added on top of this one. See native-app-lock.ts's own doc
        // comment on markUnlocked() for the short-dip-after-unlock bug this
        // prevents.
        markUnlocked();
        await applyLegalStatus();
        recordAuthDiagnostic("NATIVE_BOOTSTRAP_RESULT_AUTHENTICATED");
        return true;
      }
      recordAuthDiagnostic("ME_REQUEST_STARTED");
      setUser(await api.me());
      markUnlocked();
      await applyLegalStatus();
      recordAuthDiagnostic("ME_RESULT_200");
      recordAuthDiagnostic("AUTHENTICATED");
      return true;
    } catch (cause) {
      // PCC maintenance mode: the API answers 503 `maintenance_mode` to every
      // consumer request. That is not a lost session and not a connectivity
      // problem, so it gets its own status (and screen) and never signs the
      // user out.
      if (isMaintenanceError(cause)) {
        setStatus("maintenance");
        return false;
      }
      if (isNativeShell() && cause instanceof Error && cause.name === "NativeBiometricUnlockError") {
        setStatus("locked");
        recordAuthDiagnostic("NATIVE_BIOMETRIC_LOCKED");
        return false;
      }
      if (!isNativeShell() && cause instanceof ApiError && cause.status === 401) {
        try {
          setUser(await api.renew());
          markUnlocked();
          await applyLegalStatus();
          recordAuthDiagnostic("RENEW_RESULT_200");
          return true;
        } catch (renewalCause) {
          if (isMaintenanceError(renewalCause)) {
            setStatus("maintenance");
            return false;
          }
          if (renewalCause instanceof ApiError && renewalCause.status === 401) {
            setUser(null);
            setStatus("signed_out");
            recordAuthDiagnostic("LOGIN_REDIRECT");
            redirectToLogin("session_expired");
            return false;
          }
        }
      }
      if (isNativeShell()) {
        setStatus("offline");
        recordAuthDiagnostic("NATIVE_BOOTSTRAP_ERROR");
      } else {
        setStatus("offline");
        recordAuthDiagnostic("ME_NETWORK_ERROR");
      }
      return false;
    } finally {
      if (initial) setInitialSessionLoading(false);
      else setSessionRefreshing(false);
    }
  }, [redirectToLogin, applyLegalStatus]);

  useEffect(() => {
    if (path === "/" && runtimeNative === null) {
      return;
    }
    if (
      platformControlCentre
      || isPublicPath(path)
      || (runtimeNative === false && path === "/")
    ) {
      setInitialSessionLoading(false);
      if (status !== "ready") setStatus("signed_out");
      return;
    }
    // This guard is intentionally independent of pathname. Authenticated
    // client navigation must never restart the initial session bootstrap.
    if (bootstrapped.current || status === "ready") return;
    bootstrapped.current = true;
    void loadSession(true);
  }, [path, status, loadSession, platformControlCentre, runtimeNative]);

  useUserUpdatedListener(setUser);

  useEffect(() => {
    if (!isNativeShell() || status !== "ready") return;
    void initializeNativePush((destination) => router.push(destination));
    void reconcileNativePush();
  }, [router, status]);

  // Phase 4: native lifecycle re-lock. This is a *local* re-lock layer over
  // the existing server session — never a second session model. It reuses
  // exactly the same bootstrap path a cold launch already goes through
  // (`loadSession(true)` → `bootstrapNativeSession()`), which already
  // contains the whole biometric-gate-then-verify-with-server sequence,
  // the "cancellation never destroys the stored session" guarantee, and
  // the "an expired/revoked server session wins regardless of biometric
  // outcome" behaviour — none of that is reimplemented here, only
  // triggered at the right moment.
  //
  // Registered once, for the component's lifetime, independent of `status`
  // — background/foreground transitions must be tracked accurately even
  // while the app is "locked" or still bootstrapping, not only while
  // "ready". `statusRef`/`loadSessionRef` (kept current by the effects
  // below) let the listener always act on the latest values without being
  // torn down and re-created on every status change, which would otherwise
  // risk missing an appStateChange event during the brief re-subscribe gap.
  const statusRef = useRef(status);
  useEffect(() => {
    statusRef.current = status;
  }, [status]);
  const loadSessionRef = useRef(loadSession);
  useEffect(() => {
    loadSessionRef.current = loadSession;
  }, [loadSession]);
  const reauthenticatingOnResume = useRef(false);

  useEffect(() => {
    if (!isNativeShell()) return;
    startAppLockTracking();
    let disposed = false;
    let removeListener: (() => void) | undefined;
    void App.addListener("appStateChange", ({ isActive }) => {
      if (!isActive) return;
      // Only ever acts while genuinely "ready" — resuming while already
      // "locked" leaves the existing lock screen's own Try again/Sign in
      // with password controls in charge (no auto-retry storm), and there
      // is nothing to protect in any other status (offline/signed_out/
      // initializing already show their own non-authenticated screen).
      if (statusRef.current !== "ready") return;
      // hasEverBeenBackgrounded() first: some platforms fire one
      // appStateChange(isActive:true) during ordinary startup with no
      // preceding isActive:false, which wasBackgroundedLongEnoughToLock()
      // alone cannot distinguish from "backgrounded forever" (see that
      // function's own doc comment on the deliberate `null` → `true`
      // default, which exists for a *different* caller). Cold launch is
      // already fully owned by the bootstrap effect above; this listener
      // has nothing to do unless a real background period was recorded.
      if (!hasEverBeenBackgrounded() || !wasBackgroundedLongEnoughToLock()) return;
      // A synchronous re-entrancy guard, not a ref-derived one: rapid
      // repeated foreground events (task-switcher flicker, a picker/
      // permission dialog's own transitions) must never start a second
      // overlapping re-lock/re-auth attempt while one is already in
      // flight. statusRef alone can't guard this — it only updates after
      // React commits the `setStatus("locked")` below, leaving a window
      // where a second synchronous event in the same tick would still see
      // "ready".
      if (reauthenticatingOnResume.current) return;
      reauthenticatingOnResume.current = true;
      // Set synchronously, before any await, so the very next paint shows
      // the lock screen instead of one frame of the still-mounted
      // authenticated content underneath — there is nothing else that can
      // render in between since nothing but this effect changes `status`.
      setStatus("locked");
      recordAuthDiagnostic("NATIVE_APP_LOCK_RESUME_TRIGGERED");
      void loadSessionRef.current(true).finally(() => {
        reauthenticatingOnResume.current = false;
      });
    }).then((handle) => {
      if (disposed) void handle.remove();
      else removeListener = () => void handle.remove();
    });
    return () => {
      disposed = true;
      removeListener?.();
    };
  }, []);

  const value = useMemo<AuthContextValue>(() => ({
    user,
    status,
    initialSessionLoading,
    sessionRefreshing,
    legalStatus,
    legalStatusError,
    refreshLegalStatus: applyLegalStatus,
    retryLegalStatus: () => void applyLegalStatus(),
    retryInitialSession: () => void loadSession(true),
    refreshSession: () => loadSession(false),
    setAuthenticatedUser: async (authenticatedUser) => {
      bootstrapped.current = true;
      setUser(authenticatedUser);
      // Keep the shell in its branded loading state while MFA completion's
      // legal-status request and React state commit settle. Without this,
      // navigation can briefly render the old signed_out branch as blank.
      setInitialSessionLoading(true);
      // A fresh sign-in (password or MFA) starts this device's Phase-4
      // app-lock clock over from nothing — any "backgrounded at" timestamp
      // recorded before this login belongs to whatever was previously
      // signed in (or to no one, on a first-ever login) and must never be
      // read as if it applied to this session.
      markUnlocked();
      // authentication → required MFA (already complete by the time either
      // caller reaches this point) → legal compliance → application.
      try {
        await applyLegalStatus();
      } finally {
        setInitialSessionLoading(false);
      }
    },
    clearSession: () => {
      setUser(null);
      setStatus("signed_out");
      setLegalStatus(null);
    },
  }), [user, status, initialSessionLoading, sessionRefreshing, legalStatus, applyLegalStatus, loadSession]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
