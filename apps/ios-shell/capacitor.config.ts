import type { CapacitorConfig } from "@capacitor/cli";
import { allowedNavigationHosts, liveFrontendOrigin, resolveIosShellEnvironment } from "./src/config";

const environment = resolveIosShellEnvironment();

// Reused from the retired apps/mobile Expo scaffold (ADR 0011) rather than
// invented fresh — see docs/architecture/adr/0012-capacitor-ios-shell.md
// for why. Reverse-DNS under the mykhaya.app domain. Confirm with Anthony
// before this is ever registered against a real Apple Developer account.
const appId = "app.mykhaya.mobile";

const config: CapacitorConfig = {
  appId,
  appName: "MyKhaya",
  // Required by Capacitor even in "live remote frontend" mode — never
  // actually shown except as a brief loading flash before the WebView
  // navigates to server.url below, or as an offline fallback if the
  // network is unavailable at launch. See www/index.html.
  webDir: "www",
  server: {
    url: liveFrontendOrigin(environment),
    // HTTPS only — never cleartext, in either environment. Both
    // dev.mykhaya.app and mykhaya.app are real HTTPS origins (Caddy/NetBird
    // Proxy in dev, Caddy in production); there is no "local plain-HTTP"
    // iOS target.
    cleartext: false,
    // No wildcards. Only the live frontend's own origin and its paired
    // native API origin (see src/config.ts's own docstring for exactly
    // what is and is not included, and why).
    allowNavigation: allowedNavigationHosts(environment),
  },
  ios: {
    // Content extends under the status bar/notch/Dynamic Island by
    // default in Capacitor's iOS template; apps/web's own safe-area CSS
    // (env(safe-area-inset-*), audited in Phase 1) already accounts for
    // this, so no additional native inset handling is configured here yet.
    contentInset: "automatic",
  },
};

export default config;
