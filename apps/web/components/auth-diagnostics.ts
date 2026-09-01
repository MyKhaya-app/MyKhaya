import { ApiError } from "@mykhaya/api-client";

// Shared by components/app-shell.tsx (session bootstrap) and the login
// pages (sign-in attempts) — one ring buffer of recent auth events per app
// boot, so a failure on either can be correlated with what happened around
// it. Never records a token, password, or any other credential/secret —
// only event names and small non-sensitive fields (status codes, booleans,
// pathnames). See recordLoginFailureDiagnostic below for the specific
// categorisation this task added: distinguishing invalid credentials from
// a CORS/network/server-configuration failure, which previously all
// collapsed into the same generic "We couldn't sign you in" UI message
// with no way to tell them apart from the console/localStorage record.

const AUTH_DIAGNOSTICS_KEY = "mykhaya.auth-diagnostics";
const AUTH_BOOT_ID =
  typeof window === "undefined"
    ? "server"
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;

export function recordAuthDiagnostic(event: string, fields: Record<string, unknown> = {}): void {
  if (typeof window === "undefined") return;
  const entry = {
    event,
    bootId: AUTH_BOOT_ID,
    origin: window.location.origin,
    pathname: window.location.pathname,
    standalone:
      window.matchMedia("(display-mode: standalone)").matches ||
      ("standalone" in navigator && Boolean(navigator.standalone)),
    at: new Date().toISOString(),
    ...fields,
  };
  console.info("[AUTH_DIAG]", entry);
  try {
    const stored = window.localStorage.getItem(AUTH_DIAGNOSTICS_KEY);
    const previous: unknown = stored ? JSON.parse(stored) : [];
    const entries: unknown[] = Array.isArray(previous) ? (previous as unknown[]).slice(-49) : [];
    window.localStorage.setItem(AUTH_DIAGNOSTICS_KEY, JSON.stringify([...entries, entry]));
  } catch {
    // Diagnostics must never affect authentication startup.
  }
}

/**
 * Classifies a login (or child login) failure into a small, named set of
 * causes and records it via recordAuthDiagnostic — never the user-facing
 * message, which stays deliberately generic ("We couldn't sign you in.
 * Please try again.") so it never leaks which part of the stack failed to
 * a potential attacker. This is the development/operator-facing signal:
 *
 * - invalid_credentials: the server understood the request and rejected it
 *   (a genuine 401/403/422 from the auth endpoint itself)
 * - server_unavailable: the server responded, but with a 5xx
 * - api_configuration_error: a bug in this client's own request — a 4xx
 *   that isn't the credential-rejection shape (e.g. malformed body,
 *   missing field) or a CORS-style 403 from the origin-allowlist
 *   middleware (mykhaya.main's security_and_limits) — this exact category
 *   is what silently broke native iOS login: the origin/preflight was
 *   rejected before the credentials were ever checked.
 * - network_or_cors_error: fetch() itself threw — no HTTP response was
 *   ever received. This is indistinguishable, from the browser's fetch()
 *   API alone, between "no network", "DNS failure", and "CORS preflight
 *   blocked the request" — the exact three causes this task asked to be
 *   able to tell apart in the console during development. A CORS block is
 *   overwhelmingly the likely cause when this fires *only* for the native
 *   shell's direct-to-API requests and never for the browser's
 *   same-origin `/api/v1` ones.
 */
export function recordLoginFailureDiagnostic(context: string, cause: unknown): void {
  if (cause instanceof ApiError) {
    const category =
      cause.status === 401 || cause.status === 403 || cause.status === 422
        ? "invalid_credentials"
        : cause.status >= 500
          ? "server_unavailable"
          : "api_configuration_error";
    recordAuthDiagnostic("LOGIN_FAILED", { context, category, status: cause.status });
    return;
  }
  // No ApiError means fetch() itself rejected — parseApiResponse (see
  // packages/api-client/src/errors.ts) was never reached, so there is no
  // status code to report. See this function's docstring above for why
  // this bucket is the one to suspect first for a CORS/preflight failure.
  recordAuthDiagnostic("LOGIN_FAILED", {
    context,
    category: "network_or_cors_error",
    message: cause instanceof Error ? cause.name : "unknown",
  });
}
