# iOS DEV and PROD apps

MyKhaya ships **two separate iOS apps** from one repository and one Xcode
project (`apps/ios-shell/ios/App/App.xcodeproj`). They have different
identities, so both can be installed on the same iPhone at once, and each
only ever talks to its own backend.

| | DEV | PROD |
| --- | --- | --- |
| Home screen name | MyKhaya-Dev | MyKhaya |
| App bundle ID | `app.mykhaya.mobile` | `app.mykhaya.mobile.prod` |
| Widget bundle ID | `app.mykhaya.mobile.widgets` | `app.mykhaya.mobile.prod.widgets` |
| App Group (app and widget) | `group.app.mykhaya.mobile` | `group.app.mykhaya.mobile.prod` |
| Widget deep-link URL scheme | `mykhaya://` | `mykhaya-prod://` |
| Live frontend and API | `https://dev.mykhaya.app` (`/api/v1`) | `https://mykhaya.app` (`/api/v1`) |
| Xcode scheme (app) | `MyKhaya-Dev` | `MyKhaya-Prod` |
| Xcode scheme (widget only) | `MyKhayaWidgets-Dev` | `MyKhayaWidgets-Prod` |
| Run configuration | `Debug-Dev` | `Debug-Prod` |
| Archive configuration | `Release-Dev` | `Release-Prod` |
| APNs environment | Debug: development, Release: production | Debug: development, Release: production |
| Team / signing | `M86392YDLQ`, automatic | `M86392YDLQ`, automatic |
| Associated domains | none (not used) | none (not used) |

Keychain sign-ins, widget data and push registrations stay separate
automatically: each lives under its own bundle ID or App Group.

## Where each value lives

Every environment value is version-controlled, and set in exactly one place:

- `apps/ios-shell/ios/App/Config/Environment-Dev.xcconfig` and
  `Environment-Prod.xcconfig`: the `MYKHAYA_*` settings (bundle ID, App
  Group, URL scheme, server host, display name), team and signing style.
- `Debug-Dev`, `Release-Dev`, `Debug-Prod`, `Release-Prod.xcconfig`: include
  one environment file and set the APNs environment. They are the base
  configurations of the project's four build configurations, which both
  targets inherit.

Everything else refers to those settings, never to literal values:

- Targets: `PRODUCT_BUNDLE_IDENTIFIER = $(MYKHAYA_APP_BUNDLE_ID)`
  (widget: `$(MYKHAYA_APP_BUNDLE_ID).widgets`).
- Entitlements (`AppDebug`, `AppRelease`, `native/widgets/MyKhayaWidgets`):
  App Group `$(MYKHAYA_APP_GROUP)`.
- `ios/App/App/Info.plist`: URL scheme `$(MYKHAYA_URL_SCHEME)`, display name,
  and `MyKhayaEnvironment` / `MyKhayaServerHost` / `MyKhayaURLScheme` /
  `MyKhayaAppGroup` for the native code.
- `native/widgets/Info.plist`: the same keys for the widget (no server host).

Shared native code (`native/WidgetCore`, `native/widgets`, `native/plugin`)
reads the environment from the Info.plist through `MyKhayaEnvironment` and
must never hardcode either environment's identifiers.

## How each app picks its backend

`MainViewController` overrides Capacitor's `instanceDescriptor()` and loads
`https://$(MYKHAYA_SERVER_HOST)` from the build configuration, with that host
as the only allowed navigation host. It does **not** use the `server.url` in
`capacitor.config.json`: `npx cap sync` rewrites that one file for a single
environment at a time, so it cannot describe two apps. If the build
configuration has no valid server host, the app stops at launch rather than
guess (a guess could connect DEV to PROD). The web app then derives its API
origin from the page it was loaded from (`nativeApiBaseUrlForWebHost`), so
DEV only ever calls `dev.mykhaya.app` and PROD only `mykhaya.app`.

## Widget taps

A widget builds `<scheme>://open?path=/...` with its own environment's scheme.
Each app registers only its own scheme and `WidgetBridgePlugin` ignores any
other, so a DEV widget cannot open or drive the PROD app, or the reverse.

## Building and running from Xcode

1. On the Mac: `cd apps/ios-shell && bash scripts/mac-bootstrap.sh` (or, if
   the project is already set up, `bash scripts/install-widget-sources.sh`).
2. `npx cap open ios`.
3. In Xcode's toolbar scheme menu pick **MyKhaya-Dev** or **MyKhaya-Prod**.
   (Do not pick a `MyKhayaWidgets-*` scheme to run the app; those build the
   widget alone.)
4. Pick a simulator or your iPhone, then **Product > Run** (⌘R). This builds
   `Debug-Dev` or `Debug-Prod`, including the matching widget.
5. To ship: keep the same scheme, choose **Any iOS Device**, then
   **Product > Archive**. This builds `Release-Dev` or `Release-Prod`. Upload
   from the Organizer to the matching App Store Connect app (MyKhaya-Dev or
   MyKhaya).

Both apps can be installed side by side. The build log shows
"MyKhaya iOS environment OK: App Debug-Dev -> app.mykhaya.mobile" (or the
PROD equivalent) from the validation build phase.

From Terminal:

```sh
cd apps/ios-shell
xcodebuild -project ios/App/App.xcodeproj -scheme MyKhaya-Dev  -configuration Debug-Dev  -sdk iphonesimulator build
xcodebuild -project ios/App/App.xcodeproj -scheme MyKhaya-Prod -configuration Debug-Prod -sdk iphonesimulator build
xcodebuild -project ios/App/App.xcodeproj -scheme MyKhaya-Prod -configuration Release-Prod -archivePath build/MyKhaya-Prod.xcarchive archive
```

`MYKHAYA_IOS_ENV=production bash scripts/mac-bootstrap.sh` builds and launches
PROD in the simulator instead of DEV; it changes nothing else.

## Checks

- `pnpm --filter @mykhaya/ios-shell test` (any OS, also in CI):
  `src/ios-environments.test.ts` checks every committed file above against the
  matrix, that no shared native code or setup script hardcodes an identifier,
  and that the build-phase validator accepts each configuration and rejects
  crossed DEV/PROD values.
- `sh scripts/validate-ios-environments.sh` (Mac): expands every
  configuration of both targets with `xcodebuild -showBuildSettings` and
  checks the real values and the schemes. `mac-bootstrap.sh` runs it.
- The **Validate MyKhaya environment** build phase on both targets fails any
  build whose settings mix environments (for example a bundle ID typed into
  Xcode's Signing pane).
- `swift test` in `native/WidgetCore`: environment parsing and widget-tap
  routing for both apps.

## Changing signing or identifiers

Change the value in `Environment-Dev.xcconfig` or `Environment-Prod.xcconfig`,
then update `IOS_APP_ENVIRONMENTS` in `apps/ios-shell/src/config.ts` and the
matrix in `scripts/validate-ios-environments.sh` (the tests fail until all
three agree). Avoid setting signing in Xcode's Signing & Capabilities pane:
it writes a target-level override that the tests reject. Changing a bundle ID
or App Group creates a different app: existing installs would not update and
would lose their widget data.

## One-time migration on a Mac that had DEV set up by hand

Before this change, DEV was produced by editing PROD values in Xcode. Those
edits are uncommitted local changes to `project.pbxproj`, the entitlements
and `Info.plist`, and they block `git pull`. Discard them first (they are
replaced by the configurations above):

```sh
cd apps/ios-shell
git status --short ios native
git stash push -m "manual DEV Xcode edits" -- ios   # or: git checkout -- ios
cd ../.. && git pull --ff-only && cd apps/ios-shell
bash scripts/install-widget-sources.sh
sh scripts/validate-ios-environments.sh
```

Then open Xcode and pick a scheme as above. Both installed apps keep their
data: their bundle IDs and App Groups are unchanged.
