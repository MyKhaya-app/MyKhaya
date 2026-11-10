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

export type WebBuild = {
  commit: string;
  buildTime: string;
};

// This frontend's own build, inlined by next.config.ts at build time — no
// request — so a developer can tell which web build a browser or native
// shell has loaded, separately from the API's. Development builds only: a
// stable (production) build inlines nothing and this returns null.
export function webBuild(): WebBuild | null {
  const commit = process.env.MYKHAYA_WEB_COMMIT;
  if (!commit) return null;
  return { commit, buildTime: process.env.MYKHAYA_WEB_BUILD_TIME || "unknown" };
}

// A full SHA shortened to 7 characters, keeping a local "-dirty" suffix.
export function shortCommit(commit: string): string {
  if (!commit || commit === "unknown") return "Unknown";
  const separator = commit.indexOf("-");
  const sha = separator === -1 ? commit : commit.slice(0, separator);
  const suffix = separator === -1 ? "" : commit.slice(separator);
  return `${/^[0-9a-f]{40}$/i.test(sha) ? sha.slice(0, 7) : sha}${suffix}`;
}

// "2026-11-01T20:57:42Z" as "2026-11-01 20:57 UTC"; anything else as given.
export function buildTimeText(value: string): string {
  const match = value.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?Z$/);
  if (match) return `${match[1]} ${match[2]} UTC`;
  return !value || value === "unknown" ? "Unknown" : value;
}
