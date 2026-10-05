"use client";

import { useEffect } from "react";
import { api, ApiError } from "@mykhaya/api-client";

/** Stable code the API puts on its HTTP 503 while PCC maintenance mode is on
 *  (apps/api/mykhaya/platform_runtime.py MAINTENANCE_CODE). */
export const MAINTENANCE_CODE = "maintenance_mode";
export const MAINTENANCE_POLL_MS = 30_000;

export function isMaintenanceError(cause: unknown): boolean {
  return cause instanceof ApiError && cause.status === 503 && cause.code === MAINTENANCE_CODE;
}

/** The full-screen state shown while MyKhaya is in maintenance. It reuses the
 *  existing `app-bootstrap-state` full-screen pattern (same as the offline and
 *  unlock screens), so it needs no new layout and leaves the native/mobile
 *  baseline untouched. It asks the always-reachable public config whether
 *  maintenance is still on and calls `onRecovered` once it is not. */
export function MaintenanceScreen({ onRecovered }: { onRecovered: () => void }) {
  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        const config = await api.publicConfig();
        if (!cancelled && !config.maintenance_mode) onRecovered();
      } catch {
        // Still unreachable or still in maintenance — keep showing the screen.
      }
    }
    const timer = window.setInterval(() => void check(), MAINTENANCE_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [onRecovered]);

  return (
    <main className="app-bootstrap-state" role="alert" data-testid="maintenance-screen">
      <h1>MyKhaya is undergoing maintenance</h1>
      <p>We’re making some improvements and will be back shortly. Your information is safe.</p>
      <button
        onClick={async () => {
          try {
            const config = await api.publicConfig();
            if (!config.maintenance_mode) onRecovered();
          } catch {
            // Remain on the maintenance screen.
          }
        }}
      >
        Check again
      </button>
    </main>
  );
}
