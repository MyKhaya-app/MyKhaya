import type { User } from "@mykhaya/shared-types";
import {
  InMemoryNativeSessionStore,
  NativeMyKhayaClient,
  nativeApiBaseUrlForWebHost,
  type NativeSessionStore,
} from "@mykhaya/api-client";

// Native auth bootstrap (task §7/§9/§10). This module is the only place
// `apps/web` constructs a `NativeMyKhayaClient` — every native auth call
// (login, child login, session restore, sign-out) should go through the
// functions below rather than a component reaching for the client class
// directly, so there is exactly one shared client/store pair per page load.
//
// The store here is `InMemoryNativeSessionStore` (Phase 2) — real Keychain
// persistence is Phase 4's job (see docs/architecture/adr/0012). That means
// "persistent login across app restarts" is not actually wired up to real
// storage yet, but everything above the storage boundary (client
// construction, bootstrap, login, logout) is already written against the
// `NativeSessionStore` interface, so swapping in a real adapter later is a
// one-line change here, not a rewrite of this module or its callers.
let sharedStore: NativeSessionStore | undefined;
let sharedClient: NativeMyKhayaClient | undefined;

function client(): NativeMyKhayaClient {
  if (!sharedClient) {
    sharedStore ??= new InMemoryNativeSessionStore();
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
