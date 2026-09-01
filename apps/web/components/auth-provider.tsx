"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import type { User } from "@mykhaya/shared-types";
import { api, ApiError } from "@mykhaya/api-client";
import { recordAuthDiagnostic } from "./auth-diagnostics";
import { bootstrapNativeSession } from "./native-auth";
import { isNativeShell } from "./native-runtime";
import { useUserUpdatedListener } from "./user-events";

type AuthStatus = "initializing" | "ready" | "offline" | "signed_out";
type AuthContextValue = {
  user: User | null;
  status: AuthStatus;
  initialSessionLoading: boolean;
  sessionRefreshing: boolean;
  retryInitialSession: () => void;
  refreshSession: () => Promise<boolean>;
  setAuthenticatedUser: (user: User) => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function isPublicPath(path: string) {
  return ["/login", "/register", "/forgot-password", "/reset-password", "/verify-email", "/onboarding"].some(
    (prefix) => path === prefix || path.startsWith(`${prefix}/`),
  );
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<AuthStatus>("signed_out");
  const [initialSessionLoading, setInitialSessionLoading] = useState(false);
  const [sessionRefreshing, setSessionRefreshing] = useState(false);
  const bootstrapped = useRef(false);

  const redirectToLogin = useCallback(() => {
    const destination = typeof window === "undefined" ? "" : `${window.location.pathname}${window.location.search}`;
    router.replace(destination && destination !== "/login" ? `/login?next=${encodeURIComponent(destination)}` : "/login");
  }, [router]);

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
          redirectToLogin();
          return false;
        }
        setUser(restored);
        setStatus("ready");
        recordAuthDiagnostic("NATIVE_BOOTSTRAP_RESULT_AUTHENTICATED");
        return true;
      }
      recordAuthDiagnostic("ME_REQUEST_STARTED");
      setUser(await api.me());
      setStatus("ready");
      recordAuthDiagnostic("ME_RESULT_200");
      recordAuthDiagnostic("AUTHENTICATED");
      return true;
    } catch (cause) {
      if (!isNativeShell() && cause instanceof ApiError && cause.status === 401) {
        try {
          setUser(await api.renew());
          setStatus("ready");
          recordAuthDiagnostic("RENEW_RESULT_200");
          return true;
        } catch (renewalCause) {
          if (renewalCause instanceof ApiError && renewalCause.status === 401) {
            setUser(null);
            setStatus("signed_out");
            recordAuthDiagnostic("LOGIN_REDIRECT");
            redirectToLogin();
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
  }, [redirectToLogin]);

  useEffect(() => {
    if (isPublicPath(path)) {
      setInitialSessionLoading(false);
      if (status !== "ready") setStatus("signed_out");
      return;
    }
    // This guard is intentionally independent of pathname. Authenticated
    // client navigation must never restart the initial session bootstrap.
    if (bootstrapped.current || status === "ready") return;
    bootstrapped.current = true;
    void loadSession(true);
  }, [path, status, loadSession]);

  useUserUpdatedListener(setUser);

  const value = useMemo<AuthContextValue>(() => ({
    user,
    status,
    initialSessionLoading,
    sessionRefreshing,
    retryInitialSession: () => void loadSession(true),
    refreshSession: () => loadSession(false),
    setAuthenticatedUser: (authenticatedUser) => {
      bootstrapped.current = true;
      setUser(authenticatedUser);
      setStatus("ready");
      setInitialSessionLoading(false);
    },
  }), [user, status, initialSessionLoading, sessionRefreshing, loadSession]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
