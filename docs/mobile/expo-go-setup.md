# Expo Go Setup (Windows)

`apps/mobile` currently targets **Expo SDK 53** (see
[expo-and-device-development-audit.md](./expo-and-device-development-audit.md#sdk-rollback-57--53)
for why - a deliberate early-stabilisation step, not a permanent decision).
The Expo Go app currently on the Play Store / App Store targets a newer SDK
generation (SDK 54+ as of this writing), so:

- **Android**: install the SDK-53-specific Expo Go build directly from Expo
  (not the Play Store) - see
  [Android: SDK 53 Expo Go installation](#android-sdk-53-expo-go-installation)
  below.
- **iPhone**: Apple's platform restrictions mean only the current Play
  Store / App Store build of Expo Go can be installed - there is no
  supported way to sideload an older SDK-specific build on iOS. Use Android
  for now, or wait for a future SDK bump / EAS development build.

EAS development-build setup (for when Expo Go isn't enough - custom native
modules, production-grade push notification testing, or iPhone testing
against an older SDK) is a later, separate piece of work and isn't
documented yet.

## What this covers

Getting `apps/mobile` open on Anthony's physical phone via Expo Go, from a
Windows development machine, against the local MyKhaya backend, and signing
in (see "Signing in" below - implemented per
[ADR 0010](../architecture/adr/0010-mobile-bearer-session-tokens.md)).

## One-time setup

1. Install [Expo Go](https://expo.dev/go) from the iOS App Store or Google
   Play Store on the phone.
2. Confirm the phone and the Windows computer are on the **same trusted
   network** (same Wi-Fi/LAN). Expo Go's default "LAN" connection mode
   requires this; it does not work across separate networks or most guest
   Wi-Fi setups that isolate clients from each other.
3. Find the Windows machine's LAN IP address:
   ```powershell
   ipconfig
   ```
   Use the IPv4 address of the adapter the phone's network is also on
   (typically `192.168.x.x` or `10.x.x.x`).
4. Copy the mobile env template and fill in that address:
   ```powershell
   cd apps\mobile
   copy .env.example .env
   ```
   Edit `.env` and set `EXPO_PUBLIC_API_BASE_URL=http://<your-LAN-IP>:8080`
   (`8080` matches `MYKHAYA_DEV_HOST_PORT` in the root `.env.dev.example`).
   **Do not commit `.env`** — it's covered by the repo's root `.gitignore`
   (`.env.*` with `.env.example` explicitly allow-listed).
5. Windows Firewall: the first time `expo start` runs, Windows will likely
   prompt to allow Node.js through the firewall for private networks —
   accept it. If the phone still can't connect, check
   **Windows Defender Firewall → Allowed apps** and confirm Node.js (or the
   specific `node.exe` you're running) is allowed on "Private" networks. Do
   not allow it on "Public" networks.

## Every-time developer workflow

```powershell
git checkout dev
git pull
pnpm install --frozen-lockfile
make dev-up                       # starts the backend (see root README)
pnpm --filter @mykhaya/mobile start
```

`expo start` will print a QR code in the terminal and open Expo Dev Tools.

## Android: SDK 53 Expo Go installation

Expo officially publishes SDK-specific Expo Go builds for Android outside
the Play Store, precisely for this situation (a project pinned to an older
SDK than the current Play Store release). This is Expo's own domain, not a
third-party APK site.

1. On the Android phone, open a browser and go to:
   `https://expo.dev/go?sdkVersion=53&platform=android&device=true`
   This is Expo's own official page for downloading the SDK-53-matched Expo
   Go build; it detects the device and offers a direct APK download.
2. Download the APK from that page.
3. **Allow installation from this source**: Android will prompt to allow
   installs from the browser (or Files app) that downloaded it -
   Settings → Apps → [Chrome/Files] → Install unknown apps → Allow. This
   permission only needs to be granted once and can be revoked afterwards
   if preferred.
4. Install the downloaded APK.
5. If the Play Store version of Expo Go is already installed, this
   SDK-specific build is packaged as a distinct app (their package IDs
   differ) - both can coexist, or uninstall the Play Store one first if you
   prefer a single Expo Go icon.
6. Start Metro as in "Every-time developer workflow" above:
   `pnpm --filter @mykhaya/mobile start`
7. Open the SDK-53 Expo Go app and scan the QR code from the terminal, or
   type the `exp://` URL Metro prints if scanning doesn't work.
8. **To revert to the Play Store version later**: uninstall this
   SDK-specific build and reinstall/reopen Expo Go from the Play Store as
   normal - no special uninstall steps beyond that.

## On the phone

1. Open Expo Go (the SDK-53 build on Android, per above; the Play Store
   build on iPhone - see the SDK/platform note at the top of this document
   for the current iPhone limitation).
2. Sign in to the same Expo account, if prompted (only needed for
   EAS-linked features like update channels; plain Expo Go LAN dev works
   without it too).
3. Scan the QR code from the terminal (use the phone's camera app on iOS, or
   the in-app scanner on Android).
4. The MyKhaya app should open. The home screen shows a live connection
   check against the API's `/api/v1/health/live` endpoint — "Connected"
   confirms the phone can reach the backend over the LAN.

## If LAN mode fails

- Confirm `make dev-up` is actually running and `http://localhost:8080/api/v1/health/live`
  returns `{"status":"ok"}` from the Windows machine itself first.
- Confirm the phone and PC show IP addresses on the *same* subnet.
- Recheck the Windows Firewall prompt (step 5 above) — a silently blocked
  Node.js process is the most common cause.
- Some routers isolate wireless clients from each other ("AP/client
  isolation" or "guest network" settings) — this will break LAN mode even
  though both devices show as "connected" to the same Wi-Fi name. Check the
  router configuration or use a non-guest network.
- **Fallback: Expo tunnel mode.** This routes traffic through Expo's relay
  servers instead of the LAN, which works around network isolation and
  cross-network cases:
  ```powershell
  pnpm --filter @mykhaya/mobile start --tunnel
  ```
  Tunnel mode is a development convenience for exactly this kind of
  connectivity troubleshooting — it is not the production network
  architecture and should not be treated as a permanent workflow.

## Signing in

Implemented per
[ADR 0010](../architecture/adr/0010-mobile-bearer-session-tokens.md):
`POST /api/v1/auth/mobile/login` returns an opaque bearer token in the
response body (never a cookie), which the app stores via `expo-secure-store`
(`apps/mobile/src/auth/tokenStore.ts`) and attaches as
`Authorization: Bearer <token>` on every subsequent request
(`apps/mobile/src/api/authorizedFetch.ts`).

On the home screen, the sign-in form (email + password, plain React Native
components - not yet styled with Khaya UI, which is a later phase) calls
this endpoint directly. A successful sign-in immediately fetches
`GET /api/v1/users/me` via the same bearer token to confirm the round trip
works end to end. Sign out calls `POST /api/v1/auth/mobile/logout` and always
clears the local token even if that call fails (offline-safe, per ADR 0010).

To test manually: register and verify an account on the web app first
(`https://dev.mykhaya.app`, or via `MYKHAYA_EMAIL_VERIFICATION_ENABLED=false`
for local dev without email delivery), then use the same credentials in the
mobile app's sign-in form.
