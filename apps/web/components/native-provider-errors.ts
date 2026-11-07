import { ApiError } from "@mykhaya/api-client";

/** Where a native provider sign-in or link attempt failed. */
export type NativeProviderStage = "start" | "provider" | "exchange" | "follow_up";

/** Safe, non-sensitive failure categories for native Apple/Google sign-in.
 * These are what diagnostics record; none of them carries a token, nonce,
 * transaction id, email address or provider subject. */
export type NativeProviderFailureCategory =
  | "cancelled"
  | "plugin_unavailable"
  | "provider_unavailable_on_device"
  | "provider_failed"
  | "attempt_expired"
  | "network"
  | "server_rejected"
  | "unexpected";

export type NativeProviderFailure = {
  category: NativeProviderFailureCategory;
  /** Text for the person, or null when nothing should be shown (cancellation). */
  userMessage: string | null;
  /** Plugin rejection code or HTTP status: diagnostic only, never secret. */
  code: string | null;
  nativeCode: number | null;
  status: number | null;
};

type ProviderName = "apple" | "google";

const LOCAL_ATTEMPT_EXPIRED = "The native sign-in attempt is no longer available.";

function providerLabel(provider: ProviderName): string {
  return provider === "apple" ? "Apple" : "Google";
}

function stringField(value: unknown, key: string): string | null {
  if (typeof value !== "object" || value === null || !(key in value)) return null;
  const field = (value as Record<string, unknown>)[key];
  return typeof field === "string" ? field : null;
}

function nativeCodeOf(value: unknown): number | null {
  if (typeof value !== "object" || value === null || !("data" in value)) return null;
  const data = (value as { data?: unknown }).data;
  if (typeof data !== "object" || data === null) return null;
  const code = (data as Record<string, unknown>).native_code;
  return typeof code === "number" ? code : null;
}

/** Classify a failure from the native provider flow into a category and a
 * user-safe message. ApiError messages are already user-safe server text and
 * are preserved, matching the existing behaviour. */
export function classifyNativeProviderFailure(
  cause: unknown,
  provider: ProviderName,
  stage: NativeProviderStage,
  action: "sign-in" | "link" = "sign-in",
): NativeProviderFailure {
  const label = providerLabel(provider);
  const generic = action === "link"
    ? `Could not connect ${label}. Please try again.`
    : `${label} sign-in could not be completed. Please try again or use your password.`;
  const base = { code: null, nativeCode: null, status: null } as const;

  if (cause instanceof ApiError) {
    return { ...base, category: "server_rejected", userMessage: cause.message, status: cause.status, code: cause.code ?? null };
  }

  const code = stringField(cause, "code");
  const nativeCode = nativeCodeOf(cause);
  const message = cause instanceof Error ? cause.message : stringField(cause, "message") ?? "";

  if (code === "cancelled" || (stage === "provider" && /cancel/i.test(message))) {
    return { ...base, category: "cancelled", userMessage: null, code: code ?? "cancelled", nativeCode };
  }
  // Capacitor's own codes when the installed app has no such native plugin
  // (an app build that predates it) — the live web frontend can be newer than
  // the binary.
  if (code === "UNIMPLEMENTED" || code === "UNAVAILABLE") {
    return {
      ...base,
      category: "plugin_unavailable",
      userMessage: `${label} sign-in needs the latest version of the MyKhaya app. Please update the app, or sign in with your password.`,
      code,
    };
  }
  if (code === "apple_unknown" || code === "apple_not_interactive") {
    return {
      ...base,
      category: "provider_unavailable_on_device",
      userMessage: `${label} sign-in isn't available on this device right now. Check you're signed in to your Apple Account in Settings, or sign in with your password.`,
      code,
      nativeCode,
    };
  }
  if (code && stage === "provider") {
    return { ...base, category: "provider_failed", userMessage: generic, code, nativeCode };
  }
  if (message === LOCAL_ATTEMPT_EXPIRED) {
    return { ...base, category: "attempt_expired", userMessage: "This sign-in attempt has expired. Please try again." };
  }
  // fetch() rejects with a TypeError ("Load failed" in WKWebView) when the
  // request never reached the API.
  if (cause instanceof TypeError && stage !== "provider") {
    return { ...base, category: "network", userMessage: "We couldn't reach MyKhaya. Check your connection and try again." };
  }
  return { ...base, category: "unexpected", userMessage: generic, code };
}

/** A fresh per-attempt correlation id. Sent as X-Request-ID on the attempt's
 * API calls, so the API's request log lines and auth diagnostics for one
 * attempt share it with the device console entry. Random; carries no data. */
export function newNativeAuthCorrelationId(): string {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return `nauth-${Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("")}`;
}

/** Console-only diagnostic (visible in the Xcode / Android Studio device
 * log). Records category, stage and codes only. */
export function logNativeProviderFailure(
  provider: ProviderName,
  stage: NativeProviderStage,
  correlationId: string,
  failure: NativeProviderFailure,
): void {
  const fields = {
    provider,
    stage,
    category: failure.category,
    code: failure.code,
    native_code: failure.nativeCode,
    status: failure.status,
    correlation_id: correlationId,
  };
  if (failure.category === "cancelled") console.info("[NATIVE AUTH] provider attempt cancelled", fields);
  else console.warn("[NATIVE AUTH] provider attempt failed", fields);
}
