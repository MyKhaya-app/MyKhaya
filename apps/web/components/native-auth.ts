import type { User } from "@mykhaya/shared-types";
import {
  InMemoryNativeSessionStore,
  NativeMyKhayaClient,
  nativeApiBaseUrlForWebHost,
  type NativeSessionStore,
} from "@mykhaya/api-client";
import { isNativeShell } from "./native-runtime";
import { KeychainNativeSessionStore } from "./keychain-native-session-store";

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

function client(): NativeMyKhayaClient {
  if (!sharedClient) {
    sharedStore ??= isNativeShell()
      ? new KeychainNativeSessionStore()
      : new InMemoryNativeSessionStore();
    sharedClient = new NativeMyKhayaClient(
      nativeApiBaseUrlForWebHost(window.location.hostname),
      sharedStore,
    );
  }
  return sharedClient;
}

/** App-start bootstrap: returns the signed-in user if a stored native
 * session is still valid, or null if there is none / it was rejected. Never
 * exposes the bearer token — see `NativeMyKhayaClient.bootstrapSession`. */
export function bootstrapNativeSession(): Promise<User | null> {
  return client().bootstrapSession();
}

export function nativeLogin(email: string, password: string): Promise<User> {
  return client().login(email, password);
}

export function nativeChildLogin(
  homeCode: string,
  username: string,
  pin: string,
): Promise<User> {
  return client().childLogin(homeCode, username, pin);
}

export function nativeLogout(): Promise<void> {
  return client().logout();
}
