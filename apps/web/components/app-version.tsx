"use client";

import { useEffect, useState } from "react";

export type BuildInfo = {
  version: string;
  commit: string;
  build_time: string;
  environment: string;
  channel: string;
};

// Fetches the backend-reported build metadata (see resolve_app_version() /
// build_channel in apps/api/mykhaya/config.py) — the canonical source for the
// Web version and "development" channel shown on About (apps/web/app/about).
export function useBuildInfo(): BuildInfo | null {
  const [build, setBuild] = useState<BuildInfo | null>(null);

  useEffect(() => {
    fetch("/api/v1/health/build", { cache: "no-store" })
      .then((response) => (response.ok ? (response.json() as Promise<BuildInfo>) : null))
      .then((payload) => setBuild(payload))
      .catch(() => setBuild(null));
  }, []);

  return build;
}
