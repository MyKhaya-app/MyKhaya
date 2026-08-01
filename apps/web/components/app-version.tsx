"use client";

import { useEffect, useState } from "react";

type BuildInfo = {
  version: string;
  commit: string;
  build_time: string;
  environment: string;
  channel: string;
};

export function AppVersion() {
  const [build, setBuild] = useState<BuildInfo | null>(null);

  useEffect(() => {
    fetch("/api/v1/health/build", { cache: "no-store" })
      .then((response) => (response.ok ? (response.json() as Promise<BuildInfo>) : null))
      .then((payload) => setBuild(payload))
      .catch(() => setBuild(null));
  }, []);

  if (!build) {
    return <p className="app-version">MyKhaya version unavailable</p>;
  }

  const suffix = build.channel === "development" ? " (development)" : "";
  return (
    <p className="app-version">
      MyKhaya {build.version}
      {suffix}
    </p>
  );
}