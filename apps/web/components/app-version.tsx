"use client";

import { useEffect, useState } from "react";

type BuildInfo = {
  version: string;
  commit: string;
  build_time: string;
  environment: string;
  channel: string;
};

// Asks the service worker actually controlling this page which cache/SW version it's
// running — the only way to tell "the deploy hasn't reached this device yet" apart
// from "something else is wrong" when a PWA looks stale. No controller (e.g. desktop
// browser tab, or the SW hasn't taken control yet) just means no answer.
function getServiceWorkerVersion(): Promise<string | null> {
  return new Promise((resolve) => {
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator) || !navigator.serviceWorker.controller) {
      resolve(null);
      return;
    }
    const channel = new MessageChannel();
    const timer = setTimeout(() => resolve(null), 2000);
    channel.port1.onmessage = (event: MessageEvent<{ cacheName?: string } | undefined>) => {
      clearTimeout(timer);
      resolve(event.data?.cacheName ?? null);
    };
    navigator.serviceWorker.controller.postMessage({ type: "MYKHAYA_GET_VERSION" }, [channel.port2]);
  });
}

export function AppVersion() {
  const [build, setBuild] = useState<BuildInfo | null>(null);
  const [swVersion, setSwVersion] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/v1/health/build", { cache: "no-store" })
      .then((response) => (response.ok ? (response.json() as Promise<BuildInfo>) : null))
      .then((payload) => setBuild(payload))
      .catch(() => setBuild(null));
    getServiceWorkerVersion().then(setSwVersion);
  }, []);

  if (!build) {
    return <p className="app-version">MyKhaya version unavailable</p>;
  }

  const suffix = build.channel === "development" ? " (development)" : "";
  return (
    <p className="app-version">
      MyKhaya {build.version}
      {suffix}
      {build.channel === "development" && (
        <>
          {" · SW: "}
          {swVersion ?? "not active"}
        </>
      )}
    </p>
  );
}