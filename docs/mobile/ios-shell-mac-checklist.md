# iOS Shell — Mac/Xcode Checklist (Phase 4)

This is the exact, minimal list of steps to turn `apps/ios-shell` (already
built and tested on Windows — see
[ADR 0012](../architecture/adr/0012-capacitor-ios-shell.md)) into a runnable
iOS app, **on a fresh Mac clone of this repository**. It assumes **no prior
Xcode experience** — every Xcode-specific term is explained inline. It does
not cover App Store submission or TestFlight. Native APNs and biometric
unlock are covered below.

**The native `apps/ios-shell/ios/` Xcode project is committed to this
repository** — a normal clone gets a complete, working project, the same
project every other Mac uses, not a freshly regenerated one. `npx cap add
ios` is a **recovery-only** action (see "If `ios/` is ever lost or
corrupted" near the end of this document) — do not run it on a checkout
that already has `ios/`; it is a no-op there by design (see Step 1 below),
but if `ios/` is ever deleted, regenerating it from scratch loses every
manual Xcode signing/capability change until it's redone.

## Fastest path: copy-paste scripts, no Xcode GUI required

If you just want to get MyKhaya running on the iOS Simulator with the
least ceremony, everything through "build and launch" is one script:

```sh
brew install node cocoapods   # if not already installed
bash apps/ios-shell/scripts/mac-bootstrap.sh
```

This installs deps, syncs the Capacitor config into the already-committed
`ios/` project, installs/updates the widget sources and the local
`MyKhayaWidgetCore` Swift Package, picks an already-installed iPhone
simulator (no new runtime download), builds, and launches the app — no
Xcode window ever needs to open. Read the step-by-step version below if you
want to understand what it's doing, want to run on a **physical device**
instead (needs the GUI signing step below), or something in the script
fails and you need to debug it manually.

If you changed anything under `apps/ios-shell/ios/`, `apps/ios-shell/native/`,
or `apps/ios-shell/scripts/` — a new widget, an entitlement change, a
plugin — commit those changes yourself with an ordinary `git add`/`git
commit` once you've verified them (see "Committing native project changes"
below); this is no longer a special one-time generated-artifact commit.

## Before you start (only needed if not using the script above)

- Install Xcode from the Mac App Store (free). Open it once and let it
  finish its own first-run setup — this can take a while.
- Install [Homebrew](https://brew.sh) if it isn't already there, then:
  ```sh
  brew install node cocoapods
  ```
  ("CocoaPods" is the iOS equivalent of `pnpm install` — it fetches native
  iOS library dependencies. You don't need to know more than that to use
  it.)
- Clone this repo onto the Mac and run `pnpm install` from the repo root,
  exactly as on Windows. `apps/ios-shell/ios/` already exists in the
  checkout — nothing needs generating.

## Step 1 — Sync the shell's config into the committed Xcode project

```sh
cd apps/ios-shell
npx cap sync ios
```

`ios/` is already there, committed to git — nothing needs generating.
`npx cap sync ios` copies the current `capacitor.config.ts`/`www/`/native
plugin dependency list into the project; it does **not** regenerate or
replace anything else, and is safe to run any time those change. It does
**not** need to be run when only `apps/web`'s UI changes — that's the whole
point of the live-frontend model (see ADR 0012). `npx cap add ios` — the
old one-time generation step — now detects the existing `ios/` and no-ops
(see `mac-bootstrap.sh`'s own check); it is **recovery-only**, see "If
`ios/` is ever lost or corrupted" near the end of this document.

## Step 2 — Open the project in Xcode

```sh
npx cap open ios
```

This launches Xcode with the generated project already open. Terms you'll
see:
- **Project navigator** (left sidebar): the file tree.
- **Scheme** (top toolbar, next to the Run button): which build
  configuration to run — pick `App` to run the app (it embeds and builds
  `MyKhayaWidgets` automatically; you don't need to select the widget
  scheme separately just to run the app).
- **Target**: `App` (the main app) and `MyKhayaWidgets` (the Home Screen
  widget extension — see [ios-widgets.md](ios-widgets.md)).

## Step 3 — Apple Developer account and signing

**This is the one step in this whole checklist that cannot be scripted —
it's an interactive Apple-account choice, not a mechanical action.** It is
only needed to run on a **physical iPhone**. Simulator builds (what
`mac-bootstrap.sh` does) need no signing at all — skip this step entirely
if the simulator is enough for this phase's verification.

You'll need an Apple Developer account (paid, $99/year, or the free tier
for simulator-only testing) signed into Xcode:
Xcode menu → Settings → Accounts → add your Apple ID.

Then, in the project navigator, click the top-level "App" project → the
"App" target → the "Signing & Capabilities" tab:
- Tick "Automatically manage signing."
- Choose your Team (your Apple Developer account) from the dropdown.
- **Bundle identifier**: this project is pre-configured with
  `app.mykhaya.mobile`, reused from the retired `apps/mobile` Expo app
  (see ADR 0012). **Confirm with Anthony before registering this
  identifier for real** in the Apple Developer portal — reusing the string
  in this repo's config is not the same as it having been registered.

Xcode will complain here if the bundle identifier isn't yet registered to
your team — follow its own "Register this identifier" prompt if so, only
after Anthony has confirmed the identifier choice.

## Step 4 — Run it

- Pick a simulator (iPhone 15, etc.) from the scheme dropdown next to the
  Run button, or plug in a real iPhone and pick it from the same dropdown
  (a physical device additionally needs "Trust This Computer" on the phone,
  and — for a paid developer account — the device registered in the portal,
  which Xcode does for you automatically when you pick a plugged-in phone
  as the run target).
- Press the Run (▶) button, or Cmd+R.
- The app should launch and load the live MyKhaya frontend
  (`https://dev.mykhaya.app` by default — see `MYKHAYA_IOS_ENV` in
  ADR 0012 for switching to production).

## Step 5 — Verify the security posture, not just that it loads

- Confirm the app refuses to navigate to a domain outside the configured
  `allowNavigation` list — e.g. tap something that would open an external
  link (a wishlist item's "View item"); it should NOT take over the main
  app view. (This is `openExternalUrl()` — see ADR 0012's "External URL
  handling" section.)
- Confirm sign-in works against the native bearer-auth endpoints
  (`/auth/mobile/login`, `/auth/mobile/child/login`) and not the
  browser/cookie ones.

## Step 6 — Verify persistent Keychain-backed login end to end

`apps/web/components/native-auth.ts` now selects
`apps/web/components/keychain-native-session-store.ts`
(`@aparajita/capacitor-secure-storage`-backed) whenever it's running inside
the native shell — this is only exercisable for real once the `ios/`
project exists, which is why it couldn't be verified end-to-end before
this checklist. On the Mac:

1. Sign in as an adult (or managed child, via Home Code/username/PIN).
2. Confirm Home loads.
3. Close the app normally (send to background / swipe away), then reopen —
   confirm still signed in.
4. Force-kill the app from the iOS app switcher, then reopen — confirm
   still signed in. This is the real test: `InMemoryNativeSessionStore`
   would have failed it (Phase 2/3 never wired up real persistence); the
   Keychain-backed store should not.
5. Sign out — confirm the app returns to a clean signed-out state and a
   subsequent relaunch does **not** silently resume the old session.

## Step 7 — Verify native biometric unlock

The native shell uses `@aparajita/capacitor-biometric-auth`, whose iOS
implementation invokes Apple's `LocalAuthentication` framework. The web
browser/PWA continues to use its existing WebAuthn passkey path and never
calls this native code.

1. On an iPhone Face ID simulator, use **Features → Face ID → Enrolled**.
2. Sign in normally in MyKhaya. On the first successful native login, choose
   **Enable Face ID**, then authenticate successfully. Choosing **Not now**
   records that decision and does not prompt again; enable it later under
   **Settings → Security**.
3. Force-terminate the app:
   `xcrun simctl terminate "$SIM_NAME" app.mykhaya.mobile`
4. Relaunch it:
   `xcrun simctl launch "$SIM_NAME" app.mykhaya.mobile`
5. Confirm only the neutral **Unlock MyKhaya** state is shown while the
   biometric prompt is active. Use **Features → Face ID → Matching Face**;
   Home should appear only after the successful unlock.
6. Repeat and choose **Cancel**. Confirm the saved session is retained, the
   fallback screen offers **Try again** and **Sign in with password**, and no
   authenticated content is visible.
7. Choose **Sign in with password**, then explicitly log out. Kill and relaunch
   again; Face ID must not restore the old session.
8. To test enrolment changes, disable/re-enrol Face ID in the simulator and
   relaunch. The app must not silently bypass the unlock; normal sign-in or
   re-enabling the setting is required.

The current secure-storage plugin supports `whenUnlockedThisDeviceOnly`,
which remains the session store's Keychain class. Version 8.0.0 does not
expose Apple's `SecAccessControl`/`biometryCurrentSet` attribute, so this
integration performs the LocalAuthentication challenge before reading and
validating the persisted session and fails closed on errors. A future native
Keychain bridge can add `biometryCurrentSet` without changing the shared
startup state machine.

If any of the above fails, check that Xcode's generated project actually
resolved the `@aparajita/capacitor-secure-storage` native pod/package (see
`npx cap sync ios`'s output) — a missing native dependency is the most
likely cause of a working JS-side adapter with no real persistence.
`apps/ios-shell/package.json` now explicitly declares
`@aparajita/capacitor-secure-storage`, `@aparajita/capacitor-biometric-auth`,
`@capacitor/app` and `@capacitor/browser` itself (previously only
`apps/web/package.json` did, which `cap sync ios` — run from
`apps/ios-shell` — never reads for plugin auto-discovery) — this was the
confirmed root cause of the first physical-device TestFlight build's
persistent-login and Quick Sign-In failures. Re-run `npx cap sync ios` (or
`npx cap add ios` if `ios/` doesn't exist yet on this Mac) after pulling
this change, and confirm the resulting `Podfile`/`Package.swift` now lists
all four plugins before building again.

## Step 8 — Home Screen widgets (Phase 5)

`mac-bootstrap.sh` runs `scripts/install-widget-sources.sh` automatically
(between Steps 1 and 2 above), which installs/updates the `MyKhayaWidgets`
extension target, its App Group, and its dependency on the local
`MyKhayaWidgetCore` Swift Package (`apps/ios-shell/native/WidgetCore/` —
the shared, unit-tested snapshot models and pure display logic; see
[docs/mobile/ios-widgets.md](ios-widgets.md)). All of this is idempotent —
re-running after a `git pull` picks up source changes without duplicating
targets, file references, or package dependencies. See
[docs/mobile/ios-widgets.md](ios-widgets.md) for the full architecture and
its own detailed manual verification checklist (widget gallery, event/
reminder updates, active Home switching, logout, deep links, light/dark,
TestFlight archive entitlement checks, and `swift test`/`xcodebuild test`
for the package's own test suite). Run that checklist after this one — it
assumes Steps 1–8 above already passed.

## If `ios/` is ever lost or corrupted

`apps/ios-shell/ios/` is committed to git specifically so this should never
be necessary — but if a Mac's local `ios/` is somehow deleted, corrupted, or
you deliberately want a from-scratch regenerate to compare against what's
committed:

1. **Back up first.** Copy the current `apps/ios-shell/ios/` directory
   somewhere safe before touching anything, even if it looks broken —
   don't discard evidence of what went wrong.
2. Move or delete the broken `ios/` (after the backup above), then run
   `npx cap add ios` from `apps/ios-shell` — this is the one situation
   where that command is the right thing to run.
3. Run `bash apps/ios-shell/scripts/mac-bootstrap.sh` (or its individual
   steps: `cap sync`, `ensure-apns-appdelegate.sh`,
   `ensure-storyboard-scene-delegate.sh`, the Face ID Info.plist patch,
   `install-widget-sources.sh`) to reapply every native customization this
   checklist and [ios-widgets.md](ios-widgets.md) describe.
4. **Compare the regenerated project against `git diff`/`git status`**
   before doing anything else with it. A clean regenerate that reproduces
   the same tracked files exactly is the expected, healthy outcome — a
   regenerate that differs from what's committed (a changed bundle ID,
   missing entitlement, different deployment target) means something about
   the committed project was manually changed in Xcode and never
   committed; reconcile that difference deliberately, don't overwrite it
   blindly in either direction.
5. **Never leave a regenerated `ios/` untracked again.** Once it matches
   (or you've deliberately reconciled it with) what's expected, commit it.
   This exact failure mode — a working native project existing only on one
   Mac's disk, never committed, silently lost — is what this whole
   "commit `ios/`" model exists to prevent; see the git history around the
   commit that introduced this section for what it looked like when it
   happened.
6. Signing/Team/provisioning-profile state lives in Xcode's own local
   account configuration, not in any committed file — you will need to
   re-select your Team under Signing & Capabilities after a regenerate
   (Step 3 above), the same as on a brand new Mac.

## Committing native project changes

Once `apps/ios-shell/ios/`, `apps/ios-shell/native/`, and
`apps/ios-shell/scripts/` are ordinary tracked files, committing a change
to any of them (a new widget, an entitlement change, a plugin update) is
an ordinary `git add`/`git commit` — review `git status`/`git diff` first,
same as anywhere else in this repo. `apps/ios-shell/scripts/mac-commit.sh`
is a safety-check helper for exactly this (see its own header comment) —
it checks for the things that must never be staged (`xcuserdata`,
`DerivedData`, absolute machine paths, obvious secret files) and for the
things that must be present (`project.pbxproj`, entitlements,
`AppDelegate.swift`, the widget target) before showing you the file list
to review; it never commits without your explicit confirmation.

## What is deliberately still open after this checklist

- **The Stripe billing navigation question** flagged in ADR 0012 — needs a
  deliberate decision (allow-list relaxation vs. external-browser +
  Universal Links), not a mechanical fix.
- Native passkeys, Associated Domains/Universal Links, App Store
  screenshots, TestFlight, and App Store submission are all out of scope
  here — later, separate phases. (APNs push delivery configuration is
  covered in `apps/ios-shell/README.md`'s "Native push / APNs" section;
  the `aps-environment=development` entitlement already present in the
  committed project is what Xcode's Automatic signing produces for a
  development-team-signed build — a production/Distribution entitlement
  value is not fabricated here and is Xcode/App Store Connect's own
  responsibility to manage at archive time, once that's actually attempted.)
