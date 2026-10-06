"use client";

import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { BillingStatus, FeatureMatrix } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { useAuth } from "./auth-provider";
import { useActiveHome } from "./use-active-home";
import { failed, LOADING, ready, type Resolved } from "./resolvable";

// Plan/entitlement/feature state for the active Home, resolved ONCE and shared
// by the whole authenticated shell (nav, quick-action dock, More, ...) instead
// of each surface fetching it on its own and guessing meanwhile. Billing and
// the feature matrix are resolved together: a surface only ever sees both or
// neither, so "matrix arrived, billing not yet" can never render a premium
// module as available before it is revealed to be locked.
//
// Cached per Home for the lifetime of the (persistent) shell: navigating
// between pages and switching back to a Home reads the cache immediately and
// revalidates silently in the background, so there is no re-loading state.
export type HomeAccess = { billing: BillingStatus; features: FeatureMatrix };

export type HomeAccessContextValue = {
  /** Access for the *active* Home. Never carries another Home's data. */
  access: Resolved<HomeAccess>;
  /** Re-resolve after something that can change the plan (checkout, grant). */
  refresh: () => Promise<void>;
};

const HomeAccessContext = createContext<HomeAccessContextValue | null>(null);

function fetchHomeAccess(homeId: string): Promise<HomeAccess> {
  return Promise.all([api.billingStatus(homeId), api.featureMatrix(homeId)]).then(
    ([billing, features]) => ({ billing, features }),
  );
}

function useHomeAccessState(enabled: boolean): HomeAccessContextValue {
  const { activeHomeId } = useActiveHome();
  const { status } = useAuth();
  const authenticated = status === "ready";
  const [cache, setCache] = useState<Record<string, Resolved<HomeAccess>>>({});

  // Bumped whenever the session ends, so a response still in flight from the
  // previous session is discarded instead of repopulating the cache.
  const epoch = useRef(0);

  const load = useCallback(async (homeId: string) => {
    const started = epoch.current;
    try {
      const value = await fetchHomeAccess(homeId);
      if (epoch.current !== started) return;
      setCache((current) => ({ ...current, [homeId]: ready(value) }));
    } catch (error) {
      if (epoch.current !== started) return;
      // Keep a previously-resolved value rather than regress to an error on a
      // transient revalidation failure; only a Home with nothing yet errors.
      setCache((current) => (current[homeId]?.state === "ready" ? current : { ...current, [homeId]: failed(error) }));
    }
  }, []);

  // Plan state belongs to the authenticated session: drop everything the
  // moment it ends (sign-out, expiry, lock) so a later session can never read it.
  useEffect(() => {
    if (authenticated) return;
    epoch.current += 1;
    setCache({});
  }, [authenticated]);

  useEffect(() => {
    if (!enabled || !activeHomeId || !authenticated) return;
    void load(activeHomeId);
    const revalidate = () => {
      if (document.visibilityState === "visible") void load(activeHomeId);
    };
    document.addEventListener("visibilitychange", revalidate);
    return () => document.removeEventListener("visibilitychange", revalidate);
  }, [enabled, activeHomeId, authenticated, load]);

  const refresh = useCallback(async () => {
    if (activeHomeId) await load(activeHomeId);
  }, [activeHomeId, load]);

  const access = activeHomeId && authenticated ? (cache[activeHomeId] ?? LOADING) : LOADING;
  return useMemo(() => ({ access, refresh }), [access, refresh]);
}

export function HomeAccessProvider({ children }: { children: React.ReactNode }) {
  const value = useHomeAccessState(true);
  return createElement(HomeAccessContext.Provider, { value }, children);
}

/** Active-Home access. Reads the shell's shared, cached state; a surface
 *  rendered outside the shell (isolated pages/tests) resolves it itself. */
export function useHomeAccess(): HomeAccessContextValue {
  const shared = useContext(HomeAccessContext);
  const own = useHomeAccessState(shared === null);
  return shared ?? own;
}

export function featureEnabled(features: FeatureMatrix | undefined, feature: string): boolean {
  return Boolean(features?.features.some((item) => item.feature === feature && item.enabled));
}
