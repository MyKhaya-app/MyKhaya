"use client";

import { useEffect, useMemo, useState } from "react";
import type { Home } from "@mykhaya/shared-types";
import { api } from "@mykhaya/api-client";

const STORAGE_KEY = "mykhaya.activeHomeId";

export function useActiveHome({ enabled = true }: { enabled?: boolean } = {}) {
  const [homes, setHomes] = useState<Home[]>([]);
  const [activeHomeId, setActiveHomeId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    api
      .homes()
      .then((rows) => {
        setError(false);
        setHomes(rows);
        const stored = typeof window === "undefined" ? null : window.localStorage.getItem(STORAGE_KEY);
        const next = rows.find((row) => row.id === stored)?.id ?? rows[0]?.id ?? null;
        setActiveHomeId(next);
        if (next && typeof window !== "undefined") {
          window.localStorage.setItem(STORAGE_KEY, next);
        }
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [enabled]);

  useEffect(() => {
    if (!activeHomeId || typeof window === "undefined") return;
    window.localStorage.setItem(STORAGE_KEY, activeHomeId);
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
  };
}
