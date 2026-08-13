# Administrative Authentication

Platform administrators are separate records and have no public registration route. The first Platform Owner is created only with `python -m mykhaya.bootstrap_platform_owner` while `MYKHAYA_ADMIN_BOOTSTRAP_ENABLED=true`; the command prompts without echo and refuses to run after the first administrator exists. Disable the flag immediately.

Admin sessions use opaque random tokens stored as keyed hashes. `mk_admin_session` is Secure in production, HttpOnly, SameSite=Strict, host-only and path `/`; `mk_admin_csrf` is a separate double-submit value. Household cookies are neither read nor accepted. Sessions have a sliding idle deadline and a non-extendable absolute deadline and can be listed or revoked.

Sensitive actions require a session authenticated within `MYKHAYA_ADMIN_RECENT_AUTH_MINUTES`, an explicit `confirmed: true`, a meaningful reason, role permission and an audit event.

`mfa_enrolled` and `MYKHAYA_ADMIN_MFA_REQUIRED` form a fail-closed enforcement boundary. The bootstrap process deliberately creates the owner as unenrolled. Do not disable MFA in production; configuration validation rejects that state.

## Second factors

Platform administrators may enrol a WebAuthn passkey (`mykhaya.platform_mfa`, standards-based via the `webauthn` package) and/or a TOTP authenticator app (`pyotp`). Enrolment, credential management, and sign-in verification live under `/api/v1/platform/auth/mfa/*` in `mykhaya.routers.platform`.

WebAuthn's RP ID and expected origin are derived once, from validated configuration — `Settings.admin_webauthn_rp_id`/`admin_webauthn_origin`, both computed from `MYKHAYA_ADMIN_URL` (never from the request's `Host`/`X-Forwarded-*` headers, which `enforce_admin_network`/`TrustedHostMiddleware` already treat as untrusted for a different reason — the admin surface's network boundary). A passkey registered while `MYKHAYA_ADMIN_URL` pointed at one hostname will not verify under a different one — this is WebAuthn's own origin binding, not a MyKhaya bug, and is why the admin hostname must not change post-enrolment without re-enrolling affected administrators.

`AdminWebAuthnCredential.credential_id` is stored as a base64url **string**; every place that hands a stored credential ID back to the `webauthn` library (`build_registration_options`/`build_authentication_options` in `mykhaya.platform_mfa`) must decode it back to raw bytes with `base64url_to_bytes`, not `.encode("utf-8")` — the latter silently produces a different byte sequence that no real authenticator can ever match, which previously made passkey sign-in fail with the browser reporting no matching passkey even though a valid credential existed server-side.

## Recovery codes

Ten single-use recovery codes (`mykhaya.platform_mfa.generate_recovery_codes`, stored as salted hashes in `AdminRecoveryCode`, never plaintext) are issued **atomically** with whichever request completes an administrator's *first* MFA factor (`routers.platform._issue_recovery_codes_if_first_factor`) — not via a separate follow-up call the frontend could fail to complete. An administrator can regenerate their codes at any time from the Security page (`POST /auth/mfa/recovery-codes`, requires recent auth); regeneration invalidates every previous code. Codes are shown to the administrator exactly once, at generation time, and are never retrievable again afterwards.

## Locked-out recovery

Two mechanisms exist, for two different situations:

- **Another administrator with sufficient privilege is signed in**: `PUT /api/v1/platform/administrators/{id}/mfa-reset`, gated by role (an Owner is required to reset another Owner; Administrator/Security may reset non-Owners) and audited.
- **No other administrator can help (true break-glass)**: `python -m mykhaya.platform_admin_mfa_recovery --email <email>`, run with server/container access only. Console-only, never web-exposed; requires typing the administrator's email back as confirmation; clears TOTP, WebAuthn credentials and recovery codes, revokes every active session, and writes a `SecurityEvent` — but never touches the administrator's role or the global `MYKHAYA_ADMIN_MFA_REQUIRED` policy. The administrator simply re-enrols (`mfa_setup_required`) on next sign-in. See `docs/security/platform-administration-security.md` for the full operational procedure.
