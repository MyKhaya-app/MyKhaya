# Administrative Authentication

Platform administrators are separate records and have no public registration route. The first Platform Owner is created only with `python -m mykhaya.bootstrap_platform_owner` while `MYKHAYA_ADMIN_BOOTSTRAP_ENABLED=true`; the command prompts without echo and refuses to run after the first administrator exists. Disable the flag immediately.

Admin sessions use opaque random tokens stored as keyed hashes. `mk_admin_session` is Secure in production, HttpOnly, SameSite=Strict, host-only and path `/`; `mk_admin_csrf` is a separate double-submit value. Household cookies are neither read nor accepted. Sessions have a sliding idle deadline and a non-extendable absolute deadline and can be listed or revoked.

Sensitive actions require a session authenticated within `MYKHAYA_ADMIN_RECENT_AUTH_MINUTES`, an explicit `confirmed: true`, a meaningful reason, role permission and an audit event.

`mfa_enrolled` and `MYKHAYA_ADMIN_MFA_REQUIRED` form a fail-closed enforcement boundary. The bootstrap process deliberately creates the owner as unenrolled. WebAuthn enrolment and assertion verification are not implemented, so production Control Centre release remains blocked. Do not disable MFA in production; configuration validation rejects that state.
