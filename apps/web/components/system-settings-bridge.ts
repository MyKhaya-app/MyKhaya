import { registerPlugin } from "@capacitor/core";
import { isNativeShell, nativePlatform } from "./native-runtime";

/**
 * TS-side contract for the native `SystemSettingsPlugin` — one interface,
 * two native implementations under the same Capacitor plugin name, so this
 * file needs no platform branching for the call itself:
 * - iOS: apps/ios-shell/native/plugin/SystemSettingsPlugin.swift, installed
 *   into the generated ios/ project by scripts/install-widget-sources.sh
 *   (same repo-local-plugin pattern as widget-bridge.ts/WidgetBridgePlugin.swift).
 *   Opens Apple's documented `UIApplication.openSettingsURLString`.
 * - Android: apps/android-shell/android/app/src/main/java/app/mykhaya/mobile/SystemSettingsPlugin.java,
 *   registered directly in MainActivity.java (no separate install step —
 *   the android-shell source tree isn't Mac-generated the way ios/ is).
 *   Opens Settings.ACTION_APP_NOTIFICATION_SETTINGS (or the general
 *   app-details screen on API <26).
 */
export interface SystemSettingsPlugin {
  /** Opens this app's page in the OS Settings app. */
  openAppSettings(): Promise<void>;
}

const SystemSettings = registerPlugin<SystemSettingsPlugin>("SystemSettings");

/**
 * Opens the device's MyKhaya settings screen. No-ops outside the native
 * shell. On iOS only, falls back to the `app-settings:` URL-scheme trick (a
 * top-level navigation to a non-app-origin URL, which Capacitor's WKWebView
 * delegate hands to `UIApplication.shared.open(...)` — see
 * WebViewDelegationHandler.swift in the installed @capacitor/ios package)
 * if the native plugin call itself fails, e.g. a web build shipped ahead of
 * a native rebuild that hasn't picked up SystemSettingsPlugin yet. That
 * fallback is a safety net, not the primary mechanism, and has no Android
 * equivalent (there is no comparable WebView URL-scheme behaviour on
 * Android to fall back to) — a failed plugin call there simply leaves the
 * user on Settings' own "This device" copy pointing them to the OS Settings
 * app manually.
 */
export async function openAppSettings(): Promise<void> {
  if (!isNativeShell()) return;
  try {
    await SystemSettings.openAppSettings();
  } catch {
    if (nativePlatform() === "ios") {
      try {
        window.location.href = "app-settings:";
      } catch {
        // Nothing more we can do.
      }
    }
  }
}
