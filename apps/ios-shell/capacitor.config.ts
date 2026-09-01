import type { CapacitorConfig } from "@capacitor/cli";
import {
  allowedNavigationHosts,
  iosShellConfiguration,
  liveFrontendOrigin,
  resolveIosShellEnvironment,
} from "./src/config";

const environment = resolveIosShellEnvironment();
const shellConfiguration = iosShellConfiguration(environment);

console.log(`MyKhaya environment: ${shellConfiguration.environment}`);
console.log(`Frontend: ${shellConfiguration.frontend}`);
console.log(`API: ${shellConfiguration.api}`);

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
    // No wildcards. Only the live frontend's own origin is needed because
    // native bearer requests use that same origin's /api/v1 route.
    allowNavigation: allowedNavigationHosts(environment),
  },
  ios: {
    // "automatic" lets UIKit's own scroll-view content-inset adjustment
    // handle the status bar/notch/Dynamic Island natively — but that
    // silently prevents `env(safe-area-inset-*)` from ever resolving to a
    // real, nonzero value in the page's own CSS (a well-documented
    // Capacitor/WKWebView interaction, confirmed as the root cause of the
    // public/login pages rendering under the status bar on a real device).
    // "never" turns native inset adjustment off entirely, so 100% of
    // safe-area handling is left to apps/web's own CSS
    // (env(safe-area-inset-*) + viewport-fit=cover, audited in Phase 1) —
    // which is what this setting's comment always claimed was already
    // happening.
    contentInset: "never",
  },
};

export default config;
