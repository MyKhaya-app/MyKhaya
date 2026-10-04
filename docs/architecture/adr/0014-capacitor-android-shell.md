# ADR 0014: Capacitor Android Shell — Same Architecture as iOS

**Status:** Accepted (Phase 1 of the Android native-client track; builds on [ADR 0010](./0010-mobile-bearer-session-tokens.md), [ADR 0011](./0011-single-pwa-retire-mobile-app.md), and [ADR 0012](./0012-capacitor-ios-shell.md)).

## Decision

MyKhaya's Android packaging follows the exact same model ADR 0012 already
established for iOS: a thin Capacitor shell, `apps/android-shell`, that
loads the live, deployed `apps/web` frontend inside a Capacitor Android
WebView (`server.url` in `capacitor.config.ts`) rather than bundling a
static copy of the app. Ordinary web/PWA feature work continues to happen
exclusively in `apps/web` and reaches the Android shell automatically on
next app launch, with no new Play Store release required. The shell adds
native Android capabilities incrementally, on top of the same web app, not
a parallel one.

This does not reopen ADR 0011 or ADR 0012: there is still exactly one
frontend codebase. `apps/android-shell` is a native wrapper/loader around
it, the same relationship `apps/ios-shell` already has, and the same
relationship a browser has to a website.

> One frontend codebase, multiple thin native shells.

## Why a second shell, not a shared native package

`apps/ios-shell` was deliberately named to end in "-shell" rather than
`apps/native` specifically because Android was already a live possibility
(ADR 0012's own package-naming rationale). Platform shells are kept
separate directories, each with its own `capacitor.config.ts`, environment
resolver, and (eventually) native project, because their native build
tooling, signing, and platform-specific plugin implementations genuinely
differ — but every architectural decision this ADR makes is a direct copy
of ADR 0012's decision for the same reason, not a new one. Where this ADR
and ADR 0012 overlap, ADR 0012's own reasoning is the reasoning here too;
this document does not repeat it beyond stating the parallel.

## Package location and naming

`apps/android-shell` (package name `@mykhaya/android-shell`), matching
`apps/ios-shell`'s pattern. Not merged into `apps/ios-shell` — the
repository deliberately keeps platform shells separate (their native
project structures, build tooling, and signing are entirely different).

## Configuration and navigation security

- `appId` / Android `applicationId`: `app.mykhaya.mobile` — reused, not
  invented. The retired `apps/mobile` Expo app's last `app.config.ts`
  (before ADR 0011 retired it) already configured
  `android: { package: "app.mykhaya.mobile" }`, the same identifier ADR
  0012 separately reused for iOS's `appId`. This ADR simply confirms that
  existing precedent rather than choosing a new one. **Needs Anthony's
  explicit confirmation before any real Google Play Console registration**
  — reuse here is a naming decision, not a claim that registration has
  happened, exactly the same posture ADR 0012 stated for iOS.
- `appName`: "MyKhaya".
- Environment selection: `MYKHAYA_ANDROID_ENV` (`development` | `production`,
  default `development`) — one variable per shell, mirroring
  `MYKHAYA_IOS_ENV` exactly rather than introducing a single cross-platform
  variable that would couple the two shells' build tooling together.
- `server.url`: `https://dev.mykhaya.app` (development) /
  `https://mykhaya.app` (production) — the same canonical frontend origins
  `apps/ios-shell` already uses, not new ones invented for this shell.
- `server.cleartext`: always `false`.
- `server.allowNavigation`: an explicit, non-wildcard single-host list per
  environment (just the live frontend's own hostname), mirroring
  `apps/ios-shell`'s policy and its Stripe-domain regression test
  (`src/config.test.ts`) exactly.
- `AndroidManifest.xml`: `android:usesCleartextTraffic="false"` (explicit,
  belt-and-suspenders alongside Capacitor's own bridge-level check),
  `android:allowBackup="false"` (no application data included in Android
  Auto Backup — there is no equivalent-to-iOS-Keychain secure storage wired
  up on this platform yet, and no legitimate reason for this shell's data
  to be backed up until there is), and only the `INTERNET` permission.

## Native runtime detection — no change required

`apps/web/components/native-runtime.ts` (`isNativeShell()`,
`nativePlatform()`) already types `NativePlatform` as
`"ios" | "android" | "web"` and wraps `Capacitor.isNativePlatform()` /
`Capacitor.getPlatform()` directly — both are Capacitor-core APIs that
report the actual running platform generically, with no iOS-specific
assumption baked in. Adding the Android shell causes `nativePlatform()` to
correctly report `"android"` with zero changes to this file. This was
verified statically (see the completion report); it could not be verified
by launching the built app, since no Android SDK/JDK is available in this
environment — the shared frontend has never before actually run inside a
non-iOS native shell.

## Explicit non-decisions

This ADR does not introduce, and this phase does not implement:

- A separate Android UI or layout. The shared responsive frontend and its
  existing `.native-shell` / `.native-shell-app` CSS model (which already
  fires for any Capacitor native platform, not iOS specifically) is used
  unmodified.
- Separate Android business logic. All auth, entitlement, and domain logic
  remains exclusively in `apps/web`/`apps/api`.
- A bundled frontend. Exactly as with iOS, `webDir: "www"` holds only a
  brief "Connecting to MyKhaya…" fallback, never the real UI.
- Firebase Cloud Messaging (FCM) / push notifications. No Firebase
  dependency, no `google-services.json` (the android shell's `.gitignore`
  explicitly excludes it), no notification channels or permissions.
- Biometric unlock / `BiometricPrompt` configuration.
- Android App Links / `assetlinks.json`.
- Google Play Billing.
- Android home-screen widgets.

Each of the above is real, scoped, later-phase work — not omitted by
oversight, and not blocked by anything decided here. They belong to later
implementation phases identified in the prior Android-readiness audit.

## What was and wasn't verified in this phase

- `npx cap add android` and `npx cap sync android` both completed
  successfully (Node-level operations, no Java required) and produced a
  standard, structurally valid Capacitor Android Gradle project, with the
  generated `capacitor.config.json` correctly reflecting the development
  origin, `cleartext: false`, and the single-host `allowNavigation` list.
- `pnpm --filter @mykhaya/android-shell typecheck` and `test` both pass.
- The Gradle build itself (`./gradlew assembleDebug`) could not be run in
  this environment — no JDK/Android SDK is installed, confirmed by
  Gradle's own `JAVA_HOME is not set and no 'java' command could be found`
  error. This is an environment-tooling gap, not a defect discovered in the
  generated project; the project's Gradle file references (module paths,
  the `@capacitor/android` package location under pnpm's store) were
  inspected and are structurally correct.
- No emulator or physical Android device was available to actually launch
  the app, inspect the shared UI rendering, or confirm `nativePlatform()`
  returns `"android"` at runtime. This remains open — see the completion
  report's "deferred to Phase 1 verification" list.

## Alternatives considered

- **Place Android inside `apps/ios-shell`, parameterized by platform.**
  Rejected: the two platforms' native project structures, build tooling,
  and signing processes are different enough that a shared directory would
  mostly just be two projects awkwardly interleaved, not simplified —
  exactly why `apps/ios-shell` was already named to imply "one of possibly
  several shells" rather than "the native shell."
- **Invent a new Android-specific application ID rather than reusing
  `app.mykhaya.mobile`.** Rejected: the retired Expo app already used this
  exact identifier for Android, and ADR 0012 already reused it for iOS —
  reusing the same identifier a second time preserves one consistent
  MyKhaya product namespace rather than fragmenting it.
- **Bundle a static build.** Rejected for the same reason ADR 0012 rejected
  it for iOS: it reintroduces a two-release-cadence problem for ordinary UI
  changes.

## Consequences

- `apps/android-shell/android/` (a committed Gradle project, mirroring
  `apps/ios-shell/ios/`'s own committed-not-gitignored precedent) now
  exists in the repository.
- Building, running, and verifying this shell on an actual device/emulator
  requires the Android SDK and a JDK — genuinely new tooling this
  repository has not previously needed, unlike iOS's Xcode/macOS
  requirement which was already accounted for.
- FCM, biometrics, App Links, billing, and widgets remain entirely separate,
  future work, tracked by the phased plan the prior Android-readiness audit
  produced — this ADR only establishes the shell itself.
