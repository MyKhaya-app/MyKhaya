import { api } from "@mykhaya/api-client";

// PushManager needs the VAPID public key as a raw Uint8Array, not the base64url
// string the API returns.
function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const normalised = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(normalised);
  return Uint8Array.from([...raw].map((char) => char.charCodeAt(0)));
}

export type SubscribeResult =
  | { ok: true }
  | { ok: false; reason: "unsupported" | "not-configured" | "permission-denied" | "error" };

// Requests notification permission (if needed) and registers a real push subscription
// with the backend. Must only be called from a user gesture (a button's onClick), never
// on mount — browsers require an explicit action before prompting for permission.
export async function subscribeToPush(): Promise<SubscribeResult> {
  if (typeof window === "undefined" || !("serviceWorker" in navigator) || !("PushManager" in window)) {
    return { ok: false, reason: "unsupported" };
  }
  try {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") return { ok: false, reason: "permission-denied" };

    const { configured, public_key } = await api.pushPublicKey();
    if (!configured || !public_key) return { ok: false, reason: "not-configured" };

    const registration = await navigator.serviceWorker.ready;
    const existing = await registration.pushManager.getSubscription();
    const subscription =
      existing ??
      (await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(public_key),
      }));
    const json = subscription.toJSON();
    if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) {
      return { ok: false, reason: "error" };
    }
    await api.registerPushSubscription({
      endpoint: json.endpoint,
      keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
      device_label: deviceLabel(),
      user_agent: navigator.userAgent.slice(0, 300),
    });
    return { ok: true };
  } catch (cause) {
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
