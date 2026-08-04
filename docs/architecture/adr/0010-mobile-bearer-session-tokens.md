# ADR 0010: Mobile Bearer Session Tokens

**Status:** Proposed — awaiting Anthony's review before any `apps/api` implementation. Not yet built. Written in response to a security design checkpoint raised while building the mobile Calendar foundation (`docs/mobile/expo-go-setup.md` documents the current gap in practice).

## Problem

`docs/architecture/authentication.md` and [ADR 0006](./0006-session-authentication.md) both describe browser sessions as opaque, high-entropy tokens transported in `Secure`, `HttpOnly` cookies, with ADR 0006 explicitly noting this "preserv[es] native-client evolution through a separate secure-storage flow." That separate flow was never built: `POST /auth/login` (`apps/api/mykhaya/routers/auth.py`) only calls `set_auth_cookies`, and `current_user()` (`apps/api/mykhaya/security.py`) only reads `request.cookies.get("mk_session")`. There is no `Authorization` header handling anywhere in `apps/api`. A native app cannot sign in.

## Trust boundary

A browser and a MyKhaya-controlled native app are different trust boundaries. A browser auto-attaches cookies to same-origin requests, which is why CSRF protection exists (`require_csrf` in `security.py`) — an attacker's page can trigger a cookie-carrying request without the user's intent. A native app has no equivalent ambient-credential problem: nothing attaches an `Authorization` header except code we write, so CSRF's threat model doesn't apply to it. The mobile app itself is a data store worth protecting (a stolen unlocked phone with the app installed), which is why the token belongs in `expo-secure-store` (OS keychain / Keystore-backed), not `AsyncStorage`.

## Proposed design

Reuse the existing `Session` model and token scheme exactly — no new token type, no new secret, no new hashing. Only the *transport* differs for native clients.

1. **Login request signals client type.** Add an optional field to `LoginRequest`, e.g. `client: Literal["web", "mobile"] = "web"` (schema-level, not a header, so it's validated the same way as the rest of the request body).
2. **`issue_session` returns the raw token to mobile clients only.** When `client == "mobile"`, `POST /auth/login`'s response body includes the raw session token (the same `raw = new_session_token()` value that's otherwise only ever put in the cookie) as e.g. `session_token`. Cookies are *not* set for mobile logins — a native app's `fetch` doesn't manage cookie jars reliably across app restarts, and giving it a cookie it can't use is a false affordance. Web logins are unchanged: cookies only, no token in the body, so browser response payloads don't gain a new secret they don't need (least privilege).
3. **`current_user()` accepts `Authorization: Bearer <token>` as an alternative to the cookie.** Same `hash_secret` + `Session` table lookup either way — a mobile-issued token and a browser-issued token are indistinguishable server-side once issued; both show up identically in `GET /auth/sessions` and can be revoked identically via `DELETE /auth/sessions/{id}`.
4. **`require_csrf` skips the CSRF check when the request authenticates via `Authorization` header instead of the `mk_session` cookie.** CSRF protection exists specifically for cookie-carried credentials; it has no meaning for a header the client must construct explicitly.
5. **Mobile stores only the raw token** via `expo-secure-store`, under a dedicated key (e.g. `mykhaya.session_token`), and sends it as `Authorization: Bearer <token>` on every request. It never receives or needs the CSRF cookie value.
6. **No new expiry/rotation logic.** `session_minutes` (default 14 days), `/auth/sessions/rotate`, and `/auth/logout` all already operate on the `Session` row and work unchanged for a bearer-authenticated session — `auth.session` is resolved identically regardless of transport.

## Data protected

The session token itself (bearer-equivalent to a password for the token's lifetime) and, transitively, everything a signed-in user can reach: household calendar events (including private ones), member data, feature settings.

## Token lifecycle

- **Issuance**: on successful `/auth/login` with `client: "mobile"`, identical entropy/hashing/expiry to the existing cookie flow (`new_session_token()`, `hash_secret`, `session_minutes`).
- **Storage**: `expo-secure-store` only. Never logged, never included in analytics/crash reports, never in `EXPO_PUBLIC_*` (those are build-time, not runtime, and are not secrets storage regardless).
- **Refresh**: existing `/auth/sessions/rotate` semantics apply unchanged.
- **Revocation**: existing `/auth/logout` (self) and `DELETE /auth/sessions/{id}` (any device, from any signed-in device) apply unchanged — a mobile session is just another row in the same table, visible and revocable from the web session-management UI once mobile sessions start appearing there.

## Failure behaviour

A `401` from any authenticated endpoint means the mobile app clears the stored token and returns to a signed-out state — no silent retry with a stale token, no ambiguous partial-auth UI state. This mirrors how `apps/web` already treats a `401` (per existing session-check patterns).

## Audit requirements

No new audit events needed — `session.created` and `session.revoked` already fire from the same code paths regardless of transport (`issue_session`, `logout`, `revoke_session` in `auth.py`). The existing `user_agent` field on `Session` already distinguishes device/client type in the audit trail (mobile requests would carry Expo/React Native's default `fetch` user agent, or we set an explicit one — a one-line addition, not a new audit mechanism).

## Recovery implications

Identical to today's web recovery path: password reset flows are unaffected (they don't touch sessions directly), and a compromised mobile device is handled the same way a compromised browser session is — revoke via `DELETE /auth/sessions/{id}` from another signed-in device, or `session.rotate` after password change (existing behaviour, not proposed here).

## Alternatives considered

- **JWTs instead of opaque tokens.** Rejected: would duplicate the exact problem ADR 0006 already solved for the web (long-lived, unrevocable-until-expiry credentials) and introduce a second auth scheme to maintain instead of reusing the one that's already reviewed and in production.
- **OAuth2 / OIDC-style refresh+access token pair.** Rejected for now as disproportionate: MyKhaya has one first-party client (its own mobile app), not third-party integrations, so the added complexity (short-lived access tokens, refresh rotation, refresh-token theft detection) isn't buying anything the existing single-opaque-token-with-server-side-revocation model doesn't already provide via `/auth/sessions/rotate`. Worth revisiting only if MyKhaya grows third-party API consumers.
- **Reusing the cookie for mobile via a cookie jar library.** Rejected: React Native's `fetch` cookie handling is platform-inconsistent and not something to depend on for session integrity; an explicit header is unambiguous and testable.
- **A separate mobile-only session table.** Rejected: `Session` already has everything needed (`token_hash`, `expires_at`, `revoked_at`, `user_agent`); a second table would fork session-listing, revocation and rotation logic for no benefit.

## Scope of implementation, once approved

Confined to `apps/api/mykhaya/routers/auth.py` (login response), `apps/api/mykhaya/security.py` (`current_user`, `require_csrf`), `apps/api/mykhaya/schemas.py` (`LoginRequest`, `SessionResponse`/login response shape), and `apps/mobile` (SecureStore-backed token storage + an `Authorization` header on API requests). No model changes, no migration.
