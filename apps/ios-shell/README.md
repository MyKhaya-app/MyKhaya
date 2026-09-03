# @mykhaya/ios-shell

Capacitor native iOS shell for MyKhaya. This package does **not** contain a
second copy of the MyKhaya frontend — it configures a native WKWebView that
loads the real, deployed `apps/web` origin ("live frontend" model). See
[ADR 0012](../../docs/architecture/adr/0012-capacitor-ios-shell.md) for the
full architecture decision, and [ADR 0011](../../docs/architecture/adr/0011-single-pwa-retire-mobile-app.md)
for why this is a thin shell and not a resurrection of the retired
`apps/mobile` Expo app.

## What lives here vs. what doesn't

- **Here:** `capacitor.config.ts` (which live frontend origin to load, and
  the explicit `allowNavigation` allow-list), a minimal `www/index.html`
  fallback page, the native `ios/` Xcode project (**committed to git** —
  see below), `native/` (repo-managed Swift sources, including the
  `MyKhayaWidgetCore` local Swift Package), and the Mac setup/recovery
  scripts under `scripts/`.
- **Not here:** any MyKhaya UI. Ordinary web/PWA feature work happens in
  `apps/web` exactly as before and reaches this shell automatically on next
  app launch, with no new iOS release, because the shell always loads the
  live origin.

## The native `ios/` project is committed — this is not a build artifact

Unlike a typical Capacitor project (where `ios/` is often gitignored and
regenerated per-machine), **this repository commits `apps/ios-shell/ios/`**
so a fresh Mac clone gets a complete, working, already-signed-once project —
the exact one every other Mac uses — rather than a bare, unsigned
regeneration missing every manual Xcode capability/entitlement change. A
working native iOS project existing only on one Mac's local disk, never
committed, is a real failure mode this repository has hit before — see
[docs/mobile/ios-shell-mac-checklist.md](../../docs/mobile/ios-shell-mac-checklist.md)'s
"If `ios/` is ever lost or corrupted" section for what to do if it ever
happens again, and treat `npx cap add ios` as a recovery-only command, not
routine setup — see "Commands that require macOS + Xcode" below.

xcuserdata, DerivedData, build output, and machine-specific IDE state are
still gitignored (`apps/ios-shell/ios/.gitignore`) — only the project
structure, source, and configuration needed to reconstruct a working build
are tracked.

## Windows-friendly commands

These all run on Windows (or Linux) with no Xcode/macOS required:

```sh
pnpm install                                   # from the repo root
pnpm --filter @mykhaya/ios-shell typecheck     # tsc --noEmit
pnpm --filter @mykhaya/ios-shell test          # vitest — config.ts's logic
```

Editing `capacitor.config.ts` or `src/config.ts` (which live frontend origin
a build points at, the `allowNavigation` list, the app name/identifier) is
plain TypeScript — fully editable and testable from Windows.

## Commands that require macOS + Xcode

Everything below needs Xcode, which only runs on macOS. `ios/` is already
committed to this repo, so a fresh Mac checkout does **not** need to
generate it — see
[the Mac handoff checklist](../../docs/mobile/ios-shell-mac-checklist.md)
for the exact steps.

```sh
npx cap sync ios        # copies capacitor.config.ts + www/ into ios/ after any change to either
npx cap open ios        # opens Xcode
npx cap add ios         # RECOVERY-ONLY — no-ops if ios/ already exists;
                         # only run this if ios/ is genuinely lost/corrupted,
                         # after backing it up first (see the checklist's
                         # "If ios/ is ever lost or corrupted" section)
```

`cap sync ios` needs re-running (on the Mac) only when `capacitor.config.ts`,
`www/`, or a native plugin dependency changes — never for an ordinary
`apps/web` UI change, which the live shell picks up on its own.

## Environment selection

`MYKHAYA_IOS_ENV` (`development` | `production`, default `development`)
selects which live frontend origin a build points at — see `src/config.ts`.
Production archives must set `MYKHAYA_IOS_ENV=production` explicitly. The
native API uses the same frontend origin's `/api/v1` route in both environments.
There is no separate `.env` file for this package; it is a single named
variable, set when running `cap sync`/opening the relevant Xcode scheme, the
same MYKHAYA_-prefixed convention used throughout the backend.

## Home Screen widgets (Next Event, Calendar, To-do)

Repository-managed Swift sources for MyKhaya's WidgetKit widgets live in
`apps/ios-shell/native/`, including the `MyKhayaWidgetCore` local Swift
Package (`native/WidgetCore/`) — the shared, XCTest-covered snapshot models
and pure calendar/event/to-do display logic, imported by both the `App` and
`MyKhayaWidgets` Xcode targets. `scripts/install-widget-sources.sh`
(chained from `mac-bootstrap.sh`) installs the widget sources into the
committed `ios/` project, creates/updates the `MyKhayaWidgets` extension
target, and links the `MyKhayaWidgetCore` package into both targets —
idempotently, safe to re-run after any `git pull`. Full architecture, data
model, security model, and manual verification checklist: see
[docs/mobile/ios-widgets.md](../../docs/mobile/ios-widgets.md).

## Native push / APNs

The native shell uses `@capacitor/push-notifications`; it does not use the
service-worker/VAPID Web Push path. The API worker requires these backend-only
secrets for real iOS delivery:

```text
MYKHAYA_APNS_DELIVERY_CONFIGURED=true
MYKHAYA_APNS_TEAM_ID=...
MYKHAYA_APNS_KEY_ID=...
MYKHAYA_APNS_BUNDLE_ID=app.mykhaya.mobile
MYKHAYA_APNS_PRIVATE_KEY="-----BEGIN PRIVATE KEY----- ..."
```

Never commit the `.p8` key or expose these values to the web bundle. TestFlight
uses Apple's production APNs endpoint. The Mac-generated Xcode project must
have the Push Notifications capability and an `aps-environment` entitlement
with the production signing profile before archiving; Background Modes is not
required for ordinary alert delivery.

The APNs Key ID and private `.p8` key must belong to the same Apple key. A
previous delivery outage was caused by loading a valid, but different, `.p8`
for the configured Key ID. If delivery is in doubt, compare public-key
fingerprints without exposing private material. On the source machine, derive
the fingerprint from the source key:

```sh
openssl pkey -in AuthKey_<KEY_ID>.p8 -pubout -outform DER | shasum -a 256
```

Derive the fingerprint from the key loaded by the worker (the command prints
only the SHA-256 fingerprint):

```sh
docker compose exec worker python -c 'import hashlib; from cryptography.hazmat.primitives import serialization; from mykhaya.config import get_settings; s=get_settings(); k=serialization.load_pem_private_key(s.apns_private_key.get_secret_value().replace("\\n", "\n").encode(), password=None); print(hashlib.sha256(k.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest())'
```

The two fingerprints must match. APNs credentials belong on the backend only;
never commit or paste a `.p8` file, JWT, bearer token, or device token.

### Capacitor 8 AppDelegate wiring

The installed Capacitor Push Notifications 8 plugin does not automatically
intercept UIKit's remote-notification registration callbacks. Its
`PushNotificationsPlugin.swift` observes these NotificationCenter names:

- `.capacitorDidRegisterForRemoteNotifications`
- `.capacitorDidFailToRegisterForRemoteNotifications`

`apps/ios-shell/scripts/mac-bootstrap.sh` runs
`scripts/ensure-apns-appdelegate.sh` after `cap sync ios`. That idempotent
patch adds both AppDelegate callbacks and posts the exact plugin-supported
notifications. It also logs only `token_present=true` on success or the safe
category `error_category=apns_registration_failure` on failure; it never logs
the token or the NSError text. If a generated/custom AppDelegate already has
partial or custom APNs callbacks, the script stops for manual review rather
than risking duplicate or intercepted methods.
