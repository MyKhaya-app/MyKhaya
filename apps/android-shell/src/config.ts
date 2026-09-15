/**
 * The single place the Android shell's target environment is decided. Kept
 * as plain, independently testable TS (not inlined into capacitor.config.ts)
 * so the actual decision logic — which live frontend origin to load, and
 * exactly which hosts the WebView is allowed to navigate to — can be unit
 * tested without Android Studio or a native build. Deliberately mirrors
 * apps/ios-shell/src/config.ts's shape; see
 * docs/architecture/adr/0014-capacitor-android-shell.md for why this is a
 * second thin shell around the same frontend, not a parallel implementation.
 *
 * "Live frontend" architecture (see docs/architecture/adr/0012-capacitor-ios-shell.md,
 * extended to Android by ADR 0014): this shell does NOT bundle a copy of the
 * MyKhaya web app. It points Capacitor's Android WebView at the real,
 * deployed apps/web origin — the same origin a Chrome user would visit — so
 * ordinary MyKhaya UI/feature deploys reach the Android app without a Play
 * Store update. Only native shell behaviour (this package, plus any future
 * native plugins) needs a new Android release.
 */

export type AndroidShellEnvironment = "development" | "production";

/** MYKHAYA_ANDROID_ENV picks which live frontend this build points at — set
 * by whoever runs `cap sync android`/builds the relevant Gradle variant.
 * Development is the safe pre-production default; production must be
 * selected explicitly so an unset release build cannot silently ship
 * against production. Mirrors apps/ios-shell/src/config.ts's
 * MYKHAYA_IOS_ENV exactly, one variable per shell rather than a single
 * cross-platform variable, so each shell's own build tooling stays
 * self-contained. */
export function resolveAndroidShellEnvironment(
  env: Record<string, string | undefined> = process.env,
): AndroidShellEnvironment {
  const value = env.MYKHAYA_ANDROID_ENV;
  if (value === "development") return "development";
  if (value === undefined) return "development";
  if (value === "production") return "production";
  throw new Error(
    `MYKHAYA_ANDROID_ENV must be "development" or "production" (got ${JSON.stringify(value)}).`,
  );
}

/** The live frontend origin this shell's WebView loads — the same
 * canonical URLs already used throughout the backend/Caddy configuration
 * and by apps/ios-shell/src/config.ts, not values invented here. */
export const LIVE_FRONTEND_ORIGINS: Record<AndroidShellEnvironment, string> = {
  development: "https://dev.mykhaya.app",
  production: "https://mykhaya.app",
};

export function nativeApiBaseUrl(environment: AndroidShellEnvironment): string {
  return `${LIVE_FRONTEND_ORIGINS[environment]}/api/v1`;
}

export function androidShellConfiguration(environment: AndroidShellEnvironment) {
  return {
    environment,
    frontend: LIVE_FRONTEND_ORIGINS[environment],
    api: nativeApiBaseUrl(environment),
  } as const;
}

/**
 * Hosts the WebView is permitted to navigate to at the top level, beyond
 * the live frontend origin itself. Deliberately short and explicit — no
 * wildcards, mirroring apps/ios-shell/src/config.ts's
 * allowedNavigationHosts() exactly. Everything else (Stripe Checkout,
 * external wishlist product links, support/legal links) is intentionally
 * NOT here — those must open via the external-browser helper
 * (apps/web/components/open-external-url.ts), never as a top-level
 * navigation of the authenticated WebView. See ADR 0012's Stripe finding,
 * which applies identically to this shell.
 */
export function allowedNavigationHosts(environment: AndroidShellEnvironment): string[] {
  return [new URL(LIVE_FRONTEND_ORIGINS[environment]).hostname];
}

export function liveFrontendOrigin(environment: AndroidShellEnvironment): string {
  return LIVE_FRONTEND_ORIGINS[environment];
}
