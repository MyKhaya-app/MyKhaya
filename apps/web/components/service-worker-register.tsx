"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { isSafeInternalPath } from "./internal-path";
import { isNativeShell } from "./native-runtime";

// sw.js's own resolveDeepLinkPath() already maps every notification's
// deep_link to one of a small, closed set of literal internal paths before
// this message is ever sent — isSafeInternalPath below is defence-in-depth
// on top of that, not the primary safety mechanism. It exists so a
// malformed or unexpected message (a future bug in the service worker, or
// any other script able to postMessage this client) can never cause a
// navigation outside the app.

export function ServiceWorkerRegister() {
  const router = useRouter();

  useEffect(() => {
    // Inside the Capacitor native shell, push delivery and foreground
    // navigation will eventually go through native APNs + the web/native
    // bridge (see native-bridge.ts) instead of a service worker message —
    // that's future work, but registering this browser-only listener now
    // would be dead weight at best and a second, conflicting navigation
    // path at worst once the native bridge exists.
    if (isNativeShell()) return;

    // Foreground click-to-navigate: sw.js's notificationclick handler
    // postMessages an already-open client with the resolved path rather
    // than reloading it via clients.openWindow (which is only used when no
    // window is open at all) — this is the listener that was previously
    // missing, so clicking a push notification while the app was already
    // open in a foreground tab did nothing.
    function handleMessage(event: MessageEvent<unknown>) {
      const data = event.data;
      if (
        typeof data !== "object" ||
        data === null ||
        (data as { type?: unknown }).type !== "mykhaya-notification-click"
      ) {
        return;
      }
      const path = (data as { path?: unknown }).path;
      if (!isSafeInternalPath(path)) return;
      router.push(path);
    }
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.addEventListener("message", handleMessage);
    }
    return () => {
      if ("serviceWorker" in navigator) {
        navigator.serviceWorker.removeEventListener("message", handleMessage);
      }
    };
  }, [router]);

  useEffect(() => {
    // The PWA service worker (offline caching, background push) is a
    // browser-tab concept; Capacitor's native app lifecycle (backgrounding,
    // termination, relaunch) is managed by iOS itself, and a future native
    // push implementation (APNs) will replace this path entirely rather
    // than layer on top of it. Registering it here would risk it competing
    // with — or being silently no-op'd/inconsistent under — the native
    // WebView's own lifecycle, for no benefit.
    if (isNativeShell()) return;
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
