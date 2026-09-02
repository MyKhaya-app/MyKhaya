import { Capacitor } from "@capacitor/core";
import { isPlatformControlCentreHost } from "./application-host";

export { isPlatformControlCentreHost } from "./application-host";

// Single canonical place to ask "am I running inside the Capacitor native
// iOS shell, or a normal browser/PWA tab?" Every future native-only
// behaviour (auth bootstrap, service-worker skip, native navigation,
// external-link handling, biometric unlock) should branch on these
// functions instead of touching `window.Capacitor`/`Capacitor` directly.

export type NativePlatform = "ios" | "android" | "web";

export function isNativeShell(): boolean {
  if (typeof window === "undefined") return false;
  return Capacitor.isNativePlatform();
}

export function nativePlatform(): NativePlatform {
  if (typeof window === "undefined") return "web";
  const platform = Capacitor.getPlatform();
  return platform === "ios" || platform === "android" ? platform : "web";
}

/** The admin hostname is a separate application surface even though Next's
 * middleware rewrites it to /control-centre internally. Keep consumer auth,
 * AppShell, and native bearer startup out of that surface. */
export function isPlatformControlCentre(): boolean {
  if (typeof window === "undefined") return false;
  return isPlatformControlCentreHost(window.location.hostname);
}
