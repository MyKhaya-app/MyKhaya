/**
 * The single place the iOS shell's target environment is decided. Kept as
 * plain, independently testable TS (not inlined into capacitor.config.ts)
 * so the actual decision logic — which live frontend origin to load, and
 * exactly which hosts the WebView is allowed to navigate to — can be unit
 * tested from Windows without Xcode or a native build.
 *
 * "Live frontend" architecture (see docs/architecture/adr/0012-capacitor-ios-shell.md):
 * this shell does NOT bundle a copy of the MyKhaya web app. It points
 * Capacitor's WKWebView at the real, deployed apps/web origin — the same
 * origin a Safari user would visit — so ordinary MyKhaya UI/feature
 * deploys reach the iOS app without an App Store update. Only native
 * shell behaviour (this package, plus native plugins) needs a new iOS
 * release.
 */

export type IosShellEnvironment = "development" | "production";

/** MYKHAYA_IOS_ENV picks which live frontend this build points at — set by
 * whoever runs `cap sync ios`/opens the Xcode scheme, analogous to how the
 * backend's MYKHAYA_ENVIRONMENT selects behaviour. Defaults to production
 * so an accidental unset variable can never point a real build at a dev
 * server. */
export function resolveIosShellEnvironment(
  env: Record<string, string | undefined> = process.env,
): IosShellEnvironment {
  const value = env.MYKHAYA_IOS_ENV;
  if (value === "development") return "development";
  if (value === undefined || value === "production") return "production";
  throw new Error(
    `MYKHAYA_IOS_ENV must be "development" or "production" (got ${JSON.stringify(value)}).`,
  );
}

/** The live frontend origin this shell's WebView loads — the same
 * canonical URLs already used throughout the backend/Caddy configuration
 * (docs/operations/dev-deployment.md, infrastructure/caddy/Caddyfile.production),
 * not a value invented here. */
export const LIVE_FRONTEND_ORIGINS: Record<IosShellEnvironment, string> = {
  development: "https://dev.mykhaya.app",
  production: "https://mykhaya.app",
};

/**
 * Hosts the WebView is permitted to navigate to at the top level, beyond
 * the live frontend origin itself. Deliberately short and explicit — no
 * wildcards. `api.*.mykhaya.app` is included because the live frontend's
 * own JS (packages/api-client's NativeMyKhayaClient) calls it directly
 * with an absolute URL (see ADR 0010); everything else (Stripe Checkout,
 * external wishlist product links, support/legal links) is intentionally
 * NOT here — those must open via the external-browser helper
 * (apps/web/components/open-external-url.ts), never as a top-level
 * navigation of the authenticated WebView. See ADR 0012 for the current,
 * explicitly-flagged exception (Stripe Checkout/Portal) this creates.
 */
export function allowedNavigationHosts(environment: IosShellEnvironment): string[] {
  return environment === "development"
    ? ["dev.mykhaya.app", "api.dev.mykhaya.app"]
    : ["mykhaya.app", "api.mykhaya.app"];
}

export function liveFrontendOrigin(environment: IosShellEnvironment): string {
  return LIVE_FRONTEND_ORIGINS[environment];
}
