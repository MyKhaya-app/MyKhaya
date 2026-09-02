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
  fallback page, and (once generated on a Mac — see the checklist below)
  the native `ios/` Xcode project.
- **Not here:** any MyKhaya UI. Ordinary web/PWA feature work happens in
  `apps/web` exactly as before and reaches this shell automatically on next
  app launch, with no new iOS release, because the shell always loads the
  live origin.

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

Capacitor's `ios add`/`ios sync` and everything downstream of them needs
CocoaPods and Xcode, which only run on macOS. **None of this has been run
yet** — no `ios/` directory exists in this repo. See
[the Mac handoff checklist](../../docs/mobile/ios-shell-mac-checklist.md)
for the exact, minimal steps to do this once, on the Mac, when Phase 4
begins.

```sh
npx cap add ios        # generates ios/ — macOS + CocoaPods only, one-time
npx cap sync ios        # copies capacitor.config.ts + www/ into ios/ after any change to either
npx cap open ios        # opens Xcode
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
