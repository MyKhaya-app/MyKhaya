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

export type NativePushDiagnostic = {
  stage: string;
  permission?: string;
  tokenPresent?: boolean;
  registrationPresent?: boolean;
  errorCategory?: string;
  status?: number;
};

let listenersReady: Promise<void> | undefined;
let lastRegistrationId: string | null = null;
let lastToken: string | null = null;
let tokenWaiter: Promise<void> | undefined;
let resolveTokenWaiter: (() => void) | undefined;
let registrationWaiter: Promise<void> | undefined;
let resolveRegistrationWaiter: (() => void) | undefined;
let registrationFailure: unknown;
let registrationActive = false;
let cleanupRequested = false;
let actionHandler: ((path: string) => void) | undefined;
let listenerHandles: PluginListenerHandle[] = [];
let latestDiagnostic: NativePushDiagnostic | null = null;
const diagnosticListeners = new Set<() => void>();

type DiagnosticValue = boolean | number | string | undefined;

function nativePushDiagnostic(stage: string, details: Record<string, DiagnosticValue> = {}): void {
  latestDiagnostic = {
    stage,
    permission: typeof details.permission === "string" ? details.permission : undefined,
    tokenPresent: typeof details.token_present === "boolean" ? details.token_present : undefined,
    registrationPresent: typeof details.registration_present === "boolean" ? details.registration_present : undefined,
    errorCategory: typeof details.error_category === "string" ? details.error_category : undefined,
    status: typeof details.status === "number" ? details.status : undefined,
  };
  diagnosticListeners.forEach((listener) => listener());
  console.info("[MyKhaya native push]", { stage, ...details });
}

export function getNativePushDiagnostic(): NativePushDiagnostic | null {
  return latestDiagnostic;
}

export function subscribeNativePushDiagnostics(listener: () => void): () => void {
  diagnosticListeners.add(listener);
  return () => diagnosticListeners.delete(listener);
}

export function nativePushDiagnosticsText(diagnostic: NativePushDiagnostic | null = latestDiagnostic): string {
  if (!diagnostic) return "native_push_stage=not_started";
  const lines = [`native_push_stage=${diagnostic.stage}`];
  if (diagnostic.permission) lines.push(`permission=${diagnostic.permission}`);
  if (diagnostic.tokenPresent !== undefined) lines.push(`token_present=${diagnostic.tokenPresent}`);
  if (diagnostic.registrationPresent !== undefined) lines.push(`registration_present=${diagnostic.registrationPresent}`);
  if (diagnostic.errorCategory) lines.push(`error_category=${diagnostic.errorCategory}`);
  if (diagnostic.status !== undefined) lines.push(`status=${diagnostic.status}`);
  return lines.join("\n");
}

function errorStatus(error: unknown): number | undefined {
  if (typeof error !== "object" || error === null || !("status" in error)) return undefined;
  const status = error.status;
  return typeof status === "number" ? status : undefined;
}

function errorCategory(error: unknown): string {
  return error instanceof Error ? error.name : "unknown";
}

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
      nativePushDiagnostic("os_token_received", { token_present: Boolean(token.value) });
      resolveTokenWaiter?.();
      resolveTokenWaiter = undefined;
      const platform = nativePlatform();
      if (platform !== "ios" && platform !== "android") return;
      nativePushDiagnostic("backend_register_started", { token_present: Boolean(token.value) });
      try {
        const registration = await api.registerNativePushDevice({
          platform,
          token: token.value,
          installation_id: installationId(),
          device_label: platform === "ios" ? "iPhone" : "Android device",
        });
        lastRegistrationId = registration.id;
        nativePushDiagnostic("backend_register_succeeded", { status: 200 });
      } catch (error) {
        registrationFailure = error;
        nativePushDiagnostic("backend_register_failed", {
          status: errorStatus(error),
          error_category: errorCategory(error),
        });
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
      nativePushDiagnostic("os_registration_failed", { error_category: errorCategory(error) });
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
    nativePushDiagnostic("listeners_ready", { listener_count: listenerHandles.length });
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
  nativePushDiagnostic("permission_checked", { permission: permission.receive });
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
  registrationActive = true;
  cleanupRequested = false;
  registrationFailure = undefined;
  try {
    actionHandler = onAction;
    await ensureListeners();
    nativePushDiagnostic("permission_check_started");
    let permission = await PushNotifications.checkPermissions();
    nativePushDiagnostic("permission_checked", { permission: permission.receive });
    if (permission.receive === "denied") return { ok: false, status: "denied" };
    if (permission.receive !== "granted") {
      nativePushDiagnostic("permission_request_started");
      permission = await PushNotifications.requestPermissions();
      nativePushDiagnostic("permission_requested", { permission: permission.receive });
    }
    if (permission.receive !== "granted") return { ok: false, status: "denied" };
    nativePushDiagnostic("os_register_requested");
    await PushNotifications.register();
    if (registrationFailure) return { ok: false, status: "error" };
    // The registration listener performs the authenticated API write. A token
    // already known to this process has already been reconciled.
    if (!lastToken) {
      tokenWaiter ??= new Promise<void>((resolve) => { resolveTokenWaiter = resolve; });
      await Promise.race([tokenWaiter, new Promise<void>((resolve) => setTimeout(() => {
        nativePushDiagnostic("token_timeout", { token_present: Boolean(lastToken) });
        resolve();
      }, 10_000))]);
    }
    if (registrationFailure) return { ok: false, status: "error" };
    if (lastToken && !lastRegistrationId) {
      registrationWaiter ??= new Promise<void>((resolve) => { resolveRegistrationWaiter = resolve; });
      await Promise.race([registrationWaiter, new Promise<void>((resolve) => setTimeout(() => {
        nativePushDiagnostic("backend_register_timeout", { token_present: true, registration_present: false });
        resolve();
      }, 10_000))]);
    }
    if (registrationFailure || !lastToken || !lastRegistrationId) return { ok: false, status: "error" };
    return { ok: true, status: "registered" };
  } catch (error) {
    nativePushDiagnostic("registration_failed", { error_category: errorCategory(error), status: errorStatus(error) });
    return { ok: false, status: "error" };
  } finally {
    registrationActive = false;
    if (cleanupRequested) await finishCleanup();
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
  if (registrationActive) {
    cleanupRequested = true;
    nativePushDiagnostic("cleanup_deferred", { registration_pending: true });
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
  cleanupRequested = false;
}
