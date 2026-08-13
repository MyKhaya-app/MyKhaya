# Platform Administration Security

Implemented controls include a separate hostname and API namespace, host-only session cookie, Strict SameSite, CSRF, idle/absolute expiry, revocation, deny-by-default network policy, trusted-proxy validation, platform-only roles, bounded queries, strict schemas, recent authentication for sensitive actions, reasons/confirmation, metadata minimisation, secret-shaped audit redaction and a dedicated append-only API trail.

The application exposes no audit update/delete endpoint. Database roles and external log shipping should additionally prevent application operators from altering retained audit data.

Never store passwords, cookies, session/reset/verification tokens, SMTP credentials, API keys or full secrets in events, notes or settings. Mail credentials remain environment-managed and are never returned.

Production blockers: external audit retention/alerting and independent security testing.

## Emergency MFA recovery (break-glass)

`python -m mykhaya.platform_admin_mfa_recovery --email <email>` — for a Platform Administrator who has lost every second factor (passkey, authenticator app, recovery codes) and has no other administrator able to reset them from the Control Centre. Restricted to whoever already has shell/container access to the MyKhaya server; it is a console-only command with no web endpoint or API route, and must never be exposed as one.

Behaviour: prints the target's email, display name, role and active status, then requires the operator to type the administrator's email back exactly before proceeding (no single-key confirmation for a Platform Control Centre account). It then, in one transaction: disables and removes any TOTP secret, deletes every registered WebAuthn credential, deletes every recovery code, and revokes every currently-active session for that administrator — and writes a `SecurityEvent` (`administrator_mfa_reset_via_break_glass_cli`, severity `high`) recording that it ran. It never logs a secret, session token, or credential material; it never signs the administrator in; it never changes their role or the global `MYKHAYA_ADMIN_MFA_REQUIRED` policy. The administrator re-enrols MFA (`mfa_setup_required`) the next time they sign in with their password, if the policy still requires it — which it does unless explicitly changed separately.

Operational implications: this is a genuinely destructive action against the highest-privilege identity in MyKhaya — every session for that administrator ends immediately, including any that were legitimately in use. Only run it when you have independently confirmed, outside of MyKhaya, that the request is genuine (e.g. a known colleague, not just an email in a ticket). Treat the `SecurityEvent` it writes as something to review, not just log.
