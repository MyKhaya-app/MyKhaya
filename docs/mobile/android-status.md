# Android Shell — Status & Handover

Android development is **paused, not abandoned**. This document is the single
place to read before resuming it — it records what's actually done, what's
implemented but unverified live, what's deferred, the exact resume point, and
the implementation decisions already made so they aren't re-litigated.

**Resume Android work at Phase 5B: real Firebase/FCM runtime validation.**
See "Resume point" below.

## Completed (implemented and covered by unit/integration tests)

- **Phase 1 — Android Capacitor shell** (`apps/android-shell`, package id
  `app.mykhaya.mobile`). Live-frontend model: the WebView loads the real
  deployed `apps/web` origin (`dev.mykhaya.app` / `mykhaya.app`), never a
  bundled copy — see
  [ADR 0014](../architecture/adr/0014-capacitor-android-shell.md).
- **Phase 2 / 2B — native authentication/session lifecycle.** Bearer-token
  sessions via `NativeMyKhayaClient`, persisted through
  `@aparajita/capacitor-secure-storage` (Android Keystore-backed), mirroring
  the iOS Keychain-backed store.
- **Phase 3 — Android biometric Quick Sign-In**, via
  `@aparajita/capacitor-biometric-auth`, same shared UI/preference model as
  iOS Face ID/Touch ID.
- **Android back handling** — `native-back-button.ts`, `dismissal-stack.ts`,
  `native-history-depth.ts` (Capacitor `App` back-button integration +
  SPA-aware dismissal/history handling).
- **Phase 4 — native lifecycle re-lock.** `native-app-lock.ts` wired into
  `auth-provider.tsx`'s resume-lock effect; 5-minute background threshold
  (`BIOMETRIC_LOCK_TIMEOUT_MS`); reuses the existing
  `bootstrapNativeSession()` biometric-gate-then-verify pipeline for both
  cold launch and resume — no second session model.
- **Phase 5 — FCM implementation (code-complete).**
  - Backend: `send_fcm()` alongside `send_apns()`/`send_push()` in
    `mykhaya/notifications/push.py` (FCM HTTP v1 API via `httpx` + a
    service-account JWT built with `authlib` — no `firebase-admin`
    dependency, consistent with the existing hand-rolled-provider style).
  - `worker._send_native_push()` — the single seam dispatching APNs vs FCM
    by `NativePushDevice.platform`.
  - `engine.py`'s device query widened from iOS-only to `ios`/`android`.
  - Three Android notification channels (`general` / `reminders` /
    `calendar_family`), created in `MainActivity.onCreate()`
    (`NotificationChannels.java`) and mapped from `notification_type` by
    `fcm_channel_for_notification_type()` — see
    [notification-engine.md](../architecture/notification-engine.md#android-notification-channels).
  - Frontend: `native-push.ts`'s five iOS-only guards widened to
    `isSupportedNativePushPlatform()`; `notification-permission.ts`'s
    adapter selector returns the same `nativePushAdapter` for both
    platforms; `system-settings-bridge.ts`'s `SystemSettings` plugin has a
    real Android implementation (`SystemSettingsPlugin.java`, an
    `ACTION_APP_NOTIFICATION_SETTINGS` intent) alongside the iOS one.
  - PCC: `/push/test` reports `platform` per device; the Push page renders
    a per-device provider breakdown (`iOS · APNs` / `Android · FCM` /
    `Web Push`); About page shows Android/FCM labels instead of hardcoded
    iOS/APNs text.
  - Full unit/integration test coverage: `test_native_push_fcm.py`,
    `test_native_push_worker.py` (backend), plus Android cases added to
    `native-push.test.ts`, `notification-permission.test.ts`,
    `system-settings-bridge.test.ts`, `app/about/page.test.tsx`,
    `app/control-centre/push/page.test.tsx` (frontend). All pass; APNs and
    Web Push tests are unmodified and still pass.

## Implemented but still requiring live validation

None of the following have been exercised on a real device/emulator or
against a real Firebase project — only unit/integration-tested:

- **Real Firebase-backed FCM end-to-end delivery** — blocked on a real
  Firebase project; see "Resume point" below.
- **Android notification permission flow on-device** (first-run prompt →
  OS dialog → granted/denied/permanently-denied → Settings deep link).
- **Notification channels on-device** — that `general`/`reminders`/
  `calendar_family` actually appear correctly in Android Settings and that
  a real FCM message lands in the right one.
- **Foreground/background/terminated push delivery.**
- **Notification-tap routing** to the correct in-app MyKhaya route.
- **Phase 4's >5-minute live app-lock smoke test** — the resume-lock state
  machine is covered by integration tests with mocked timers/lifecycle
  events, but has never been run on a real device across a real >5-minute
  background period.
- **Predictive-back gesture validation** — `native-back-button.ts` is unit
  tested against a mocked Capacitor `App` listener, not against Android's
  real predictive-back animation/gesture on-device.

## Not started / intentionally deferred

- **Phase 5B — real Firebase/FCM runtime validation** (this document's
  resume point).
- Android App Links.
- Google Play Billing.
- Android home-screen widgets.
- Google Play Console release work.
- Signing/release pipeline (only the auto-generated debug keystore has
  ever been used; no release keystore exists).

## Known implementation decisions (do not re-litigate on resume)

- Android uses the shared `apps/web` frontend — no separate Android UI, no
  separate business logic. The shell is a thin Capacitor native wrapper.
- Application id: `app.mykhaya.mobile` (reused from the retired `apps/mobile`
  Expo scaffold, same identifier family as iOS's appId — see ADR 0014).
- Development/production origins follow the existing MyKhaya environment
  model (`dev.mykhaya.app` / `mykhaya.app`), selected via `MYKHAYA_ANDROID_ENV`
  at build/sync time — no localhost branch exists in `apps/android-shell/src/config.ts`
  or `packages/api-client/src/native-config.ts` (any localhost value seen
  during live-device testing sessions is a deliberate, temporary, hand-edit
  of the generated `capacitor.config.json` — never a permanent code path —
  and must always be reverted afterward).
- Native authentication uses bearer-token sessions (`NativeMyKhayaClient`),
  not cookies.
- Secure storage uses `@aparajita/capacitor-secure-storage`
  (Keystore-backed), the same package/pattern as iOS's Keychain store.
- Biometrics use `@aparajita/capacitor-biometric-auth` — the same plugin and
  preference model as iOS Face ID/Touch ID.
- Android Back is handled through Capacitor's `App` plugin integration plus
  SPA history/dismissal-stack handling, not a native back-stack rewrite.
- App re-lock threshold is 5 minutes (`BIOMETRIC_LOCK_TIMEOUT_MS`).
- Android push uses FCM; iOS uses APNs; browser/PWA uses Web Push (VAPID).
  Backend provider dispatch is centralized in one function
  (`worker._send_native_push()`) keyed on `NativePushDevice.platform` — no
  caller elsewhere branches on platform.
- No Firebase secrets are committed anywhere in this repository (see audit
  below) — FCM server credentials are three plain env-var-sourced settings
  values (`fcm_project_id`/`fcm_client_email`/`fcm_private_key`), never a
  service-account JSON file; the Android client's `google-services.json` is
  gitignored and has never existed in this repo.
- One MyKhaya entitlement model remains the intended billing architecture —
  Android does not get its own parallel entitlement/billing system when
  Play Billing work eventually starts.

## Resume point: Phase 5B — real Firebase/FCM runtime validation

**Tooling already present on this development machine** (discovered during
this pause, worth recording so it isn't re-discovered from scratch):
Android SDK at `%LOCALAPPDATA%\Android\Sdk` (platforms `android-34` and
`android-36`, build-tools, platform-tools, emulator), two AVDs already
created (`mykhaya_test` = API 34, `mykhaya_test36` = API 36), and JDK 17/21
(Eclipse Temurin) under `Program Files\Eclipse Adoptium`. **No Firebase or
gcloud CLI is installed, and no Firebase project, `google-services.json`, or
service-account key exists anywhere on this machine** — that is the actual
and only blocker to resuming, not missing build tooling.

First actions on resume:

1. Create (or reuse) a Firebase project and register an Android app with
   package id `app.mykhaya.mobile`, in the Firebase console.
2. Download that app's `google-services.json` into
   `apps/android-shell/android/app/google-services.json` — **local only**,
   never commit it (already gitignored, see "Secrets" below).
3. Generate a service-account key for the same Firebase project (Project
   Settings → Service Accounts → Generate new private key) and set the
   three backend env vars from it — `MYKHAYA_FCM_PROJECT_ID`,
   `MYKHAYA_FCM_CLIENT_EMAIL`, `MYKHAYA_FCM_PRIVATE_KEY` — plus
   `MYKHAYA_FCM_DELIVERY_CONFIGURED=true` — **local only** (e.g. `.env`,
   already gitignored), never the JSON file itself.
4. `cd apps/android-shell && npx cap sync android`, then build/run on both
   `mykhaya_test` (API 34) and `mykhaya_test36` (API 36).
5. Verify real FCM token registration end-to-end: OS permission prompt →
   token obtained → `NativePushDevice` row created (platform=android) →
   PCC identifies it as Android/FCM → a real test push from PCC's
   `/push/test` is delivered foreground, background, and terminated → a tap
   opens the correct in-app route.
6. Confirm the three notification channels appear correctly in Android
   Settings and that each notification type lands in the expected one (see
   the channel table in
   [notification-engine.md](../architecture/notification-engine.md#android-notification-channels)).
7. While there: also complete the two still-outstanding Phase 4 items above
   (the real >5-minute app-lock smoke test and predictive-back gesture
   validation) — same device session, no separate setup.

## Secrets / credentials audit (this pause)

- Searched the full working tree (tracked and untracked) for
  `google-services.json`, `*-firebase-adminsdk-*.json`, PEM/private-key
  material, and any FCM-related value in `.env*.example` files — **none
  found**. The two instances of the literal string `BEGIN PRIVATE KEY` in
  tracked files are a test fixture placeholder
  (`tests/test_native_push.py`) and a documentation placeholder
  (`apps/ios-shell/README.md`); neither is real key material.
- `apps/android-shell/android/app/.gitignore` already excludes
  `google-services.json`; root `.gitignore` already excludes
  `firebase-service-account*.json` / `*-firebase-adminsdk-*.json` (added in
  Phase 5, defensively, even though the backend never stores that file).
- `apps/android-shell/android/local.properties` (machine-specific SDK path)
  and the auto-generated `~/.android/debug.keystore` are both outside/
  excluded from source control, as expected — neither is a secret, both are
  ordinary per-machine Android tooling state.
- No release keystore exists anywhere in the repo or gitignore patterns for
  one — signing/release work has not started.

## Local cleanup performed during this pause

`apps/android-shell/android/app/build/`, `android/build/`, and
`android/.gradle/` (all gitignored Gradle build output, ~40MB) were deleted
— purely disposable, regenerated by the next build. One of them contained a
stale generated `capacitor.config.json` pointing at `http://localhost:8089`,
left over from an earlier live-device testing session's temporary
Docker-bridge setup; it was never tracked by git and could not have been
committed, but removing it avoids a future session mistaking stale build
output for current configuration. No source file changes were needed —
`apps/android-shell/src/config.ts` and
`packages/api-client/src/native-config.ts` (the two files a temporary
localhost test setup would touch) were already back to their permanent,
localhost-free state.
