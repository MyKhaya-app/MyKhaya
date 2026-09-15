import type { CapacitorConfig } from "@capacitor/cli";
import {
  allowedNavigationHosts,
  androidShellConfiguration,
  liveFrontendOrigin,
  resolveAndroidShellEnvironment,
} from "./src/config";

const environment = resolveAndroidShellEnvironment();
const shellConfiguration = androidShellConfiguration(environment);

console.log(`MyKhaya environment: ${shellConfiguration.environment}`);
console.log(`Frontend: ${shellConfiguration.frontend}`);
console.log(`API: ${shellConfiguration.api}`);

// Reused from the retired apps/mobile Expo scaffold's own
// `android: { package: "app.mykhaya.mobile" }` (git history, see
// docs/architecture/adr/0014-capacitor-android-shell.md) — the same
// identifier ADR 0012 already reused for iOS's appId, rather than
// inventing a competing Android-only namespace. Confirm with Anthony
// before this is ever registered against a real Google Play Console
// account.
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
    // dev.mykhaya.app and mykhaya.app are real HTTPS origins; there is no
    // "local plain-HTTP" Android target.
    cleartext: false,
    // No wildcards. Only the live frontend's own origin is needed because
    // native bearer requests use that same origin's /api/v1 route. Mirrors
    // apps/ios-shell/capacitor.config.ts's allowNavigation exactly.
    allowNavigation: allowedNavigationHosts(environment),
  },
};

export default config;
