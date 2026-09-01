"use client";

import {
  ActionPerformed,
  PermissionStatus,
  PushNotifications,
  Token,
} from "@capacitor/push-notifications";
import type { PluginListenerHandle } from "@capacitor/core";
import { api } from "@mykhaya/api-client";
import { isNativeShell, nativePlatform } from "./native-runtime";

export type NativePushStatus = "unsupported" | "prompt" | "granted" | "denied" | "registering" | "registered" | "error";

let listenersReady: Promise<void> | undefined;
let lastRegistrationId: string | null = null;
let lastToken: string | null = null;
let tokenWaiter: Promise<void> | undefined;
let resolveTokenWaiter: (() => void) | undefined;
let registrationWaiter: Promise<void> | undefined;
let resolveRegistrationWaiter: (() => void) | undefined;
let actionHandler: ((path: string) => void) | undefined;
let listenerHandles: PluginListenerHandle[] = [];

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
    listenerHandles.push(await PushNotifications.addListener("registration", async (token: Token) => {
      lastToken = token.value;
      resolveTokenWaiter?.();
      resolveTokenWaiter = undefined;
      const platform = nativePlatform();
      if (platform !== "ios" && platform !== "android") return;
      const registration = await api.registerNativePushDevice({
        platform,
        token: token.value,
        installation_id: installationId(),
        device_label: platform === "ios" ? "iPhone" : "Android device",
      });
      lastRegistrationId = registration.id;
      resolveRegistrationWaiter?.();
      resolveRegistrationWaiter = undefined;
    }));
    listenerHandles.push(await PushNotifications.addListener("registrationError", () => {}));
    listenerHandles.push(await PushNotifications.addListener("pushNotificationReceived", () => {}));
    listenerHandles.push(await PushNotifications.addListener("pushNotificationActionPerformed", (action) => {
      const value = action.notification.data?.deep_link_path ?? action.notification.data?.deep_link;
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

export async function enableNativePush(
  onAction?: (path: string) => void,
): Promise<{ ok: true; status: "registered" } | { ok: false; status: NativePushStatus }> {
  if (!isNativeShell() || nativePlatform() !== "ios") return { ok: false, status: "unsupported" };
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
    // The registration listener performs the authenticated API write. A token
    // already known to this process has already been reconciled.
    if (!lastToken) {
      tokenWaiter ??= new Promise<void>((resolve) => { resolveTokenWaiter = resolve; });
      await Promise.race([tokenWaiter, new Promise<void>((resolve) => setTimeout(resolve, 10_000))]);
    }
    if (lastToken && !lastRegistrationId) {
      registrationWaiter ??= new Promise<void>((resolve) => { resolveRegistrationWaiter = resolve; });
      await Promise.race([registrationWaiter, new Promise<void>((resolve) => setTimeout(resolve, 10_000))]);
    }
    if (!lastToken || !lastRegistrationId) return { ok: false, status: "error" };
    return { ok: true, status: "registered" };
  } catch {
    return { ok: false, status: "error" };
  }
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
}
