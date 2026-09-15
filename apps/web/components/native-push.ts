"use client";

import {
  PermissionStatus,
  PushNotifications,
  Token,
} from "@capacitor/push-notifications";
import type { PluginListenerHandle } from "@capacitor/core";
import { api } from "@mykhaya/api-client";
import { isNativeShell, nativePlatform } from "./native-runtime";

export type NativePushStatus = "unsupported" | "prompt" | "granted" | "denied" | "registering" | "registered" | "error";

/** Cross-platform permission result for requestNativePermissionOnly() —
 * structurally identical to notification-permission.ts's
 * NotificationPermissionStatus (that file owns the canonical/shared name;
 * this one is kept import-free to avoid a cross-module type dependency for
 * a single string union). */
export type NativePermissionOnlyResult = "unsupported" | "not_requested" | "granted" | "denied";

let listenersReady: Promise<void> | undefined;
let lastRegistrationId: string | null = null;
let lastToken: string | null = null;
let tokenWaiter: Promise<void> | undefined;
let resolveTokenWaiter: (() => void) | undefined;
let registrationWaiter: Promise<void> | undefined;
let resolveRegistrationWaiter: (() => void) | undefined;
let registrationFailure: unknown;
let registrationActive = false;
let registrationFlight: Promise<{ ok: true; status: "registered" } | { ok: false; status: NativePushStatus }> | undefined;
let cleanupRequested = false;
let actionHandler: ((path: string) => void) | undefined;
let listenerHandles: PluginListenerHandle[] = [];
type NativeNotificationData = {
  deep_link_path?: unknown;
  deep_link?: unknown;
};

function nativeNotificationData(value: unknown): NativeNotificationData {
  if (typeof value !== "object" || value === null) return {};
  const record = value as Record<string, unknown>;
  return { deep_link_path: record.deep_link_path, deep_link: record.deep_link };
}

export function safeNativePushPath(value: unknown): string {
  if (
    typeof value !== "string" ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\")
  ) {
    return "/home";
  }
  const allowed = ["/home", "/calendar", "/calendar/", "/meal-plans", "/people", "/settings/", "/notifications"];
  return allowed.some((prefix) => value === prefix || value.startsWith(prefix)) ? value : "/home";
}

function installationId(): string {
  const key = "mykhaya.native.push.installation";
  const existing = window.localStorage.getItem(key);
  if (existing) return existing;
  const value = crypto.randomUUID();
  window.localStorage.setItem(key, value);
  return value;
}

async function ensureListeners(): Promise<void> {
  if (listenersReady) return listenersReady;
  listenersReady = (async () => {
    async function registerToken(token: Token): Promise<void> {
      lastToken = token.value;
      resolveTokenWaiter?.();
      resolveTokenWaiter = undefined;
      const platform = nativePlatform();
      if (platform !== "ios" && platform !== "android") return;
      try {
        const registration = await api.registerNativePushDevice({
          platform,
          token: token.value,
          installation_id: installationId(),
          device_label: platform === "ios" ? "iPhone" : "Android device",
        });
        lastRegistrationId = registration.id;
        // Diagnostics-only timestamp (About > Diagnostics' "Last
        // registration" row) — never read by any permission/registration
        // decision, so a missing or stale value can't affect behavior.
        try {
          window.localStorage.setItem("mykhaya.native.push.last-registered-at", String(Date.now()));
        } catch {
          // Best-effort; diagnostics simply omit the row if this fails.
        }
      } catch (error) {
        registrationFailure = error;
      } finally {
        resolveRegistrationWaiter?.();
        resolveRegistrationWaiter = undefined;
      }
    }

    listenerHandles.push(await PushNotifications.addListener("registration", (token: Token) => {
      void registerToken(token).catch(() => undefined);
    }));
    listenerHandles.push(await PushNotifications.addListener("registrationError", (error) => {
      registrationFailure = error;
      resolveTokenWaiter?.();
      resolveTokenWaiter = undefined;
      resolveRegistrationWaiter?.();
      resolveRegistrationWaiter = undefined;
    }));
    listenerHandles.push(await PushNotifications.addListener("pushNotificationReceived", () => {}));
    listenerHandles.push(await PushNotifications.addListener("pushNotificationActionPerformed", (action) => {
      const data = nativeNotificationData(action.notification.data as unknown);
      const value = data.deep_link_path ?? data.deep_link;
      actionHandler?.(safeNativePushPath(value));
    }));
  })();
  return listenersReady;
}

export async function initializeNativePush(onAction: (path: string) => void): Promise<void> {
  if (!isNativeShell() || nativePlatform() !== "ios") return;
  actionHandler = onAction;
  await ensureListeners();
}

/** Reconcile an already-granted OS permission without prompting. */
export async function reconcileNativePush(): Promise<void> {
  if (!isNativeShell() || nativePlatform() !== "ios") return;
  const permission = await PushNotifications.checkPermissions();
  if (permission.receive === "granted") await enableNativePush();
}

export async function nativePushPermission(): Promise<PermissionStatus | null> {
  if (!isNativeShell() || nativePlatform() !== "ios") return null;
  return PushNotifications.checkPermissions();
}

/**
 * Resolves OS notification permission only — never waits on, or reports the
 * outcome of, APNs device registration (that's what conflated "OS granted"
 * with "backend registration failed" into one status the Settings page
 * showed as "not enabled" even when the OS permission genuinely was
 * granted). If OS permission is already denied, this does not call
 * `requestPermissions()` again — iOS silently no-ops a second system prompt
 * once denied, so re-asking would only be misleading UI, not a real retry.
 * On the result becoming granted, APNs registration is still kicked off
 * (fire-and-forget, via the existing fully-tested `enableNativePush()`) so
 * the device still gets registered — just decoupled from the status this
 * function returns.
 */
export async function requestNativePermissionOnly(): Promise<NativePermissionOnlyResult> {
  if (!isNativeShell() || nativePlatform() !== "ios") return "unsupported";
  const current = await PushNotifications.checkPermissions();
  if (current.receive === "denied") return "denied";
  if (current.receive === "granted") {
    void reconcileNativePush();
    return "granted";
  }
  const requested = await PushNotifications.requestPermissions();
  if (requested.receive === "granted") {
    void reconcileNativePush();
    return "granted";
  }
  return requested.receive === "denied" ? "denied" : "not_requested";
}

/** Read-only diagnostics for About > Diagnostics — reflects this session's
 * in-memory registration state (populated by reconcileNativePush() on app
 * bootstrap, or by an explicit enable flow), never inferred from OS
 * permission or vice versa. */
export function nativePushDiagnostics(): { tokenPresent: boolean; registered: boolean } {
  return { tokenPresent: Boolean(lastToken), registered: Boolean(lastRegistrationId) };
}

async function enableNativePushOnce(
  onAction?: (path: string) => void,
): Promise<{ ok: true; status: "registered" } | { ok: false; status: NativePushStatus }> {
  if (!isNativeShell() || nativePlatform() !== "ios") return { ok: false, status: "unsupported" };
  registrationActive = true;
  cleanupRequested = false;
  registrationFailure = undefined;
  try {
    actionHandler = onAction;
    await ensureListeners();
    let permission = await PushNotifications.checkPermissions();
    if (permission.receive === "denied") return { ok: false, status: "denied" };
    if (permission.receive !== "granted") {
      permission = await PushNotifications.requestPermissions();
    }
    if (permission.receive !== "granted") return { ok: false, status: "denied" };
    await PushNotifications.register();
    if (registrationFailure) return { ok: false, status: "error" };
    // The registration listener performs the authenticated API write. A token
    // already known to this process has already been reconciled.
    if (!lastToken) {
      tokenWaiter ??= new Promise<void>((resolve) => { resolveTokenWaiter = resolve; });
      await Promise.race([tokenWaiter, new Promise<void>((resolve) => setTimeout(() => {
        resolve();
      }, 10_000))]);
    }
    if (registrationFailure) return { ok: false, status: "error" };
    if (lastToken && !lastRegistrationId) {
      registrationWaiter ??= new Promise<void>((resolve) => { resolveRegistrationWaiter = resolve; });
      await Promise.race([registrationWaiter, new Promise<void>((resolve) => setTimeout(() => {
        resolve();
      }, 10_000))]);
    }
    if (registrationFailure || !lastToken || !lastRegistrationId) return { ok: false, status: "error" };
    return { ok: true, status: "registered" };
  } catch {
    return { ok: false, status: "error" };
  } finally {
    registrationActive = false;
    if (cleanupRequested) await finishCleanup();
  }
}

/**
 * Coordinated native registration entry point. Startup reconciliation,
 * permission onboarding, and explicit settings actions all share this
 * promise, so a concurrent lifecycle event cannot call the native register
 * API more than once.
 */
export function enableNativePush(
  onAction?: (path: string) => void,
): Promise<{ ok: true; status: "registered" } | { ok: false; status: NativePushStatus }> {
  if (!registrationFlight) {
    registrationFlight = enableNativePushOnce(onAction).finally(() => {
      registrationFlight = undefined;
    });
  }
  return registrationFlight;
}

export async function revokeNativePush(): Promise<void> {
  if (lastRegistrationId) {
    await api.deleteNativePushDevice(lastRegistrationId).catch(() => {});
  }
  lastRegistrationId = null;
  lastToken = null;
}

/** Remove native listeners when the authenticated native shell is torn down. */
export async function cleanupNativePush(): Promise<void> {
  if (registrationActive) {
    cleanupRequested = true;
    return;
  }
  await finishCleanup();
}

async function finishCleanup(): Promise<void> {
  await Promise.all(
    listenerHandles.map((handle) => Promise.resolve(handle.remove()).catch(() => undefined)),
  );
  listenerHandles = [];
  listenersReady = undefined;
  tokenWaiter = undefined;
  resolveTokenWaiter = undefined;
  registrationWaiter = undefined;
  resolveRegistrationWaiter = undefined;
  actionHandler = undefined;
  registrationFlight = undefined;
  cleanupRequested = false;
}
