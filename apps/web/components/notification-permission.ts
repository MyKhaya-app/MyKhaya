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

function mapIosPermission(receive: string | undefined): NotificationPermissionStatus {
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

const iosAdapter: NotificationPermissionAdapter = {
  async getPermissionStatus() {
    const permission = await nativePushPermission();
    return permission ? mapIosPermission(permission.receive) : "unsupported";
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
    return permission ? mapIosPermission(permission.receive) : "unsupported";
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
 * Android: add `androidNotificationPermissionAdapter` implementing the same
 * interface (its requestPermission()/openSystemNotificationSettings() will
 * use the Android-equivalent APIs — an Intent to
 * Settings.ACTION_APP_NOTIFICATION_SETTINGS, etc.) and return it here for
 * `nativePlatform() === "android"`. No other file needs to change.
 */
export function getNotificationPermissionAdapter(): NotificationPermissionAdapter {
  if (nativePlatform() === "ios") return iosAdapter;
  return unsupportedAdapter;
}
