"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { ApiError, platformApi } from "@mykhaya/api-client";
import { resolveLoginDestination } from "./platform-mfa-logic";
import type { PlatformActor } from "./platform-types";

// PCC's authoritative "who is this administrator" state, as a tri-state that
// is shared by every page (each page mounts its own <PlatformShell>, so this
// lives at module scope rather than in component state):
//
//   resolving → authenticated | unauthenticated | unavailable
//
// `resolving` is the initial value and renders nothing privileged. Once an
// actor has been resolved it is reused immediately on later navigations and
// revalidated silently — no repeated "loading" state inside a session.
// Client-side only: every /platform API still enforces auth server-side.
export type PlatformSessionState =
  | { state: "resolving" }
  | { state: "authenticated"; actor: PlatformActor }
  | { state: "unauthenticated"; destination: "/login" | "/setup-mfa" }
  | { state: "unavailable" };

const RESOLVING: PlatformSessionState = { state: "resolving" };
// How long a successful /auth/me result may be rendered from without asking
// again. Within it, page-to-page navigation is instant; past it, a newly
// mounted shell goes back to `resolving` and renders nothing privileged until
// the server has answered, so an expired/logged-out session can never paint
// protected UI from a stale cache.
const REVALIDATE_AFTER_MS = 10_000;

let current: PlatformSessionState = RESOLVING;
let inflight: Promise<void> | null = null;
let resolvedAt = 0;
const listeners = new Set<() => void>();

function publish(next: PlatformSessionState) {
  current = next;
  for (const listener of listeners) listener();
}

function resolveFrom(actor: PlatformActor): PlatformSessionState {
  // A session still mid-MFA must never render ordinary Control Centre content.
  const destination = resolveLoginDestination(actor.session_status);
  if (destination === "setup-mfa") return { state: "unauthenticated", destination: "/setup-mfa" };
  if (destination === "verify") return { state: "unauthenticated", destination: "/login" };
  return { state: "authenticated", actor };
}

function refresh(force: boolean): Promise<void> {
  if (inflight) return inflight;
  if (!force && current.state === "authenticated" && Date.now() - resolvedAt < REVALIDATE_AFTER_MS) {
    return Promise.resolve();
  }
  // An already-authenticated session keeps rendering while it revalidates.
  inflight = platformApi
    .get<PlatformActor>("/auth/me")
    .then((actor) => {
      resolvedAt = Date.now();
      publish(resolveFrom(actor));
    })
    .catch((cause) => {
      if (cause instanceof ApiError && (cause.status === 401 || cause.status === 403)) {
        publish({ state: "unauthenticated", destination: "/login" });
      } else if (current.state !== "authenticated") {
        // Could not determine the session (network/5xx): not "signed out" and
        // not "signed in" — surfaced as its own state with a retry.
        publish({ state: "unavailable" });
      }
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

/** Forget the resolved session (sign-out, or arriving at the login page). */
export function clearPlatformSession() {
  resolvedAt = 0;
  publish(RESOLVING);
}

export function resetPlatformSessionForTests() {
  inflight = null;
  resolvedAt = 0;
  current = RESOLVING;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function usePlatformSession(): PlatformSessionState & { retry: () => void } {
  // A previous visit's terminal non-authenticated outcome is history, not
  // news (never redirect to /login from a stale `unauthenticated` right after
  // signing in), and an authenticated result older than the TTL is no longer
  // trusted: both re-resolve before anything renders.
  useState(() => {
    const fresh = current.state === "authenticated" && Date.now() - resolvedAt < REVALIDATE_AFTER_MS;
    if (!fresh) current = RESOLVING;
  });
  const snapshot = useSyncExternalStore(subscribe, () => current, () => RESOLVING);
  useEffect(() => {
    void refresh(false);
  }, []);
  const retry = useCallback(() => {
    publish(RESOLVING);
    void refresh(true);
  }, []);
  return { ...snapshot, retry };
}
