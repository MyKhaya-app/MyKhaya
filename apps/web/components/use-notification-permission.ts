"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { App } from "@capacitor/app";
import {
  getNotificationPermissionAdapter,
  type NotificationPermissionStatus,
} from "./notification-permission";

/**
 * Shared state machine for the "This device" Settings status and the
 * NotificationPermissionPrompt sheet. Never infers status from anything but
 * a live platform check — no APNs-token presence, no device-registration
 * record, no cached value. Refreshes on mount, on app resume (foreground),
 * and after requestPermission()/openSettings() resolve — covering "user
 * flips it in iOS Settings and comes back" without a kill-and-reopen.
 */
export function useNotificationPermission() {
  const [status, setStatus] = useState<NotificationPermissionStatus>("unsupported");
  const [loading, setLoading] = useState(true);
  const adapter = useRef(getNotificationPermissionAdapter()).current;

  const refresh = useCallback(async () => {
    const next = await adapter.refreshPermissionStatus();
    setStatus(next);
    return next;
  }, [adapter]);

  useEffect(() => {
    let cancelled = false;
    adapter.getPermissionStatus().then((next) => {
      if (!cancelled) {
        setStatus(next);
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [adapter]);

  useEffect(() => {
    // Mirrors the App.addListener("appStateChange") pattern already used by
    // native-app-lock.ts — added independently here since that module's
    // listener isn't wired into the app and covers an unrelated concern
    // (biometric re-lock timing), not permission refresh.
    const handle = App.addListener("appStateChange", ({ isActive }) => {
      if (isActive) void refresh();
    });
    function onVisibility() {
      if (document.visibilityState === "visible") void refresh();
    }
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      void handle.then((h) => h.remove()).catch(() => undefined);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [refresh]);

  const requestPermission = useCallback(async () => {
    const next = await adapter.requestPermission();
    setStatus(next);
    // A returning-from-permission-dialog re-check is cheap and guards
    // against the OS resolving the prompt asynchronously relative to the
    // adapter's own return value on some platforms.
    void refresh();
    return next;
  }, [adapter, refresh]);

  const openSettings = useCallback(async () => {
    await adapter.openSystemNotificationSettings();
    void refresh();
  }, [adapter, refresh]);

  return { status, loading, requestPermission, openSettings, refresh };
}
