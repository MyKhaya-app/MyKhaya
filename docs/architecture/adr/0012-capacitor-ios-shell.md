# ADR 0012: Capacitor iOS Shell — Live Frontend, Not a Second App

**Status:** Accepted (Phase 3 of the native-client track; builds on [ADR 0010](./0010-mobile-bearer-session-tokens.md) and [ADR 0011](./0011-single-pwa-retire-mobile-app.md)).

## Decision

MyKhaya's first real iOS packaging is a thin Capacitor shell, `apps/ios-shell`, that loads the live, deployed `apps/web` frontend inside a WKWebView (`server.url` in `capacitor.config.ts`) rather than bundling a static copy of the app. Ordinary web/PWA feature work continues to happen exclusively in `apps/web` and reaches the shell automatically on next app launch, with **no new iOS release required**. The shell adds native iOS capabilities incrementally, on top of the same web app, not a parallel one.

This does not reopen ADR 0011: there is still exactly one frontend codebase. `apps/ios-shell` is a native wrapper/loader around it, the same relationship a browser has to a website, not a second implementation of MyKhaya's UI the way the retired `apps/mobile` Expo app was.

## Why "live frontend" and not a bundled static build

A bundled `webDir` build would need a new App Store release for every ordinary UI change — exactly the two-release-cadence problem ADR 0011 already rejected once, just moved from "two codebases" to "two deploy pipelines for one codebase." Loading the real origin means the shell's own release surface is limited to: the native shell version itself, its `allowNavigation` allow-list, and any native plugin it depends on — everything else ships the normal way.

`webDir: "www"` is still required by Capacitor even in this mode; `apps/ios-shell/www/index.html` is a minimal "Connecting to MyKhaya…" fallback, shown only briefly before `server.url` navigation completes, or if it fails outright (e.g. no network at launch). It is never the real UI.

## Package location and naming

`apps/ios-shell` (package name `@mykhaya/ios-shell`), not `apps/mobile` (retired by ADR 0011 — reusing that name/directory would misleadingly suggest a resurrected second frontend) and not `apps/native` (too generic once Android is a live possibility — this package is iOS-specific by name, matching what it actually contains today).

## Windows-first development

Editing `capacitor.config.ts` / `apps/ios-shell/src/config.ts` (which live origin a build points at, the navigation allow-list, app name/identifier) is plain TypeScript, fully testable from Windows (`pnpm --filter @mykhaya/ios-shell test`/`typecheck`). Only the steps that genuinely require CocoaPods/Xcode — generating the `ios/` Xcode project (`cap add ios`), syncing native config into it (`cap sync ios`), signing, and building — need the Mac. No `ios/` directory has been generated in this phase; see [the Mac handoff checklist](../../mobile/ios-shell-mac-checklist.md) for that one-time step.

## Configuration and navigation security

- `appId`: `app.mykhaya.mobile`, reused from the retired `apps/mobile` Expo app's last configuration (`git show` against its final commit) rather than inventing a competing identifier. **Needs Anthony's explicit confirmation before any real Apple Developer Program registration** — reuse here is a naming decision, not a claim that registration has happened.
- `appName`: "MyKhaya".
- Environment selection: `MYKHAYA_IOS_ENV` (`development` | `production`, default `production`) — a single named variable, following the same `MYKHAYA_`-prefixed convention as the backend, rather than a new ad hoc mechanism. This is a **build-time** concern (which origin a given Xcode scheme's build points at) — distinct from `nativeApiBaseUrlForWebHost()` in `packages/api-client`, which is a **runtime** concern (code already running inside the loaded web page deriving the matching native API origin from `window.location.hostname`, since the live-frontend model means the served origin already encodes dev-vs-prod).
- `server.url`: `https://dev.mykhaya.app` (development) / `https://mykhaya.app` (production) — MyKhaya's existing canonical frontend origins, not new ones invented for this shell.
- `server.cleartext`: always `false`. Both origins are real HTTPS deployments; there is no cleartext use case here.
- `server.allowNavigation`: an explicit, non-wildcard host list — `["dev.mykhaya.app", "api.dev.mykhaya.app"]` or `["mykhaya.app", "api.mykhaya.app"]`. Navigation to anything not on this list is blocked by Capacitor by default. This list must never grow to include a third-party domain "to fix" a broken navigation (see the Stripe finding below) — a regression test (`config.test.ts`) asserts neither list ever matches `/stripe/i`.

## Native runtime detection

`apps/web/components/native-runtime.ts` (`isNativeShell()`, `nativePlatform()`) wraps `Capacitor.isNativePlatform()`/`Capacitor.getPlatform()` behind SSR-safe guards, so shared frontend code has one canonical way to branch on browser/PWA vs. native shell instead of scattered `window.Capacitor` checks. Current consumers: the service-worker registration path and `openExternalUrl()`. Future consumers (not implemented this phase): native auth UI, native navigation, push, biometric unlock.

## Service worker separation

Inside the native shell, `ServiceWorkerRegister` (`apps/web/components/service-worker-register.tsx`) now skips both the `navigator.serviceWorker.register("/sw.js")` call and the foreground notification-click message listener — a future native push implementation (APNs, not this phase) and the web/native bridge will replace this path rather than run alongside it. The ordinary browser/PWA path is unchanged; both paths are covered by regression tests in `service-worker-register.test.tsx`.

## Native auth bootstrap

`apps/web/components/native-auth.ts` wires `packages/api-client`'s `NativeMyKhayaClient` (ADR 0010, extended in Phase 2) into a shared client/store pair, exposing `bootstrapNativeSession()`, `nativeLogin()`, `nativeChildLogin()`, `nativeLogout()`. No UI component ever holds the raw bearer token — it lives only inside `NativeSessionStore` and as one outgoing `Authorization` header per native request.

## Secure storage: deferred to Phase 4, by design

Phase 2 shipped only `InMemoryNativeSessionStore` — adequate for testing the auth flow logic, but not for real persistent login (a token that must survive app restart needs iOS Keychain, not process memory). Two maintained-looking Capacitor Keychain plugins were reviewed (`@aparajita/capacitor-secure-storage`, `capacitor-secure-storage-plugin`); neither's actual Keychain-accessibility-flag behaviour (`kSecAttrAccessibleWhenUnlockedThisDeviceOnly`-equivalent, no iCloud Keychain sync) could be verified from this sandbox. Per this phase's explicit instruction to fail safe rather than guess, no plugin was added. `native-auth.ts` is written against the `NativeSessionStore` interface, not a concrete store, so swapping in a real Keychain-backed adapter is a one-line change there once the plugin choice is verified on the Mac — see the Mac handoff checklist.

## Native navigation contract

`apps/web/components/primary-nav-destinations.ts` is the single source of truth for MyKhaya's primary destinations (currently: Home, Calendar, Family [adult-only], More — read from the actual `bottom-nav.tsx`, not assumed). It is deliberately **not** placed in `@mykhaya/shared-types`, since that package is generated from the backend's OpenAPI schema and would be overwritten by the next `make generate-client` run; navigation structure isn't an API concept. `bottom-nav.tsx` now consumes it. A genuinely new/removed/reordered destination is what would require a future native Swift tab bar release; anything else about a destination's own page stays an ordinary web deploy.

## Web/native bridge

`apps/web/components/native-bridge.ts` defines a small, closed `NativeBridgeEvent` union (navigation changed, unread count changed, auth state changed, request biometric unlock, open external URL, share) and one no-op dispatch stub — deliberately not a generic event bus. Nothing consumes these events yet; the contract exists so future native capability work (Phase 4+) has one agreed shape rather than each feature inventing its own message.

## External URL handling

`apps/web/components/open-external-url.ts` opens a URL via `@capacitor/browser`'s `Browser.open()` (an in-app SFSafariViewController-equivalent) inside the native shell, or `window.open(url, "_blank", "noopener,noreferrer")` in an ordinary browser tab — so an external link never takes over the authenticated main WebView. Applied to the two real household-facing external-link usages found by audit: a wishlist item's product link in both the owner view (`app/wish-lists/[id]/page.tsx`) and the guest share view (`app/wishlist/share/[token]/page.tsx`). (Two further matches in `app/control-centre/subscriptions/[id]/page.tsx` are Platform-Admin-only and out of scope for the household iOS shell.)

## Known finding, not fixed this phase: Stripe billing navigation

`apps/web/app/settings/billing/page.tsx` navigates the top-level window to Stripe's hosted Checkout/Billing-Portal domain via `window.location.href` (`startCheckout()`, `openPortal()`). Under this shell's navigation policy, Stripe's domain is deliberately **not** in `allowNavigation` (see the Stripe regression test above), so this navigation would currently be blocked. Fixing it properly is a genuine design question, not a config tweak: either accept a wildcard-adjacent relaxation of the allow-list for Stripe's domain, or route through `openExternalUrl()` — which raises how Stripe's `success_url`/`cancel_url` return-navigation gets the user back into the app, most likely requiring Universal Links, which are explicitly out of scope for this phase. **Flagged for a dedicated future decision; not implemented or worked around here.**

## Alternatives considered

- **Bundle a static build (`webDir` holds the real app).** Rejected: reintroduces the two-release-cadence problem this ADR exists to avoid.
- **Fold navigation destinations into `@mykhaya/shared-types`.** Rejected: that package is OpenAPI-generated and would silently lose hand-written content on the next codegen run.
- **Add a secure-storage plugin now, accepting some uncertainty.** Rejected: the task's own instruction, and this phase's general security posture, is to fail safe over guessing at Keychain-accessibility behaviour sight-unseen.

## Consequences

- No `ios/` Xcode project exists yet — generating it is exactly the kind of macOS-only step deferred to Phase 4 (see the Mac handoff checklist).
- Real Keychain-backed persistent login does not work yet; `InMemoryNativeSessionStore` means a native session does not currently survive app restart. The architecture is ready for the storage swap; the swap itself is Phase 4 work.
- APNs, Face ID, native passkeys, Associated Domains/Universal Links, and App Store submission remain unimplemented, as explicitly scoped.
