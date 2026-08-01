# Platform Administration Threat Model

## Assets and boundaries

Privileged accounts/sessions, operational metadata, global configuration, feature availability, audit/security records and public incident integrity cross browser, Caddy, API, database, Redis and operator-device boundaries.

## Principal threats and controls

- Household-role escalation: separate identity model and dependencies.
- Stolen operator credential/session: mandatory-MFA boundary, short idle/absolute sessions, host-only cookies and revocation; WebAuthn remains required.
- Proxy spoofing/network bypass: ignore forwarding headers from untrusted socket peers and deny outside the allow-list.
- Casual private-content access: no content repositories or impersonation routes in the platform API.
- Privilege escalation/unsafe action: per-route roles, recent authentication, explicit reason/confirmation and audit.
- Secret leakage: response minimisation and key-name redaction; environment-managed SMTP credentials.
- Status misinformation or internal leakage: enumerated public services/states and separate response construction.
- Audit destruction: no mutation API; production needs protected external export and retention controls.
- Compromised operator device or insider misuse: managed devices, least privilege, alerts, review and separation of duties.

High-impact failures include owner-account takeover, mass suspension, malicious maintenance messaging and exposure of family/children’s metadata. These require incident playbooks, independent testing and human review before launch.
