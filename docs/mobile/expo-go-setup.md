# Expo Go Setup (Windows)

See [expo-and-device-development-audit.md](./expo-and-device-development-audit.md)
for the SDK 53→57 upgrade that made this workflow viable in the first place.
EAS development-build setup (for when Expo Go isn't enough - custom native
modules, production-grade push notification testing) is a later, separate
piece of work and isn't documented yet.

## What this covers

Getting `apps/mobile` open on Anthony's physical phone via Expo Go, from a
Windows development machine, against the local MyKhaya backend. Does **not**
cover signing in — see "Known limitation: no mobile authentication yet"
below.

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
git checkout feature/mobile-calendar-foundation
pnpm install --frozen-lockfile
make dev-up                       # starts the backend (see root README)
pnpm --filter @mykhaya/mobile start
```

`expo start` will print a QR code in the terminal and open Expo Dev Tools.

## On the phone

1. Open Expo Go.
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

## Known limitation: no mobile authentication yet

`docs/architecture/authentication.md` states "Mobile clients use secure
platform storage," but as of this branch, `apps/api`'s `POST /auth/login`
only issues HttpOnly session cookies and returns a `UserResponse` body — it
does not return any token a native app could store via `expo-secure-store`.
There is no `Authorization: Bearer` handling anywhere in `apps/api`.

This means the mobile app can currently prove it can *reach* the API
(the health check above) but **cannot sign a user in or make any
household-scoped request**. This blocks all further mobile work that
requires an authenticated user - the Calendar view, event creation, member
data, everything past the placeholder home screen. This needs an explicit
architecture decision (see Security Design Checkpoint in the audit doc)
before Phase 6 onward can proceed with real data.
