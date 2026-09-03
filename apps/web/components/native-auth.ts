import type { User } from "@mykhaya/shared-types";
import {
  InMemoryNativeSessionStore,
  NativeMyKhayaClient,
  api,
  nativeApiBaseUrlForWebHost,
  type NativeSessionStore,
} from "@mykhaya/api-client";
import { isNativeShell, nativePlatform } from "./native-runtime";
import { KeychainNativeSessionStore } from "./keychain-native-session-store";
import { setBiometricSignInEnabled } from "./native-biometric-preference";
import { authenticateWithBiometrics, getBiometricCapability, isBiometricCancellation } from "./native-biometric";
import { clearWidgetSnapshot, syncWidgetSnapshot } from "./widget-bridge";

export class NativeBiometricUnlockError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "NativeBiometricUnlockError";
    this.code = code;
  }
}

// Native auth bootstrap (task §7/§9/§10, Keychain wiring in Phase 4 §11).
// This module is the only place `apps/web` constructs a
// `NativeMyKhayaClient` — every native auth call (login, child login,
// session restore, sign-out) should go through the functions below rather
// than a component reaching for the client class directly, so there is
// exactly one shared client/store pair per page load.
//
// Store selection is explicit and made once, here: inside the real
// Capacitor iOS shell, sessions persist in the iOS Keychain
// (`KeychainNativeSessionStore`, ADR 0012 Phase 4) so a signed-in user
// survives the app being terminated and reopened. Everywhere else
// (an ordinary browser tab, Vitest, any non-native context) falls back to
// `InMemoryNativeSessionStore` — there is no real "native session" to
// persist there, and it keeps this module trivially testable without a
// Keychain to hand. Browser/cookie authentication is completely untouched
// by this choice; it's a separate transport (see native-client.ts).
let sharedStore: NativeSessionStore | undefined;
let sharedClient: NativeMyKhayaClient | undefined;
let lastNativeLoginDiagnostic: string | null = null;
let offerBiometricAfterLogin = false;

function biometricDebug(event: string, fields: Record<string, unknown> = {}): void {
  console.info("[BIOMETRIC DEBUG]", event, fields);
}

async function withNativeStartupTimeout<T>(promise: Promise<T>, label: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      biometricDebug("native_plugin_timeout", { operation: label });
      reject(new NativeBiometricUnlockError("timeout", "Native biometric startup timed out."));
    }, 10000);
    promise.then((value) => { clearTimeout(timer); resolve(value); }, (error) => {
      clearTimeout(timer);
      reject(error instanceof Error ? error : new Error("Native startup operation failed."));
    });
  });
}

export function getLastNativeLoginDiagnostic(): string | null {
  return lastNativeLoginDiagnostic;
}

export async function runNativeNetworkDiagnostics(): Promise<string[]> {
  return client().diagnosticProbe();
}

export function fetchNativeImage(path: string): Promise<Blob> {
  return client().image(path);
}

// Device-friendly labelling for the Security page's "Signed-in devices"
// list (Phase 9) — read server-side via mobile_client_descriptor/
// device_platform (see routers.auth) into Session.user_agent /
// TrustedDevice.platform. A native login with these headers present shows
// as "iOS" there instead of a raw WKWebView user-agent string; an ordinary
// browser/PWA request never sends them at all (device_platform's own
// server-side default is "Web/PWA"), so existing devices are unaffected.
function clientHeaders(): { client: string; platform: string } | undefined {
  const platform = nativePlatform();
  if (platform === "web") return undefined;
  const label = platform === "ios" ? "iOS" : "Android";
  return { client: `MyKhaya ${label}`, platform: label };
}

function client(): NativeMyKhayaClient {
  if (!sharedClient) {
    sharedStore ??= isNativeShell()
      ? new KeychainNativeSessionStore()
      : new InMemoryNativeSessionStore();
    sharedClient = new NativeMyKhayaClient(
      nativeApiBaseUrlForWebHost(window.location.hostname),
      sharedStore,
      { clientHeaders: clientHeaders() },
    );
    api.setRequestTransport(sharedClient.request.bind(sharedClient));
  }
  return sharedClient;
}

/** App-start bootstrap: returns the signed-in user if a stored native
 * session is still valid, or null if there is none / it was rejected. Never
 * exposes the bearer token — see `NativeMyKhayaClient.bootstrapSession`. */
export function bootstrapNativeSession(): Promise<User | null> {
  return (async () => {
    biometricDebug("native_platform_detected", { platform: nativePlatform() });
    const nativeClient = client();
    const sessionPresent = await withNativeStartupTimeout(nativeClient.hasStoredSession(), "keychain_session_check");
    biometricDebug("keychain_session_present", { present: sessionPresent });
    if (!sessionPresent) return null;
    const { isBiometricSignInEnabled } = await import("./native-biometric-preference");
    const biometricEnabled = await withNativeStartupTimeout(isBiometricSignInEnabled(), "biometric_preference");
    biometricDebug("preference_result", { enabled: biometricEnabled });
    if (biometricEnabled) {
      const capability = await withNativeStartupTimeout(getBiometricCapability(), "biometric_availability");
      biometricDebug("availability_result", { available: capability.available, type: capability.kind });
      if (!capability.available) {
        throw new NativeBiometricUnlockError("unavailable", "Biometric unlock is unavailable.");
      }
      const result = await withNativeStartupTimeout(authenticateWithBiometrics("Unlock MyKhaya"), "biometric_challenge");
      if (!result.ok) {
        throw new NativeBiometricUnlockError(
          isBiometricCancellation(result) ? "cancelled" : result.code,
          "Biometric unlock was not completed.",
        );
      }
    }
    biometricDebug("session_restoration_started");
    const restored = await nativeClient.bootstrapSession();
    biometricDebug("session_restoration_completed", { authenticated: Boolean(restored) });
    if (restored) void syncWidgetSnapshot();
    return restored;
  })();
}

export function nativeLogin(email: string, password: string): Promise<User> {
  lastNativeLoginDiagnostic = null;
  return client().login(email, password).then((user) => {
    offerBiometricAfterLogin = true;
    void syncWidgetSnapshot();
    return user;
  }).catch((error: unknown) => {
    if (error instanceof Error && "status" in error && typeof error.status === "number") {
      const code = "code" in error && typeof error.code === "string" ? error.code : `http_${error.status}`;
      lastNativeLoginDiagnostic = diagnosticContext(`stage: request; status: ${error.status}; code: ${code}`);
    } else {
      const message = error instanceof Error ? error.message : "";
      lastNativeLoginDiagnostic = diagnosticContext(`stage: network; status: none; error: ${error instanceof Error ? error.name : "fetch_failed"}${message ? `; message: ${message}` : ""}`);
    }
    throw error;
  });
}

export function consumeBiometricOfferAfterLogin(): boolean {
  const result = offerBiometricAfterLogin;
  offerBiometricAfterLogin = false;
  return result;
}

function diagnosticContext(summary: string): string {
  const origin = typeof window === "undefined" ? "unknown" : window.location.origin;
  const host = typeof window === "undefined" ? "unknown" : window.location.hostname;
  const api = typeof window === "undefined"
    ? "unknown"
    : `${nativeApiBaseUrlForWebHost(host)}/auth/mobile/login`;
  const native = typeof window !== "undefined" && isNativeShell();
  const environment = host === "dev.mykhaya.app" ? "development" : host === "mykhaya.app" ? "production" : "unknown";
  const online = typeof navigator === "undefined" ? "unknown" : String(navigator.onLine);
  return `${summary}; origin: ${origin}; api: ${api}; native: ${native}; online: ${online}; environment: ${environment}`;
}

export function nativeChildLogin(
  homeCode: string,
  username: string,
  pin: string,
): Promise<User> {
  return client().childLogin(homeCode, username, pin).then((user) => {
    void syncWidgetSnapshot();
    return user;
  });
}

/** Explicit sign-out (Phase 8): revokes the server-side session (and its
 * linked long-lived device credential — see routers.auth.mobile_logout),
 * removes the local Keychain credential (NativeMyKhayaClient.logout()
 * always clears the store even if the network call fails), and clears the
 * Quick Sign-In preference — a device that's been signed out of should not
 * still offer "unlock with Face ID" on its next launch. Never touches any
 * other signed-in device. */
export async function nativeLogout(): Promise<void> {
  try {
    const { cleanupNativePush, revokeNativePush } = await import("./native-push");
    await revokeNativePush();
    await cleanupNativePush();
    await client().logout();
  } finally {
    api.setRequestTransport(null);
    await setBiometricSignInEnabled(false);
    // Must run even if the network logout call failed above — a widget
    // must never keep showing a signed-out user's household data.
    await clearWidgetSnapshot();
  }
}

/** Explicit foreground/lifecycle renewal (Phase 6/11) — distinct from
 * bootstrapSession()'s own automatic renew-on-401 fallback: this is for a
 * caller (e.g. an app-resume handler) that wants to proactively refresh a
 * session that might have quietly expired while backgrounded, without
 * first taking the round-trip cost of a failed /users/me call. Throws if
 * there is no renewable device credential or the server rejects it —
 * callers should treat that the same as bootstrapNativeSession() returning
 * null (session cannot be silently restored; fall back to Login). */
export function nativeRenewSession(): Promise<User> {
  return client().renew();
}
