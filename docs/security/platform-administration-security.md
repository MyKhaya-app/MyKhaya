# Platform Administration Security

Implemented controls include a separate hostname and API namespace, host-only session cookie, Strict SameSite, CSRF, idle/absolute expiry, revocation, deny-by-default network policy, trusted-proxy validation, platform-only roles, bounded queries, strict schemas, recent authentication for sensitive actions, reasons/confirmation, metadata minimisation, secret-shaped audit redaction and a dedicated append-only API trail.

The application exposes no audit update/delete endpoint. Database roles and external log shipping should additionally prevent application operators from altering retained audit data.

Never store passwords, cookies, session/reset/verification tokens, SMTP credentials, API keys or full secrets in events, notes or settings. Mail credentials remain environment-managed and are never returned.

Production blockers: WebAuthn/passkeys, an administrator-management workflow with verified MFA binding, external audit retention/alerting, independent security testing, and reviewed break-glass procedures.
