"use client";

import { useEffect, useState } from "react";
import { api } from "@mykhaya/api-client";

export type BuildInfo = {
  version: string;
  commit: string;
  build_time: string;
  environment: string;
  channel: string;
};

// Fetches deployment-injected backend build metadata (release tag in production,
// build_channel in apps/api/mykhaya/config.py) — the canonical source for the
// "dev" in development) shown on About (apps/web/app/about).
export function useBuildInfo(): BuildInfo | null {
  const [build, setBuild] = useState<BuildInfo | null>(null);

  useEffect(() => {
    api.buildInfo()
      .then((payload) => setBuild(payload))
      .catch(() => setBuild(null));
  }, []);

  return build;
}
