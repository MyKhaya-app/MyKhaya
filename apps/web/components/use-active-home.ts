"use client";

import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { Home } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";
import { useAuth } from "./auth-provider";
import { syncWidgetSnapshot } from "./widget-bridge";

const STORAGE_KEY = "mykhaya.activeHomeId";

type ActiveHomeState = ReturnType<typeof useActiveHomeState>;
const EMPTY_ACTIVE_HOME_STATE: ActiveHomeState = {
  homes: [],
  activeHome: null,
  activeHomeId: null,
  setActiveHomeId: () => undefined,
  loading: true,
  error: false,
  refreshHomes: async () => undefined,
};
const ActiveHomeContext = createContext<ActiveHomeState>(EMPTY_ACTIVE_HOME_STATE);

function useActiveHomeState({ enabled = true }: { enabled?: boolean } = {}) {
  const [homes, setHomes] = useState<Home[]>([]);
  const [activeHomeId, setActiveHomeId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const refreshHomes = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api.homes();
      setError(false);
      setHomes(rows);
      const stored = typeof window === "undefined" ? null : window.localStorage.getItem(STORAGE_KEY);
      const next = rows.find((row) => row.id === stored)?.id ?? rows[0]?.id ?? null;
      setActiveHomeId(next);
      if (next && typeof window !== "undefined") {
        window.localStorage.setItem(STORAGE_KEY, next);
      }
    } catch {
      setError(true);
      throw new Error("Could not refresh Homes.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void refreshHomes().catch(() => undefined);
  }, [enabled, refreshHomes]);

  useEffect(() => {
    if (!activeHomeId || typeof window === "undefined") return;
    window.localStorage.setItem(STORAGE_KEY, activeHomeId);
    // Old-Home data must not linger on the Home Screen after switching —
    // this fires for the initial selection too, which is fine: it's the
    // same fetch bootstrapNativeSession's own sync would otherwise race.
    void syncWidgetSnapshot();
  }, [activeHomeId]);

  const activeHome = useMemo(
    () => homes.find((home) => home.id === activeHomeId) ?? null,
    [homes, activeHomeId],
  );

  return {
    homes,
    activeHome,
    activeHomeId,
    setActiveHomeId,
    loading,
    error,
    refreshHomes,
  };
}

export function ActiveHomeProvider({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const value = useActiveHomeState({ enabled: status === "ready" });
  return createElement(ActiveHomeContext.Provider, { value }, children);
}

export function useActiveHome() {
  return useContext(ActiveHomeContext);
}
