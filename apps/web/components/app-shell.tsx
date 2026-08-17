"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import type { User } from "@mykhaya/shared-types";
import { api, ApiError } from "@mykhaya/api-client";
import { AppHeader } from "./app-header";
import { BottomNav } from "./bottom-nav";
import { useActiveHome } from "./use-active-home";
import { useUserUpdatedListener } from "./user-events";

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
    setAuthState("loading");
    try {
      setUser(await api.me());
      setAuthState("ready");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        try {
          setUser(await api.renew());
          setAuthState("ready");
          return;
        } catch (renewalCause) {
          if (renewalCause instanceof ApiError && renewalCause.status === 401) {
            setAuthState("signed_out");
            router.replace("/login");
          } else {
            setAuthState("offline");
          }
          return;
        }
      }
      setAuthState("offline");
    }
  }, [router]);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    if (authState === "ready" && !homesError && !loading && !homes.length && path !== "/onboarding")
      router.replace("/onboarding");
  }, [authState, homes, homesError, loading, path, router]);

  useUserUpdatedListener(setUser);

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
      {hero}
      <main className="app-main">{children}</main>
      <BottomNav principalType={user?.principal_type} />
    </div>
  );
}
