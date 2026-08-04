# ADR 0010: Mobile Bearer Session Tokens

**Status:** Proposed (revision 2) — awaiting Anthony's review before any `apps/api` implementation. Not yet built. Written in response to a security design checkpoint raised while building the mobile Calendar foundation (`docs/mobile/expo-go-setup.md` documents the current gap in practice). Revision 2 incorporates review feedback from Anthony (with architectural input from a separate reviewer) on the original proposal; every numbered change below traces to a specific point raised in that review.

## Problem

`docs/architecture/authentication.md` and [ADR 0006](./0006-session-authentication.md) both describe browser sessions as opaque, high-entropy tokens transported in `Secure`, `HttpOnly` cookies, with ADR 0006 explicitly noting this "preserv[es] native-client evolution through a separate secure-storage flow." That separate flow was never built: `POST /auth/login` (`apps/api/mykhaya/routers/auth.py`) only calls `set_auth_cookies`, and `current_user()` (`apps/api/mykhaya/security.py`) only reads `request.cookies.get("mk_session")`. There is no `Authorization` header handling anywhere in `apps/api`. A native app cannot sign in.

## Design principle (unchanged from revision 1, reaffirmed by review)

One `Session` model. One session table. One hashing implementation. One revocation model. One rotation model. The only difference between web and mobile is **how the session token is transported**, never how it is validated, authorised, or managed. Nothing below introduces a second authentication system, JWTs, or OAuth.

## Endpoint design: separate `POST /auth/mobile/login`, not a `client` field on `/auth/login`

Revision 1 proposed an optional `client: "web" | "mobile"` field on the existing `LoginRequest`, with the response shape branching on it. Review feedback correctly flagged the deeper issue: **that field would be attacker-controlled input with no verification behind it** — anything in a request body is just a claim. It cannot be trusted to mean "this really is the native app," and revision 1 didn't say so explicitly enough. That's true of both designs equally (a dedicated endpoint doesn't verify caller identity either — nothing here does, or reasonably could, since MyKhaya has no separate app-attestation mechanism). But once the field's only honest job is *"pick a response format,"* putting it in the request body of a shared endpoint invites future misreading — someone extending this code six months from now could plausibly (mis)treat `client == "mobile"` as meaningful for something security-relevant, exactly the failure mode flagged.

A dedicated endpoint makes the wrong reading structurally harder: there's no field to accidentally check downstream, because there's no field. Trade-offs:

|  | Shared `/auth/login` + `client` field | Dedicated `/auth/mobile/login` |
| --- | --- | --- |
| Response schema clarity | Conditional shape (bearer token present only sometimes) — awkward in OpenAPI, needs a union/optional response model | Unambiguous: this endpoint always returns a bearer token, the other never does |
| Risk of future misuse of the discriminator | A body field sits right next to real request data, inviting "just check this field" shortcuts later | No discriminator field exists to misuse |
| Rate limiting / observability | Shares one bucket and one set of metrics for both transports | Can be tuned per-transport later if needed, without touching the other |
| Credential-verification logic | Naturally shared (one function) | Must be deliberately factored into a shared helper, or it duplicates (and duplicated security logic drifts) |

**Recommendation: dedicated `POST /auth/mobile/login`**, with credential verification (email normalisation, password check, active/verified/lockout checks, rate limiting) factored into a shared internal function `authenticate_credentials(db, request, body, settings) -> User` that both `/auth/login` and `/auth/mobile/login` call. This gets the clearer response contract without duplicating the security-sensitive part. `/auth/login` keeps setting cookies only, exactly as today; `/auth/mobile/login` never sets cookies and always returns a bearer token in the body.

**Explicit statement, as required by review**: the request reaching `/auth/mobile/login` vs `/auth/login` is *transport-selection information supplied by the caller, nothing more*. It proves nothing about client authenticity. It must never be read anywhere for authorisation, permission, or rate-limiting decisions — those all continue to run identically off `AuthenticatedSession.user` regardless of which endpoint issued the session (see below).

## Resolved authentication context (replaces ad hoc cookie/header inspection)

Today, `auth_context()` calls `require_csrf(request, settings)` unconditionally, then `current_user(request, db, settings)`, which only reads the cookie. Two independent places would need to agree on transport if left as-is once a second transport exists. Instead:

```python
@dataclass(frozen=True)
class AuthenticatedSession:
    user: User
    session: Session
    transport: Literal["cookie", "bearer"]
```

A single function, `resolve_session(request, db, settings) -> AuthenticatedSession`, becomes the *only* place that inspects the `Authorization` header or the `mk_session` cookie. `auth_context()` calls it once, then applies CSRF policy based on `.transport`. `AuthContext` (the existing dataclass used throughout the routers) gains the resolved `transport` field; nothing downstream of `auth_context()` re-inspects headers or cookies.

### Bearer precedence (no silent fallback)

```
if request has an Authorization header:
    parse and validate as a bearer session token
    if invalid or expired or revoked -> 401, stop (do not check cookies)
    -> resolved as transport="bearer"
elif request has an mk_session cookie:
    validate as today
    -> resolved as transport="cookie"
else:
    -> 401, "Please sign in to continue."
```

An `Authorization` header, once present, is authoritative for that request. A malformed or expired bearer token never causes a quiet fall-through to cookie auth — that would let a caller probe which transport happens to be valid, and would make the two transports' failure behaviour observably different in a way that's hard to reason about.

### CSRF, precisely

`require_csrf` is called only when `resolved.transport == "cookie"`, and behaves exactly as it does today for that case (unsafe methods require the double-submit `mk_csrf` cookie/header pair, origin checked against `settings.cors_origins`). It is **not** invoked at all for `transport == "bearer"` — not "skipped because a header exists," but structurally never reached, because bearer resolution happens first and either succeeds (no cookie was involved, CSRF doesn't apply) or fails with 401 before CSRF is ever considered. Cookie-authenticated state-changing requests are completely unaffected by any of this.

## Token lifecycle

- **Issuance**: `POST /auth/mobile/login` on valid credentials calls the same `new_session_token()` / `hash_secret()` / `Session` row creation as `issue_session()` today, but returns the raw token in the response body (field name `session_token`) instead of setting cookies. Same entropy, same hash, same `session_minutes` expiry (14 days default) as web.
- **Response caching**: `POST /auth/mobile/login` and `POST /auth/mobile/sessions/rotate` (see below) responses include `Cache-Control: no-store` and `Pragma: no-cache`, so no intermediary or client-side HTTP cache persists a response body containing a live token.
- **Storage**: see SecureStore requirements below.
- **Refresh/rotation**: `POST /auth/mobile/sessions/rotate` (bearer-authenticated, mirrors `/auth/sessions/rotate`) atomically, in one committed transaction: marks the current `Session` row `revoked_at = now()` and creates a new `Session` row, then returns the new raw token in the body (again with `session_token`, `Cache-Control: no-store`). The old token stops validating the instant that transaction commits — there is no overlap window where both tokens are simultaneously valid. The mobile client must overwrite its SecureStore value with the new token before considering rotation complete; if the app is killed between receiving the response and writing SecureStore, the user is simply signed out and must sign in again (safe failure — no token is lost to an attacker, it's lost to nobody being able to use it, which is the correct default).
- **Revocation**: `DELETE /auth/sessions/{id}` (bearer- or cookie-authenticated, existing endpoint, unchanged) revokes any of a user's sessions by ID — a mobile session is just another row, visible in `GET /auth/sessions` and revocable from a web session there today, or a future mobile "your devices" screen.

## Logout (bearer)

`POST /auth/mobile/logout` (bearer-authenticated):
- Revokes the resolved `Session` row (`revoked_at = now()`), same as today's `/auth/logout`.
- Does not depend on and does not touch cookies.
- Not subject to CSRF (bearer transport, per the CSRF section above).
- Returns `204`.

Mobile client behaviour: delete the SecureStore token and clear any locally cached household-scoped data (household list, event data, member data — anything gated on the signed-in user) **immediately and unconditionally on local logout intent**, whether or not the network call succeeds. If the `POST /auth/mobile/logout` call fails (offline, timeout, server error), the app still completes local logout — the alternative (blocking logout on network success) traps the user in a household's data because their phone is offline, which is a worse security and usability outcome. **Explicitly documented residual risk**: in that failure case, the server-side `Session` row remains valid until it naturally expires (`session_minutes`) or is revoked from another device via `DELETE /auth/sessions/{id}`. This is the same shape of risk as closing a browser tab without clicking "sign out" today — not a new category of exposure.

## SecureStore requirements

- **Dedicated key**: `mykhaya.session_token`, storing only the raw token string — never the CSRF value (mobile never receives one), never any other session metadata.
- **Accessibility class**: strongest available that still allows a background-launched app to read it without requiring the device to be freshly unlocked mid-session — `expo-secure-store`'s `WHEN_UNLOCKED_THIS_DEVICE_ONLY` (iOS Keychain `kSecAttrAccessibleWhenUnlockedThisDeviceOnly` equivalent: excluded from iCloud Keychain sync and from device backups that could restore to a different device; Android via Keystore-backed encryption regardless). This must be set explicitly — `expo-secure-store`'s default accessibility is weaker (backed up / synced) and not acceptable for a session credential.
- **Never** in `AsyncStorage`, `EXPO_PUBLIC_*` (build-time, not a secret store, and readable in the bundle), application logs, crash reports (Sentry/similar, once added), or analytics events.
- **Removed**: on logout (above), on account/app data removal, and when the app observes its bearer token rejected as invalid/revoked under the compare-and-clear rule below (not on every 401 unconditionally — see next section).

## 401 handling: compare-and-clear, not clear-on-401

A naive "clear SecureStore on any 401" is unsafe under a real race: request A is sent using Token A; before A's response arrives, the app independently rotates and stores Token B; A's (now-stale) request then comes back 401 because Token A was just revoked by the rotation. Blindly clearing "the stored token" on that 401 would delete the still-valid Token B.

**Required behaviour**: the mobile API client captures the exact token value it used for a given request at the time it sends that request. On receiving a 401 for that request, it compares the captured value against whatever is *currently* in SecureStore before clearing anything:
- If they still match, the currently-stored token really is the one that was just rejected — clear it and transition to signed-out.
- If they differ, a rotation (or a fresh login) already replaced it since this request was sent — do nothing to SecureStore; the newer token's validity is independent and unaffected by this stale response.

## Session metadata (display-only, not trust-bearing)

React Native's default `fetch` user agent is generic and unhelpful in a "your signed-in devices" list. Add optional request headers the mobile app may send:
- `X-MyKhaya-Client` (e.g. `mobile`)
- `X-MyKhaya-Platform` (e.g. `ios` / `android`)
- `X-MyKhaya-App-Version` (e.g. `0.1.0`)

The server composes these (when present, falling back to the raw `User-Agent` when absent) into the existing `Session.user_agent` string column — no schema change. **These headers are read for display and diagnostics only.** They are explicitly out of scope for any authorisation, rate-limiting, or security decision, exactly like the `client` discriminator field discussed above — client-supplied strings are never trust inputs. This is stated here, once, as the general rule; it is not repeated as a caveat on every field above, but it applies to all of them.

## Transport security

Bearer tokens must only ever be sent over TLS in any non-local environment. `api.mykhaya.app` (the native-client origin per [ADR 0008](./0008-browser-routing-and-proxy-trust.md)) already terminates TLS at Caddy; FastAPI itself sees plain HTTP from Caddy and must determine the original scheme the same way ADR 0008 already establishes — via `X-Forwarded-Proto` from Caddy's already-pinned trusted proxy range, **not** by trusting an arbitrary incoming header. Concretely: reject `POST /auth/mobile/login` and `POST /auth/mobile/sessions/rotate` with a clear error when `settings.environment != "development"` and the trusted forwarded scheme is not `https`. Local development over plain `http://<LAN-IP>:8080` (per `docs/mobile/expo-go-setup.md`) remains explicitly allowed only in that environment. Production builds of the mobile app must not allow configuring an insecure (`http://`) API base URL at all — this is a mobile-app-side build configuration constraint, not just a server-side check, since defence in depth means the app itself shouldn't offer to send a production credential over an insecure channel.

## Data protected

The session token itself (bearer-equivalent to a password for its lifetime) and, transitively, everything a signed-in user can reach: household calendar events (including private ones), member data, feature settings.

## Audit requirements

No new audit event *types* — `session.created` and `session.revoked` already fire from the same code paths regardless of transport, and continue to do so from the shared `issue_session`-equivalent logic and the shared logout/rotate logic. `Session.user_agent` (now potentially composed from the `X-MyKhaya-*` headers above) is the only change to what's recorded, and it is diagnostic text, never a secret — the raw bearer token is never written to an audit row, a log line, or an exception message, matching the same rule that already applies to the cookie token today.

## Recovery implications

Identical to today's web recovery path: password reset revokes all of a user's sessions (existing behaviour in `reset_password`, transport-agnostic since it operates on `Session.user_id`), so a compromised mobile token is invalidated the same way a compromised browser session is. A user can also revoke a specific device's session via `DELETE /auth/sessions/{id}` from another signed-in session (web or mobile).

## Alternatives considered

- **JWTs instead of opaque tokens.** Rejected: reintroduces the exact problem ADR 0006 already solved for the web (long-lived, unrevocable-until-expiry credentials), and a second auth scheme to maintain instead of reusing the one already reviewed and in production. Reaffirmed by review.
- **OAuth2 / OIDC-style refresh+access token pair.** Rejected for now as disproportionate: MyKhaya has one first-party client (its own mobile app), not third-party integrations, so short-lived-access + refresh-rotation-with-theft-detection complexity isn't buying anything the existing single-opaque-token-with-server-side-revocation model doesn't already provide via the rotate endpoint. Revisit only if MyKhaya grows third-party API consumers.
- **Reusing the cookie for mobile via a cookie-jar library.** Rejected: React Native's cookie handling is platform-inconsistent and not something to depend on for session integrity; an explicit header is unambiguous and testable.
- **A separate mobile-only session table.** Rejected: `Session` already has everything needed (`token_hash`, `expires_at`, `revoked_at`, `user_agent`); a second table would fork session-listing, revocation and rotation logic for no benefit.
- **A `client` field on the shared `/auth/login` endpoint (revision 1's original proposal).** Superseded by the dedicated-endpoint design above, per review.

## Required tests before this ships

All existing authentication tests (`apps/api/tests/test_calendar.py` and whatever auth-specific test module already covers `/auth/*`) must continue to pass unchanged — web behaviour must not move at all. New tests, at minimum:

- Browser `/auth/login` never returns a `session_token` field in the response body.
- `/auth/mobile/login` returns a `session_token` and sets no cookies.
- `/auth/mobile/login` and `/auth/mobile/sessions/rotate` responses carry `Cache-Control: no-store` and `Pragma: no-cache`.
- A malformed `Authorization` header returns `401`.
- A malformed `Authorization` header does **not** fall back to cookie authentication even when a valid `mk_session` cookie is also present on the same request.
- A request authenticated via bearer bypasses CSRF (a state-changing bearer request with no `X-CSRF-Token` succeeds).
- A request authenticated via cookie still requires CSRF exactly as today (unchanged existing test, re-run to confirm no regression).
- An expired bearer token returns `401`.
- A revoked bearer token returns `401`.
- `/auth/mobile/sessions/rotate` returns a new `session_token` different from the old one.
- The old token is rejected (`401`) immediately after rotation.
- The new token is accepted immediately after rotation.
- `/auth/mobile/logout` revokes the correct `Session` row and returns `204`.
- Cross-household isolation is unchanged for bearer-authenticated requests (an existing calendar isolation test, re-run against a bearer session instead of a cookie session).
- Child-account restrictions are unchanged for bearer-authenticated requests (same, re-run against bearer).
- No test asserts on or captures a raw token value in a log or audit-table fixture (a check that the implementation doesn't accidentally introduce logging of the token, not just that tests pass).

Mobile-side (once the client wrapper exists): a unit test for the compare-and-clear 401 handler covering exactly the race described above (stale 401 for Token A must not delete a newly-rotated Token B already in SecureStore).

## Scope of implementation, once approved

`apps/api/mykhaya/routers/auth.py` (new `/auth/mobile/login`, `/auth/mobile/logout`, `/auth/mobile/sessions/rotate` endpoints; extraction of shared `authenticate_credentials`), `apps/api/mykhaya/security.py` (`resolve_session` replacing ad hoc `current_user`/`require_csrf` calls, forwarded-scheme check), `apps/api/mykhaya/dependencies.py` (`AuthContext` gains `transport`), `apps/api/mykhaya/schemas.py` (new mobile login/rotate response models), and `apps/mobile` (SecureStore-backed token storage, the compare-and-clear request wrapper, `X-MyKhaya-*` headers). No `Session` model changes, no migration.
