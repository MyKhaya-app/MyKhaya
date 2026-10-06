// The one shared vocabulary for asynchronous state that decides what the user
// may see (session, role, plan, entitlements, feature settings, ...).
//
//   UNKNOWN → RESOLVING → RESOLVED → RENDER
//
// Never model such state as a boolean/nullable whose *initial* value happens
// to mean "allowed" or "denied". `loading` is its own value: callers render a
// neutral, same-sized placeholder for it and only render permission-sensitive
// content from `ready`. Client-side gating is presentation only — the API
// remains the authorisation boundary.
export type Resolved<T> =
  | { state: "loading" }
  | { state: "ready"; value: T }
  | { state: "error"; error: unknown };

export const LOADING: Resolved<never> = { state: "loading" };

export function ready<T>(value: T): Resolved<T> {
  return { state: "ready", value };
}

export function failed(error: unknown): Resolved<never> {
  return { state: "error", error };
}

export function isReady<T>(resolved: Resolved<T>): resolved is { state: "ready"; value: T } {
  return resolved.state === "ready";
}
