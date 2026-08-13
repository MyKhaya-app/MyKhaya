import { api } from "@mykhaya/api-client";
import { isStandalone } from "./install-prompt";

// PushManager needs the VAPID public key as a raw Uint8Array, not the base64url
// string the API returns.
function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const normalised = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(normalised);
  return Uint8Array.from([...raw].map((char) => char.charCodeAt(0)));
}

export type SubscribeStage =
  | "checking-support"
  | "checking-permission"
  | "requesting-permission"
  | "fetching-public-key"
  | "waiting-for-service-worker"
  | "checking-existing-subscription"
  | "creating-push-subscription"
  | "registering-with-api"
  | "complete";

export type SubscribeResult =
  | { ok: true }
  | {
      ok: false;
      reason: "unsupported" | "not-configured" | "permission-denied" | "timeout" | "error";
      stage?: SubscribeStage;
    };

// Any single stage that can plausibly hang (a browser API promise that never settles,
// or a network request) gets this long before we give up and return an actionable
// failure. Chosen within the 10-15s range — long enough for a slow network, short
// enough that the UI never looks stuck.
const STAGE_TIMEOUT_MS = 12_000;

class StageTimeoutError extends Error {
  stage: SubscribeStage;
  constructor(stage: SubscribeStage, ms: number) {
    super(`Timed out after ${ms}ms waiting for stage "${stage}"`);
    this.stage = stage;
  }
}

// Races `promise` against a timeout. Note this does not — cannot — cancel the
// underlying browser operation if it never settles (there is no general way to abort
// navigator.serviceWorker.ready, for instance); it only stops *us* from waiting on it
// forever, so the UI can return to an actionable state instead of hanging.
function withTimeout<T>(promise: Promise<T>, stage: SubscribeStage): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new StageTimeoutError(stage, STAGE_TIMEOUT_MS)), STAGE_TIMEOUT_MS);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error: unknown) => {
        clearTimeout(timer);
        reject(error instanceof Error ? error : new Error(String(error)));
      },
    );
  });
}

function devLog(stage: SubscribeStage) {
  // Stage name only — never the subscription itself (endpoint/keys are sensitive
  // push credentials) and never gated behind anything that could leak into a
  // production console by accident beyond this explicit check.
  if (process.env.NODE_ENV !== "production") console.debug("[push] stage:", stage);
}

// Requests notification permission (if needed) and registers a real push subscription
// with the backend. Must only be called from a user gesture (a button's onClick), never
// on mount — browsers require an explicit action before prompting for permission.
//
// `onStage` fires on every stage transition so the caller can show progress and, on
// failure, know exactly which stage the flow got stuck at rather than a generic error.
export async function subscribeToPush(onStage?: (stage: SubscribeStage) => void): Promise<SubscribeResult> {
  const report = (stage: SubscribeStage) => {
    devLog(stage);
    onStage?.(stage);
  };

  report("checking-support");
  if (typeof window === "undefined" || !("serviceWorker" in navigator) || !("PushManager" in window)) {
    return { ok: false, reason: "unsupported" };
  }

  try {
    report("checking-permission");
    if (Notification.permission === "denied") {
      return { ok: false, reason: "permission-denied" };
    }

    report("requesting-permission");
    const permission = await Notification.requestPermission();
    if (permission !== "granted") return { ok: false, reason: "permission-denied" };

    report("fetching-public-key");
    const { configured, public_key } = await withTimeout(api.pushPublicKey(), "fetching-public-key");
    if (!configured || !public_key) return { ok: false, reason: "not-configured" };

    report("waiting-for-service-worker");
    const registration = await withTimeout(navigator.serviceWorker.ready, "waiting-for-service-worker");

    report("checking-existing-subscription");
    const existing = await withTimeout(
      registration.pushManager.getSubscription(),
      "checking-existing-subscription",
    );

    let subscription = existing;
    if (!subscription) {
      report("creating-push-subscription");
      subscription = await withTimeout(
        registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(public_key),
        }),
        "creating-push-subscription",
      );
    }

    const json = subscription.toJSON();
    if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) {
      return { ok: false, reason: "error", stage: "creating-push-subscription" };
    }

    report("registering-with-api");
    await withTimeout(
      api.registerPushSubscription({
        endpoint: json.endpoint,
        keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
        device_label: deviceLabel(),
        user_agent: navigator.userAgent.slice(0, 300),
      }),
      "registering-with-api",
    );

    report("complete");
    return { ok: true };
  } catch (cause) {
    if (cause instanceof StageTimeoutError) {
      console.error(`subscribeToPush timed out at stage "${cause.stage}"`);
      return { ok: false, reason: "timeout", stage: cause.stage };
    }
    // Diagnostic only — never log the subscription itself (endpoint/keys are
    // sensitive push credentials), just what kind of failure occurred.
    console.error("subscribeToPush failed:", cause instanceof Error ? cause.message : cause);
    return { ok: false, reason: "error" };
  }
}

function deviceLabel(): string {
  const ua = navigator.userAgent;
  if (/iphone/i.test(ua)) return "iPhone";
  if (/ipad/i.test(ua)) return "iPad";
  if (/android/i.test(ua)) return "Android device";
  return "This device";
}

export type PushDiagnostics = {
  notificationApiAvailable: boolean;
  permission: NotificationPermission | "unavailable";
  standalone: boolean;
  hasController: boolean;
  registrationScope: string | null;
  registrationActive: boolean;
  registrationInstalling: boolean;
  registrationWaiting: boolean;
  pushManagerAvailable: boolean;
};

// Non-sensitive environment snapshot for diagnosing exactly why push registration is
// stuck — never includes a subscription endpoint or key. Safe to log or display.
export async function diagnosePushEnvironment(): Promise<PushDiagnostics> {
  const supportsServiceWorker = typeof window !== "undefined" && "serviceWorker" in navigator;
  const registration = supportsServiceWorker
    ? await navigator.serviceWorker.getRegistration().catch(() => undefined)
    : undefined;
  return {
    notificationApiAvailable: typeof window !== "undefined" && "Notification" in window,
    permission: typeof window !== "undefined" && "Notification" in window ? Notification.permission : "unavailable",
    standalone: isStandalone(),
    hasController: supportsServiceWorker && Boolean(navigator.serviceWorker.controller),
    registrationScope: registration?.scope ?? null,
    registrationActive: Boolean(registration?.active),
    registrationInstalling: Boolean(registration?.installing),
    registrationWaiting: Boolean(registration?.waiting),
    pushManagerAvailable: typeof window !== "undefined" && "PushManager" in window,
  };
}
