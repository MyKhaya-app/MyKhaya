/**
 * The single place a future native (Capacitor) shell's API origin is named.
 * The native shell loads the live frontend, so it uses that same origin's
 * `/api/v1` route. This keeps native and web traffic on the proven gateway
 * and avoids requiring a separate api.* service.
 *
 * This file does not attempt to auto-detect which environment a native
 * shell is running in — `NativeMyKhayaClient` has no reliable way to know
 * that on its own (there is no `NODE_ENV`/browser `location` to read
 * inside a bundled native app). The host app must pass the base URL it
 * wants explicitly (see `NativeMyKhayaClient`'s constructor); these
 * constants exist so that choice is made by picking one of two named,
 * centrally-defined values, not by copying a URL string into a new place
 * each time a native build needs one.
 */
export const NATIVE_API_ORIGINS = {
  development: "https://dev.mykhaya.app",
  production: "https://mykhaya.app",
} as const;

export type NativeApiEnvironment = keyof typeof NATIVE_API_ORIGINS;

/** `/api/v1` is FastAPI's own mount prefix (see apps/api/mykhaya/main.py) —
 * identical regardless of which origin reaches it, so this is appended the
 * same way for every native environment rather than repeated by callers. */
export function nativeApiBaseUrl(environment: NativeApiEnvironment): string {
  return `${NATIVE_API_ORIGINS[environment]}/api/v1`;
}

/**
 * A second, distinct resolution path from `nativeApiBaseUrl` above.
 *
 * The Capacitor iOS shell (`apps/ios-shell`) uses the "live frontend"
 * model: its WKWebView loads the real, deployed `apps/web` origin
 * (`dev.mykhaya.app` / `mykhaya.app`) rather than a bundled static app.
 * That means code running *inside* `apps/web` can read
 * `window.location.hostname` to learn which environment it is currently
 * being served from, and does not need a separate build-time env var the
 * way `apps/ios-shell/src/config.ts`'s `MYKHAYA_IOS_ENV` does (that value
 * controls which origin the shell points its WebView at in the first
 * place — a build/Xcode-scheme concern, not a runtime-JS one).
 */
const WEB_TO_NATIVE_ENVIRONMENT: Record<string, NativeApiEnvironment> = {
  "dev.mykhaya.app": "development",
  "mykhaya.app": "production",
};

export function nativeApiBaseUrlForWebHost(hostname: string): string {
  // TEMPORARY, Android Phase 2B local-testing-only branch: when the native
  // shell's WebView is pointed at a developer's local Docker Caddy stack
  // (reached via `adb reverse tcp:8089 tcp:8089`, see
  // apps/android-shell/README.md) rather than a real dev.mykhaya.app/
  // mykhaya.app deployment, `window.location.hostname` is "localhost" and
  // has no entry in WEB_TO_NATIVE_ENVIRONMENT. Route to that same local
  // origin's own /api/v1, consistent with this file's own "native traffic
  // stays same-origin" principle — never to a real dev.mykhaya.app/
  // mykhaya.app instance. Not intended to be committed; revert once local
  // testing is complete.
  if (hostname === "localhost") return "http://localhost:8089/api/v1";
  const environment = WEB_TO_NATIVE_ENVIRONMENT[hostname];
  if (!environment) {
    throw new Error(
      `No native API origin is configured for web host ${JSON.stringify(hostname)}.`,
    );
  }
  return nativeApiBaseUrl(environment);
}
