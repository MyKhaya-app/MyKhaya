# Foundation Security Review

## Implemented controls

- Opaque high-entropy browser sessions, keyed hashes at rest, HttpOnly/SameSite cookies, CSRF double-submit and Origin validation
- Argon2 password hashing, generic account-recovery responses, single-use expiring verification/reset/invitation tokens and session revocation
- Central current-membership Home authorisation, role checks, Home-scoped queries and indistinguishable cross-Home not-found responses
- Strict request models, field/resource bounds, request IDs, safe errors, audit events and transactional outbox records
- Fixed CORS allow-list, nonce-based production script CSP, browser headers, HSTS at the production origin and no browser credential storage
- Separate migration/runtime database roles, internal-only data networks, non-root containers, dropped capabilities and read-only application filesystems
- CI gates for tests, type/lint/format/build, secrets, dependencies, SAST, containers, Compose/IaC and CycloneDX SBOM

## Awareness mapping

OWASP Top 10:2025 and API Security Top 10:2023 risks are addressed through scoped authorisation, strict schemas, ORM queries, secure configuration, dependency scans, bounded resources, flow rate limits and inventory through generated OpenAPI. OWASP Mobile Top 10:2024 is addressed at shell level by native code, SecureStore inclusion, no WebView and minimal permissions; the native authentication protocol still requires implementation and mobile security testing.

NCSC Software Security Code of Practice themes are represented by documented requirements and threat models, repeatable CI, dependency inventory/SBOM, hardened deployment, vulnerability and incident processes, and rollback/restore guidance.

## Open release blockers

- Most ASVS Level 2 controls remain formally unassessed in the generated matrix.
- MFA, account export/deletion, Home ownership transfer/deletion, retention automation, monitoring integrations and native authentication are not complete.
- Independent authorisation/session testing, WSTG testing, penetration testing and an observed off-host restore are still required before broad hosted release.
- Image signing/provenance, protected CI environments and a private vulnerability-reporting address require repository/operator configuration.

## Platform administration review

Implemented evidence includes isolated platform identities/roles/sessions, hostname and trusted-proxy-aware network gates, short idle/absolute timeouts, revocation, strict role dependencies, recent-auth/reason/confirmation checks, a dedicated redacting audit trail, privacy-minimised metadata APIs, typed settings/feature keys, internal health separation and a deliberately limited public status contract.

Open blockers are mandatory WebAuthn/passkey enrolment and verification, safe administrator lifecycle endpoints, external tamper-resistant audit export, delivery-event persistence and encrypted database-managed mail secrets, job retry idempotency registration, automated retention/rights workflows, authoritative backup/migration/capacity/performance telemetry, independently hosted status delivery and independent security/privacy/legal review. The Control Centre must not be described as production-ready.
