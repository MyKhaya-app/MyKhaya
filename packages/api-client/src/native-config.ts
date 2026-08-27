/**
 * The single place a future native (Capacitor) shell's API origin is named.
 * See ADR 0008/0010: `api.mykhaya.app` (and its dev equivalent,
 * `api.dev.mykhaya.app`) is a direct-to-FastAPI origin that is never
 * proxied through the Next.js web app the way the browser's relative
 * `/api/v1` path is — a native client has no same-origin relationship with
 * the API to rely on, so it must be given an absolute base URL instead.
 *
 * This file does not attempt to auto-detect which environment a native
 * shell is running in — `NativeMyKhayaClient` has no reliable way to know
 * that on its own (there is no `NODE_ENV`/browser `location` to read
 * inside a bundled native app). The host app must pass the base URL it
 * wants explicitly (see `NativeMyKhayaClient`'s constructor); these
 * constants exist so that choice is made by picking one of two named,
 * centrally-defined values, not by copying a URL string into a new place
 * each time a native build needs one.
 */
export const NATIVE_API_ORIGINS = {
  development: "https://api.dev.mykhaya.app",
  production: "https://api.mykhaya.app",
} as const;

export type NativeApiEnvironment = keyof typeof NATIVE_API_ORIGINS;

/** `/api/v1` is FastAPI's own mount prefix (see apps/api/mykhaya/main.py) —
 * identical regardless of which origin reaches it, so this is appended the
 * same way for every native environment rather than repeated by callers. */
export function nativeApiBaseUrl(environment: NativeApiEnvironment): string {
  return `${NATIVE_API_ORIGINS[environment]}/api/v1`;
}
