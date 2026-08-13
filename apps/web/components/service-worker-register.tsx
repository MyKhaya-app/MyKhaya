"use client";

import { useEffect } from "react";

export function ServiceWorkerRegister() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;

    let registration: ServiceWorkerRegistration | undefined;
    navigator.serviceWorker
      .register("/sw.js")
      .then((reg) => {
        registration = reg;
      })
      .catch((cause: unknown) => {
        // Offline/push support is a progressive enhancement — a failed registration
        // must never break the app, but silently swallowing it here previously hid a
        // real deployment bug (the service worker file 404ing) for a long time.
        if (process.env.NODE_ENV !== "production") {
          console.error("Service worker registration failed:", cause);
        }
      });

    // Installed iOS PWAs don't reliably re-check for a new service worker just by
    // being reopened from the background — nudge a check whenever the app regains
    // visibility so an update isn't stuck waiting for some other trigger.
    function checkForUpdate() {
      if (document.visibilityState === "visible") registration?.update().catch(() => {});
    }
    document.addEventListener("visibilitychange", checkForUpdate);
    return () => document.removeEventListener("visibilitychange", checkForUpdate);
  }, []);

  return null;
}
