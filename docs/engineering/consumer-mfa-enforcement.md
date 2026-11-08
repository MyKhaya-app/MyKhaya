# Consumer MFA enforcement (web and native)

This is the engineering reference for how MyKhaya enforces the consumer MFA
policy. It covers every adult sign-in path, on the web and in the iOS and
Android apps. Platform administrator (PCC) MFA is separate. It is always
required and is described in
[Administrative authentication](../architecture/administrative-authentication.md).

## Policy in one paragraph

There is one consumer MFA policy. PCC → Security → **Consumer MFA** manages
it (the card was called "Consumer Browser MFA" until it was renamed to match its
scope), and it is stored in `platform_settings`
(`consumer_browser_mfa_policy`). Home and user rows can only make it stricter.
When the effective policy is **Required** and the deployment gate
`MYKHAYA_BROWSER_MFA_HANDOFF_ENABLED=true` is on, an adult must complete TOTP or
an email code before **any** session is issued. This applies to web password,
web passkey, web Apple and Google, native password, and native Apple and
Google sign-in. In the same state, long-lived device renewal is blocked on web
and native. Managed-child sign-in never uses this policy. The storage key
(`consumer_browser_mfa_policy`), the API path (`/api/v1/platform/auth/mfa/browser-policy`)
and the gate `MYKHAYA_BROWSER_MFA_HANDOFF_ENABLED` keep their historical names.
Only the PCC wording changed.

## Why native sign-in is not exempt

An earlier PCC description said the policy "does not affect native app
sign-in". The backend never fully matched that. That cannot be implemented securely today:

- `/auth/mobile/*` endpoints are public URLs. Calling them proves nothing about
  the client ([ADR 0010](../architecture/adr/0010-mobile-bearer-session-tokens.md)
  says so explicitly).
- `X-MyKhaya-Client`, `X-MyKhaya-Platform`, `X-MyKhaya-App-Version` and
  `User-Agent` are display-only (`mobile_client_descriptor()` in
  `routers/auth.py`). They are never trusted.
- There is no app-instance attestation (no App Attest, DeviceCheck or Play
  Integrity) and no app-bound key.
- A native bearer session is accepted by every API endpoint, from any client.
- The system-browser native flows (Google on iOS, Apple on Android) are
  ordinary OAuth browser flows. Anyone can drive them from a desktop browser.

An exemption keyed on "native" would therefore let anyone with a stolen
password run `POST /auth/mobile/login` with `curl` and skip MFA. A native
exemption would need a demonstrable app-instance trust boundary first, such as
App Attest or Play Integrity bound to the session request, plus an
architecture decision. Until then, native sign-in follows the same policy as
the browser.

## Enforcement points

All of these call the same resolver,
`consumer_mfa_policy.resolve_consumer_mfa_policy()`, through
`_resolve_browser_mfa_policy()`. That resolver fails closed with a 503 if a
required policy has no allowed methods.

| Path | Endpoint | Behaviour when MFA is required |
|---|---|---|
| Web password, passkey, Apple, Google | `complete_browser_authentication()` | Browser pre-auth in Redis. Continues at `/mfa` with `/auth/mfa/*`. |
| Web device renewal | `POST /auth/renew` | Device revoked, 401. |
| Native password | `POST /auth/mobile/login` | Native pre-auth. Continues with `/auth/mobile/mfa/*`. |
| Native Apple (iOS) / Google (Android) SDK | `POST /auth/mobile/external/exchange` | Native pre-auth. |
| Native system-browser provider flow | `POST /auth/mobile/external/redeem` | Native pre-auth. |
| Native provider registration | `POST /auth/mobile/external/recovery/register` | Native pre-auth. |
| Native device renewal | `POST /auth/mobile/sessions/renew` | Device revoked, 401. The app returns to sign-in. |
| Native session rotation | `POST /auth/mobile/sessions/rotate` | 403 "Sign in again to extend this session". The current session stays valid until it expires. **Not yet sufficient on its own:** see the known gap below. |
| Browser session rotation | `POST /auth/sessions/rotate` | **Not gated (known gap).** |
| Managed child (web and native) | `/auth/child/login`, `/auth/mobile/child/login` | Not subject to the policy. |

`_native_mfa_continuation()` creates every native pre-auth.

**Known gap: browser session rotation.** `POST /auth/sessions/rotate` does not
check the consumer MFA policy, and `auth_context` accepts a bearer token as
well as the cookie. A session that was valid before MFA became Required, from
either transport, can therefore still be rotated there into a new cookie
session with a fresh expiry. This was confirmed on the release candidate on
2026-11-08. It does not let a new sign-in skip MFA, because it needs an
already-valid session. It does allow such a session to outlive the policy
change indefinitely. The planned fix applies the same gate as native rotation,
a 403 when MFA is required with the current session left valid. No first-party
client calls either rotate endpoint.

## Native pre-authentication contract

1. Primary factor succeeds: password check, or verified provider assertion
   with nonce, audience, environment and single-use transaction checks.
2. The server stores a `NativeMfaTransaction` in Redis (10-minute TTL) with the
   user id, the primary method (`password`, `apple` or `google`) and the SHA-256
   hash of the client's **redemption verifier**. No `Session` or
   `TrustedDevice` row exists yet. The response is
   `{authentication_state: "additional_auth_required", transaction_id, provider}`
   with `Cache-Control: no-store`.
3. The client must present the same verifier on `GET /auth/mobile/mfa/options`,
   `POST /auth/mobile/mfa/start` and `POST /auth/mobile/mfa/verify`. A leaked
   transaction id on its own is useless.
4. `verify` reads the transaction without consuming it while it checks the
   code. A mistyped code does not throw away the primary factor. Failures are
   rate limited (`mfa-email-verify` 10/15 min, `mfa-totp-verify` 10/5 min,
   plus the 5-attempt cap on each email challenge and single-use TOTP steps)
   and audited (`MFA_LOGIN_FAILED`, target `native_mfa`).
5. After a correct code, the transaction is consumed atomically (`GETDEL`)
   **before** the session is issued. Only one request can mint a session.
   Replays return 400.
6. Browser and native pre-auth transactions use separate Redis namespaces and
   cannot be used in place of each other.

For native password sign-in, `redemption_verifier` is an optional field on
`POST /auth/mobile/login` (`MobileLoginRequest`). If MFA is required and the
field is missing (an older client), the API returns 400 and issues no
session. It fails closed.

## Operational configuration

| Setting | Where | Effect |
|---|---|---|
| `MYKHAYA_BROWSER_MFA_HANDOFF_ENABLED` | Deployment `.env` | Deployment gate. When `false`, nothing is enforced on any transport, whatever the policy says. |
| Consumer policy (Optional or Required) and allowed methods | PCC → Security → Consumer MFA | Platform policy for web and native. Only a PCC Owner can change it, with recent authentication and a reason. Changes are audited. |
| Home and user MFA policy | PCC Home and User pages | Can only make the policy stricter. |
| No platform policy row and gate `true` | Legacy fallback | Effective policy is **Required** (source `rollout_flag`). |

Effect on existing sessions when the policy becomes Required: current bearer
and cookie sessions stay valid until they expire (`MYKHAYA_SESSION_MINUTES`,
14 days by default). Opening the app with a valid session, including the
biometric (Quick Sign-In) unlock, does not ask for MFA. The app calls renewal
only after `/users/me` returns 401 (`NativeMyKhayaClient.bootstrapSession`).
After expiry, renewal is refused and the device credential is revoked, so the
person signs in again with MFA. This also applies to sessions that were
originally completed with MFA. A renewal credential bound to the MFA proof would
remove that repeat prompt, but it needs a schema change and is not
implemented.

## User-visible behaviour (native)

- After password, Apple or Google sign-in, the sign-in card shows only
  **Additional verification required**. The email/password form, provider
  buttons, recovery choices and footer links are hidden. They come back only
  through **Use a different sign-in method**.
- The person picks an email code or the authenticator app and starts
  verification. The method is then fixed for that attempt; to change it, use
  **Use a different sign-in method** and sign in again. The code field takes
  focus, accepts digits only (`one-time-code` autofill), and the keyboard's
  Go/Enter key submits it. A second submit while one is in flight is ignored.
  Errors appear inside the challenge, and a wrong code can be retried without
  repeating the password or provider step.
- If an authenticator must be enrolled (a TOTP-only policy), the setup key is
  shown in the challenge.
- If a password sign-in was linking an Apple or Google identity, the link is
  made only after MFA succeeds.
- Native MFA never uses the cookie-based `/mfa` page.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Native sign-in shows "Additional verification required" | Expected. The effective policy is Required (Platform, Home or user), or there is no platform policy row while the gate is `true` (source `rollout_flag`). Check PCC → Security → Consumer MFA and the user's PCC page. |
| Native password sign-in returns 400 "Update MyKhaya and sign in again" | The client did not send `redemption_verifier`. This is a web bundle older than this change. The shell loads the live web build, so reload it. |
| `/auth/mobile/mfa/*` returns 400 "invalid or has expired" | The transaction expired (10 minutes), was already used, or the verifier does not match. Sign in again. |
| 429 on MFA verify | Ten failed codes for that user from that IP within the window. Wait for the window (15 minutes for email, 5 for TOTP). |
| App returns to sign-in after about 14 days with MFA Required | Expected. Renewal is refused while MFA is required (`session.renewal_blocked_mfa_required` in the audit log). |
| Policy shows Required but nobody is challenged | `MYKHAYA_BROWSER_MFA_HANDOFF_ENABLED=false`. The PCC card shows a warning. |
| 503 "We couldn't complete secure sign-in" | The required policy has no allowed methods after Home and user narrowing. It fails closed. Fix the method configuration. |

Audit events: `native.pre_auth.created`, `MFA_EMAIL_CHALLENGE_*`,
`MFA_TOTP_VERIFICATION_*`, `MFA_LOGIN_FAILED` (target `native_mfa` or
`browser_mfa`), `MFA_LOGIN_SUCCEEDED` and `session.renewal_blocked_mfa_required`.

## Tests

| Layer | File | Covers |
|---|---|---|
| API | `apps/api/tests/test_native_mfa_policy.py` | Native password challenge with no session or device row. Missing verifier fails closed. Optional policy or gate off still issues a session. Verifier theft, mistyped code, single issuance and replay. Spoofed native headers on browser `/auth/login`. Browser and native transactions are not interchangeable. Apple and Google exchange challenge plus exchange replay. Renewal blocked and revoked when required, and unchanged when optional. |
| API | `apps/api/tests/test_native_mfa_policy.py` (continued) | A valid session works after the policy becomes Required, and rotation is refused while the session stays valid. Rotation is unchanged when optional. Transaction TTL is 10 minutes or less and only the verifier hash is stored. Ten failed codes give 401 then 429, with 10 `MFA_LOGIN_FAILED` audit rows and no session. |
| API | `apps/api/tests/test_native_external_auth.py::test_concurrent_native_claims_leave_one_provider_owner` | Two users racing for one provider subject leave exactly one owner. Both rejection paths (ownership check or unique constraint) count as a lost claim. |
| API | `apps/api/tests/test_browser_mfa_flow.py` | Browser enforcement matrix and completion. Unchanged. |
| API client | `packages/api-client/src/native-client.test.ts` | `login()` sends the verifier and stores nothing on a continuation. |
| Web UI | `apps/web/app/login/native-mfa.test.tsx` | The challenge replaces the form after native password and Apple sign-in. Completion, in-challenge errors, TOTP setup key, cancel, method switching before start and locking after, code-field focus, keyboard submit and single submission. |
| Web unit | `apps/web/components/native-auth.test.ts` | `nativeLogin` sends a 64-hex per-attempt verifier and returns the continuation unchanged. |
| PCC UI | `apps/web/app/control-centre/security/page.test.tsx` | The "Consumer MFA" card describes native sign-in and no longer claims an exemption. |

Run the API suites through `infrastructure/scripts/run-tests.sh` (isolated
`postgres-test` and `redis-test`).

## Physical-device checks still required

Automated tests do not replace these. Record the device, OS, app build, web
build and API build for each.

- iOS DEV: password, native Apple and system-browser Google, each with MFA
  Required (email and TOTP) and with MFA Optional.
- Android DEV: password, native Google and system-browser Apple, the same
  matrix.
- The keyboard and the challenge on a standard iPhone in portrait and
  landscape and on both Duo screens: no form underneath, and the code field is
  not obscured.
- Policy changed to Required while the app holds a session: the app returns
  to sign-in on the next renewal, and Quick Sign-In does not bypass it.
- One-time-code autofill from email on iOS.
- Method switching before starting verification, cancel ("Use a different
  sign-in method"), a wrong code then a right code, and TOTP enrolment with the
  setup key on a device with no authenticator entry.
