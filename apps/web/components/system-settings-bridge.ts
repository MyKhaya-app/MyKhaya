import { registerPlugin } from "@capacitor/core";
import { isNativeShell } from "./native-runtime";

/**
 * TS-side contract for the native `SystemSettingsPlugin` (Swift source in
 * apps/ios-shell/native/plugin/SystemSettingsPlugin.swift, installed into
 * the generated ios/ project by scripts/install-widget-sources.sh — same
 * repo-local-plugin pattern as widget-bridge.ts/WidgetBridgePlugin.swift).
 * Opens the OS's own "MyKhaya notification settings" screen via Apple's
 * documented `UIApplication.openSettingsURLString`, which App Store review
 * guidelines require go straight to the app's own settings page rather than
 * the general Settings root.
 */
export interface SystemSettingsPlugin {
  /** Opens this app's page in the OS Settings app. */
  openAppSettings(): Promise<void>;
}

const SystemSettings = registerPlugin<SystemSettingsPlugin>("SystemSettings");

/**
 * Opens the device's MyKhaya settings screen. No-ops outside the native
 * shell. Falls back to the `app-settings:` URL-scheme trick (a top-level
 * navigation to a non-app-origin URL, which Capacitor's WKWebView delegate
 * hands to `UIApplication.shared.open(...)` — see
 * WebViewDelegationHandler.swift in the installed @capacitor/ios package)
 * only if the native plugin call itself fails, e.g. a web build shipped
 * ahead of a native rebuild that hasn't picked up SystemSettingsPlugin yet.
 * That fallback is a safety net, not the primary mechanism.
 */
export async function openAppSettings(): Promise<void> {
  if (!isNativeShell()) return;
  try {
    await SystemSettings.openAppSettings();
  } catch {
    try {
      window.location.href = "app-settings:";
    } catch {
      // Nothing more we can do — leave the user on Settings' own “This
      // device” copy pointing them to the OS Settings app manually.
    }
  }
}
