import { nativePlatform } from "./native-runtime";
import { requestNativePermissionOnly, nativePushPermission } from "./native-push";
import { openAppSettings } from "./system-settings-bridge";

/**
 * Common cross-platform notification-permission model. Shared UI/state
 * (notification-permission-prompt.tsx, use-notification-permission.ts, the
 * Settings "This device" section) works only with this type and the
 * NotificationPermissionAdapter interface below — never with a platform
 * check or a platform-specific status shape. Adding Android later means
 * adding one adapter that returns these same five states; nothing else in
 * the shared layer changes.
 */
export type NotificationPermissionStatus =
  | "unsupported"
  | "not_requested"
  | "granted"
  | "denied"
  | "restricted";

export interface NotificationPermissionAdapter {
  /** Current status, read from a live platform check (never cached/inferred). */
  getPermissionStatus(): Promise<NotificationPermissionStatus>;
  /** Requests OS permission if not already decided; does not re-prompt if
   *  already denied (the OS won't show it again, so this returns "denied"
   *  immediately instead). Registration/device-token concerns are handled
   *  behind this call, not surfaced in its return value. */
  requestPermission(): Promise<NotificationPermissionStatus>;
  /** Opens the OS's notification settings screen for this app. */
  openSystemNotificationSettings(): Promise<void>;
  /** Re-checks status — semantically the same call as getPermissionStatus()
   *  for adapters with no caching (iOS today), kept distinct so a future
   *  adapter that does cache has an explicit "force a fresh read" hook for
   *  resume/return-from-settings callers. */
  refreshPermissionStatus(): Promise<NotificationPermissionStatus>;
}

function mapNativePermission(receive: string | undefined): NotificationPermissionStatus {
  switch (receive) {
    case "granted":
      return "granted";
    case "denied":
      return "denied";
    case "prompt":
    case "prompt-with-rationale":
      return "not_requested";
    default:
      return "unsupported";
  }
}

/**
 * Shared by both native platforms — nativePushPermission()/
 * requestNativePermissionOnly() (native-push.ts) and openAppSettings()
 * (system-settings-bridge.ts) are already platform-generic themselves (each
 * dispatches to whichever native implementation Capacitor picks for the
 * running platform), so iOS and Android need no separate adapter bodies
 * here — only the platform-specific native code underneath differs.
 *
 * This also already covers Android's version-dependent permission model
 * without any extra branching: on API 33+ POST_NOTIFICATIONS is a real
 * runtime permission that behaves exactly like iOS's (prompt once, "denied"
 * afterwards means the OS won't show it again — requestNativePermissionOnly()
 * already encodes that "don't re-prompt once denied" rule generically); on
 * API <33 there is no such runtime permission at all, and the Capacitor
 * plugin itself reports "granted" without ever prompting — this adapter
 * just reflects whatever the plugin says, on either OS version.
 */
const nativePushAdapter: NotificationPermissionAdapter = {
  async getPermissionStatus() {
    const permission = await nativePushPermission();
    return permission ? mapNativePermission(permission.receive) : "unsupported";
  },
  async requestPermission() {
    const result = await requestNativePermissionOnly();
    return result;
  },
  async openSystemNotificationSettings() {
    await openAppSettings();
  },
  async refreshPermissionStatus() {
    const permission = await nativePushPermission();
    return permission ? mapNativePermission(permission.receive) : "unsupported";
  },
};

const unsupportedAdapter: NotificationPermissionAdapter = {
  async getPermissionStatus() {
    return "unsupported";
  },
  async requestPermission() {
    return "unsupported";
  },
  async openSystemNotificationSettings() {},
  async refreshPermissionStatus() {
    return "unsupported";
  },
};

/**
 * Selects the platform adapter. This is the *only* place in the shared
 * notification-permission layer allowed to branch on platform — every
 * caller (the hook, the prompt, Settings) works only against the
 * NotificationPermissionAdapter interface after this point.
 *
 * Phase 5: both native platforms share nativePushAdapter (see its own doc
 * comment for why one implementation covers both) — a genuinely
 * Android-specific adapter would only be needed if some future Android
 * permission concern couldn't be expressed through the same
 * getPermissionStatus/requestPermission/openSystemNotificationSettings
 * shape, which is not the case today.
 */
export function getNotificationPermissionAdapter(): NotificationPermissionAdapter {
  const platform = nativePlatform();
  if (platform === "ios" || platform === "android") return nativePushAdapter;
  return unsupportedAdapter;
}
