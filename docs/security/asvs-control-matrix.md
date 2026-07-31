# ASVS 5.0.0 Level 2 Control Matrix

Target: **OWASP ASVS 5.0.0 Level 2**. Generated from the official stable English CSV pinned in this repository. The source is OWASP ASVS, licensed CC BY-SA 4.0. Requirement text remains in the attributed CSV; this matrix uses stable identifiers and section names.

This is a coverage inventory, not a compliance claim. â€œImplementedâ€ records current code evidence only. Controls marked â€œNot assessedâ€ require design review, test evidence, an applicability decision, and where appropriate independent verification before hosted release.

| Requirement | Level | Area | Implementation | Evidence | Status |
|---|---:|---|---|---|---|
| v5.0.0-V1.1.1 | 2 | Encoding and Sanitization Architecture | Review required | TBD | Not assessed |
| v5.0.0-V1.1.2 | 2 | Encoding and Sanitization Architecture | Review required | TBD | Not assessed |
| v5.0.0-V1.2.1 | 1 | Injection Prevention | Review required | TBD | Not assessed |
| v5.0.0-V1.2.2 | 1 | Injection Prevention | Review required | TBD | Not assessed |
| v5.0.0-V1.2.3 | 1 | Injection Prevention | Review required | TBD | Not assessed |
| v5.0.0-V1.2.4 | 1 | Injection Prevention | SQLAlchemy parameterised expressions and no raw user-built SQL | apps/api/mykhaya/**/*.py | Implemented; verification pending |
| v5.0.0-V1.2.5 | 1 | Injection Prevention | Review required | TBD | Not assessed |
| v5.0.0-V1.2.6 | 2 | Injection Prevention | Review required | TBD | Not assessed |
| v5.0.0-V1.2.7 | 2 | Injection Prevention | Review required | TBD | Not assessed |
| v5.0.0-V1.2.8 | 2 | Injection Prevention | Review required | TBD | Not assessed |
| v5.0.0-V1.2.9 | 2 | Injection Prevention | Review required | TBD | Not assessed |
| v5.0.0-V1.3.1 | 1 | Sanitization | Review required | TBD | Not assessed |
| v5.0.0-V1.3.2 | 1 | Sanitization | Review required | TBD | Not assessed |
| v5.0.0-V1.3.3 | 2 | Sanitization | Review required | TBD | Not assessed |
| v5.0.0-V1.3.4 | 2 | Sanitization | Review required | TBD | Not assessed |
| v5.0.0-V1.3.5 | 2 | Sanitization | Review required | TBD | Not assessed |
| v5.0.0-V1.3.6 | 2 | Sanitization | Review required | TBD | Not assessed |
| v5.0.0-V1.3.7 | 2 | Sanitization | Review required | TBD | Not assessed |
| v5.0.0-V1.3.8 | 2 | Sanitization | Review required | TBD | Not assessed |
| v5.0.0-V1.3.9 | 2 | Sanitization | Review required | TBD | Not assessed |
| v5.0.0-V1.3.10 | 2 | Sanitization | Review required | TBD | Not assessed |
| v5.0.0-V1.3.11 | 2 | Sanitization | Review required | TBD | Not assessed |
| v5.0.0-V1.4.1 | 2 | Memory, String, and Unmanaged Code | Review required | TBD | Not assessed |
| v5.0.0-V1.4.2 | 2 | Memory, String, and Unmanaged Code | Review required | TBD | Not assessed |
| v5.0.0-V1.4.3 | 2 | Memory, String, and Unmanaged Code | Review required | TBD | Not assessed |
| v5.0.0-V1.5.1 | 1 | Safe Deserialization | Review required | TBD | Not assessed |
| v5.0.0-V1.5.2 | 2 | Safe Deserialization | Review required | TBD | Not assessed |
| v5.0.0-V2.1.1 | 1 | Validation and Business Logic Documentation | Review required | TBD | Not assessed |
| v5.0.0-V2.1.2 | 2 | Validation and Business Logic Documentation | Review required | TBD | Not assessed |
| v5.0.0-V2.1.3 | 2 | Validation and Business Logic Documentation | Review required | TBD | Not assessed |
| v5.0.0-V2.2.1 | 1 | Input Validation | Strict Pydantic request models with explicit lengths and enums | apps/api/mykhaya/schemas.py; test_journey.py | Implemented; automated evidence |
| v5.0.0-V2.2.2 | 1 | Input Validation | All security validation is repeated server-side | apps/api/mykhaya/schemas.py | Implemented; automated evidence |
| v5.0.0-V2.2.3 | 2 | Input Validation | Review required | TBD | Not assessed |
| v5.0.0-V2.3.1 | 1 | Business Logic Security | Review required | TBD | Not assessed |
| v5.0.0-V2.3.2 | 2 | Business Logic Security | Review required | TBD | Not assessed |
| v5.0.0-V2.3.3 | 2 | Business Logic Security | Related writes and outbox events share database transactions | routers/*.py; audit.py | Implemented; automated evidence |
| v5.0.0-V2.3.4 | 2 | Business Logic Security | Review required | TBD | Not assessed |
| v5.0.0-V2.4.1 | 2 | Anti-automation | Redis-backed bounded authentication and registration rate limits | rate_limit.py | Implemented; operational evidence pending |
| v5.0.0-V3.2.1 | 1 | Unintended Content Interpretation | Review required | TBD | Not assessed |
| v5.0.0-V3.2.2 | 1 | Unintended Content Interpretation | Review required | TBD | Not assessed |
| v5.0.0-V3.3.1 | 1 | Cookie Setup | Review required | TBD | Not assessed |
| v5.0.0-V3.3.2 | 2 | Cookie Setup | SameSite=Lax cookies and double-submit CSRF | security.py; test_journey.py | Implemented; automated evidence |
| v5.0.0-V3.3.3 | 2 | Cookie Setup | Review required | TBD | Not assessed |
| v5.0.0-V3.3.4 | 2 | Cookie Setup | Opaque session token is HttpOnly | security.py; test_journey.py | Implemented; automated evidence |
| v5.0.0-V3.4.1 | 1 | Browser Security Mechanism Headers | One-year includeSubDomains HSTS at production Caddy origin | Caddyfile.production | Implemented; deployment evidence pending |
| v5.0.0-V3.4.2 | 1 | Browser Security Mechanism Headers | Fixed origin allow-list in FastAPI and unsafe-request middleware | main.py; test_journey.py | Implemented; automated evidence |
| v5.0.0-V3.4.3 | 2 | Browser Security Mechanism Headers | Review required | TBD | Not assessed |
| v5.0.0-V3.4.4 | 2 | Browser Security Mechanism Headers | Review required | TBD | Not assessed |
| v5.0.0-V3.4.5 | 2 | Browser Security Mechanism Headers | Review required | TBD | Not assessed |
| v5.0.0-V3.4.6 | 2 | Browser Security Mechanism Headers | Review required | TBD | Not assessed |
| v5.0.0-V3.5.1 | 1 | Browser Origin Separation | Review required | TBD | Not assessed |
| v5.0.0-V3.5.2 | 1 | Browser Origin Separation | Review required | TBD | Not assessed |
| v5.0.0-V3.5.3 | 1 | Browser Origin Separation | Review required | TBD | Not assessed |
| v5.0.0-V3.5.4 | 2 | Browser Origin Separation | Review required | TBD | Not assessed |
| v5.0.0-V3.5.5 | 2 | Browser Origin Separation | Review required | TBD | Not assessed |
| v5.0.0-V3.7.1 | 2 | Other Browser Security Considerations | Review required | TBD | Not assessed |
| v5.0.0-V3.7.2 | 2 | Other Browser Security Considerations | Review required | TBD | Not assessed |
| v5.0.0-V4.1.1 | 1 | Generic Web Service Security | Review required | TBD | Not assessed |
| v5.0.0-V4.1.2 | 2 | Generic Web Service Security | Review required | TBD | Not assessed |
| v5.0.0-V4.1.3 | 2 | Generic Web Service Security | Review required | TBD | Not assessed |
| v5.0.0-V4.2.1 | 2 | HTTP Message Structure Validation | Central current-membership Home authorisation | dependencies.py; test_journey.py | Implemented; automated evidence |
| v5.0.0-V4.3.1 | 2 | GraphQL | Owner/administrator function checks are server-side | routers/groups.py; routers/invitations.py | Implemented; automated evidence |
| v5.0.0-V4.3.2 | 2 | GraphQL | Review required | TBD | Not assessed |
| v5.0.0-V4.4.1 | 1 | WebSocket | Review required | TBD | Not assessed |
| v5.0.0-V4.4.2 | 2 | WebSocket | Review required | TBD | Not assessed |
| v5.0.0-V4.4.3 | 2 | WebSocket | Review required | TBD | Not assessed |
| v5.0.0-V4.4.4 | 2 | WebSocket | Review required | TBD | Not assessed |
| v5.0.0-V5.1.1 | 2 | File Handling Documentation | Review required | TBD | Not assessed |
| v5.0.0-V5.2.1 | 1 | File Upload and Content | Review required | TBD | Not assessed |
| v5.0.0-V5.2.2 | 1 | File Upload and Content | Review required | TBD | Not assessed |
| v5.0.0-V5.2.3 | 2 | File Upload and Content | Review required | TBD | Not assessed |
| v5.0.0-V5.3.1 | 1 | File Storage | Review required | TBD | Not assessed |
| v5.0.0-V5.3.2 | 1 | File Storage | Review required | TBD | Not assessed |
| v5.0.0-V5.4.1 | 2 | File Download | Review required | TBD | Not assessed |
| v5.0.0-V5.4.2 | 2 | File Download | Review required | TBD | Not assessed |
| v5.0.0-V5.4.3 | 2 | File Download | Review required | TBD | Not assessed |
| v5.0.0-V6.1.1 | 1 | Authentication Documentation | Review required | TBD | Not assessed |
| v5.0.0-V6.1.2 | 2 | Authentication Documentation | Review required | TBD | Not assessed |
| v5.0.0-V6.1.3 | 2 | Authentication Documentation | Review required | TBD | Not assessed |
| v5.0.0-V6.2.1 | 1 | Password Security | Argon2 password hashing through pwdlib recommended profile | security.py | Implemented; verification pending |
| v5.0.0-V6.2.2 | 1 | Password Security | Review required | TBD | Not assessed |
| v5.0.0-V6.2.3 | 1 | Password Security | Review required | TBD | Not assessed |
| v5.0.0-V6.2.4 | 1 | Password Security | Review required | TBD | Not assessed |
| v5.0.0-V6.2.5 | 1 | Password Security | Review required | TBD | Not assessed |
| v5.0.0-V6.2.6 | 1 | Password Security | Review required | TBD | Not assessed |
| v5.0.0-V6.2.7 | 1 | Password Security | Review required | TBD | Not assessed |
| v5.0.0-V6.2.8 | 1 | Password Security | Review required | TBD | Not assessed |
| v5.0.0-V6.2.9 | 2 | Password Security | Review required | TBD | Not assessed |
| v5.0.0-V6.2.10 | 2 | Password Security | Review required | TBD | Not assessed |
| v5.0.0-V6.2.11 | 2 | Password Security | Review required | TBD | Not assessed |
| v5.0.0-V6.2.12 | 2 | Password Security | Review required | TBD | Not assessed |
| v5.0.0-V6.3.1 | 1 | General Authentication Security | Review required | TBD | Not assessed |
| v5.0.0-V6.3.2 | 1 | General Authentication Security | Review required | TBD | Not assessed |
| v5.0.0-V6.3.3 | 2 | General Authentication Security | Review required | TBD | Not assessed |
| v5.0.0-V6.3.4 | 2 | General Authentication Security | Review required | TBD | Not assessed |
| v5.0.0-V6.4.1 | 1 | Authentication Factor Lifecycle and Recovery | Review required | TBD | Not assessed |
| v5.0.0-V6.4.2 | 1 | Authentication Factor Lifecycle and Recovery | Review required | TBD | Not assessed |
| v5.0.0-V6.4.3 | 2 | Authentication Factor Lifecycle and Recovery | Review required | TBD | Not assessed |
| v5.0.0-V6.4.4 | 2 | Authentication Factor Lifecycle and Recovery | Review required | TBD | Not assessed |
| v5.0.0-V6.5.1 | 2 | General Multi-factor authentication requirements | Review required | TBD | Not assessed |
| v5.0.0-V6.5.2 | 2 | General Multi-factor authentication requirements | Review required | TBD | Not assessed |
| v5.0.0-V6.5.3 | 2 | General Multi-factor authentication requirements | Review required | TBD | Not assessed |
| v5.0.0-V6.5.4 | 2 | General Multi-factor authentication requirements | Review required | TBD | Not assessed |
| v5.0.0-V6.5.5 | 2 | General Multi-factor authentication requirements | Review required | TBD | Not assessed |
| v5.0.0-V6.6.1 | 2 | Out-of-Band authentication mechanisms | Review required | TBD | Not assessed |
| v5.0.0-V6.6.2 | 2 | Out-of-Band authentication mechanisms | Review required | TBD | Not assessed |
| v5.0.0-V6.6.3 | 2 | Out-of-Band authentication mechanisms | Review required | TBD | Not assessed |
| v5.0.0-V6.8.1 | 2 | Authentication with an Identity Provider | Review required | TBD | Not assessed |
| v5.0.0-V6.8.2 | 2 | Authentication with an Identity Provider | Review required | TBD | Not assessed |
| v5.0.0-V6.8.3 | 2 | Authentication with an Identity Provider | Review required | TBD | Not assessed |
| v5.0.0-V6.8.4 | 2 | Authentication with an Identity Provider | Review required | TBD | Not assessed |
| v5.0.0-V7.1.1 | 2 | Session Management Documentation | Review required | TBD | Not assessed |
| v5.0.0-V7.1.2 | 2 | Session Management Documentation | Review required | TBD | Not assessed |
| v5.0.0-V7.1.3 | 2 | Session Management Documentation | Review required | TBD | Not assessed |
| v5.0.0-V7.2.1 | 1 | Fundamental Session Management Security | Opaque high-entropy session identifiers stored as keyed hashes | security.py; models.py | Implemented; automated evidence |
| v5.0.0-V7.2.2 | 1 | Fundamental Session Management Security | Review required | TBD | Not assessed |
| v5.0.0-V7.2.3 | 1 | Fundamental Session Management Security | Review required | TBD | Not assessed |
| v5.0.0-V7.2.4 | 1 | Fundamental Session Management Security | Review required | TBD | Not assessed |
| v5.0.0-V7.3.1 | 2 | Session Timeout | Review required | TBD | Not assessed |
| v5.0.0-V7.3.2 | 2 | Session Timeout | Review required | TBD | Not assessed |
| v5.0.0-V7.4.1 | 1 | Session Termination | Session revocation and password-reset global revocation | routers/auth.py; test_journey.py | Implemented; automated evidence |
| v5.0.0-V7.4.2 | 1 | Session Termination | Explicit session rotation endpoint revokes predecessor | routers/auth.py; test_journey.py | Implemented; automated evidence |
| v5.0.0-V7.4.3 | 2 | Session Termination | Review required | TBD | Not assessed |
| v5.0.0-V7.4.4 | 2 | Session Termination | Review required | TBD | Not assessed |
| v5.0.0-V7.4.5 | 2 | Session Termination | Review required | TBD | Not assessed |
| v5.0.0-V7.5.1 | 2 | Defenses Against Session Abuse | Review required | TBD | Not assessed |
| v5.0.0-V7.5.2 | 2 | Defenses Against Session Abuse | Review required | TBD | Not assessed |
| v5.0.0-V7.6.1 | 2 | Federated Re-authentication | Review required | TBD | Not assessed |
| v5.0.0-V7.6.2 | 2 | Federated Re-authentication | Review required | TBD | Not assessed |
| v5.0.0-V8.1.1 | 1 | Authorization Documentation | Review required | TBD | Not assessed |
| v5.0.0-V8.1.2 | 2 | Authorization Documentation | Review required | TBD | Not assessed |
| v5.0.0-V8.2.1 | 1 | General Authorization Design | CSRF token and allowed Origin required on cookie-authenticated unsafe methods | security.py; test_journey.py | Implemented; automated evidence |
| v5.0.0-V8.2.2 | 1 | General Authorization Design | Review required | TBD | Not assessed |
| v5.0.0-V8.2.3 | 2 | General Authorization Design | Review required | TBD | Not assessed |
| v5.0.0-V8.3.1 | 1 | Operation Level Authorization | Review required | TBD | Not assessed |
| v5.0.0-V8.4.1 | 2 | Other Authorization Considerations | Review required | TBD | Not assessed |
| v5.0.0-V9.1.1 | 1 | Token source and integrity | TLS termination and HSTS are production defaults | Caddyfile.production; compose.production.yml | Implemented; deployment evidence pending |
| v5.0.0-V9.1.2 | 1 | Token source and integrity | Review required | TBD | Not assessed |
| v5.0.0-V9.1.3 | 1 | Token source and integrity | Review required | TBD | Not assessed |
| v5.0.0-V9.2.1 | 1 | Token content | Review required | TBD | Not assessed |
| v5.0.0-V9.2.2 | 2 | Token content | Review required | TBD | Not assessed |
| v5.0.0-V9.2.3 | 2 | Token content | Review required | TBD | Not assessed |
| v5.0.0-V9.2.4 | 2 | Token content | Review required | TBD | Not assessed |
| v5.0.0-V10.1.1 | 2 | Generic OAuth and OIDC Security | Review required | TBD | Not assessed |
| v5.0.0-V10.1.2 | 2 | Generic OAuth and OIDC Security | Review required | TBD | Not assessed |
| v5.0.0-V10.2.1 | 2 | OAuth Client | Reusable action and invitation tokens stored only as keyed hashes | security.py; models.py | Implemented; automated evidence |
| v5.0.0-V10.2.2 | 2 | OAuth Client | Review required | TBD | Not assessed |
| v5.0.0-V10.3.1 | 2 | OAuth Resource Server | Review required | TBD | Not assessed |
| v5.0.0-V10.3.2 | 2 | OAuth Resource Server | Review required | TBD | Not assessed |
| v5.0.0-V10.3.3 | 2 | OAuth Resource Server | Review required | TBD | Not assessed |
| v5.0.0-V10.3.4 | 2 | OAuth Resource Server | Review required | TBD | Not assessed |
| v5.0.0-V10.4.1 | 1 | OAuth Authorization Server | Review required | TBD | Not assessed |
| v5.0.0-V10.4.2 | 1 | OAuth Authorization Server | Review required | TBD | Not assessed |
| v5.0.0-V10.4.3 | 1 | OAuth Authorization Server | Review required | TBD | Not assessed |
| v5.0.0-V10.4.4 | 1 | OAuth Authorization Server | Review required | TBD | Not assessed |
| v5.0.0-V10.4.5 | 1 | OAuth Authorization Server | Review required | TBD | Not assessed |
| v5.0.0-V10.4.6 | 2 | OAuth Authorization Server | Review required | TBD | Not assessed |
| v5.0.0-V10.4.7 | 2 | OAuth Authorization Server | Review required | TBD | Not assessed |
| v5.0.0-V10.4.8 | 2 | OAuth Authorization Server | Review required | TBD | Not assessed |
| v5.0.0-V10.4.9 | 2 | OAuth Authorization Server | Review required | TBD | Not assessed |
| v5.0.0-V10.4.10 | 2 | OAuth Authorization Server | Review required | TBD | Not assessed |
| v5.0.0-V10.4.11 | 2 | OAuth Authorization Server | Review required | TBD | Not assessed |
| v5.0.0-V10.5.1 | 2 | OIDC Client | Review required | TBD | Not assessed |
| v5.0.0-V10.5.2 | 2 | OIDC Client | Review required | TBD | Not assessed |
| v5.0.0-V10.5.3 | 2 | OIDC Client | Review required | TBD | Not assessed |
| v5.0.0-V10.5.4 | 2 | OIDC Client | Review required | TBD | Not assessed |
| v5.0.0-V10.5.5 | 2 | OIDC Client | Review required | TBD | Not assessed |
| v5.0.0-V10.6.1 | 2 | OpenID Provider | Review required | TBD | Not assessed |
| v5.0.0-V10.6.2 | 2 | OpenID Provider | Review required | TBD | Not assessed |
| v5.0.0-V10.7.1 | 2 | Consent Management | Review required | TBD | Not assessed |
| v5.0.0-V10.7.2 | 2 | Consent Management | Review required | TBD | Not assessed |
| v5.0.0-V10.7.3 | 2 | Consent Management | Review required | TBD | Not assessed |
| v5.0.0-V11.1.1 | 2 | Cryptographic Inventory and Documentation | Structured audit events for auth, membership and invitation changes | audit.py; routers/*.py | Implemented; verification pending |
| v5.0.0-V11.1.2 | 2 | Cryptographic Inventory and Documentation | Review required | TBD | Not assessed |
| v5.0.0-V11.2.1 | 2 | Secure Cryptography Implementation | Review required | TBD | Not assessed |
| v5.0.0-V11.2.2 | 2 | Secure Cryptography Implementation | Review required | TBD | Not assessed |
| v5.0.0-V11.2.3 | 2 | Secure Cryptography Implementation | Review required | TBD | Not assessed |
| v5.0.0-V11.3.1 | 1 | Encryption Algorithms | Review required | TBD | Not assessed |
| v5.0.0-V11.3.2 | 1 | Encryption Algorithms | Review required | TBD | Not assessed |
| v5.0.0-V11.3.3 | 2 | Encryption Algorithms | Review required | TBD | Not assessed |
| v5.0.0-V11.4.1 | 1 | Hashing and Hash-based Functions | Review required | TBD | Not assessed |
| v5.0.0-V11.4.2 | 2 | Hashing and Hash-based Functions | Review required | TBD | Not assessed |
| v5.0.0-V11.4.3 | 2 | Hashing and Hash-based Functions | Review required | TBD | Not assessed |
| v5.0.0-V11.4.4 | 2 | Hashing and Hash-based Functions | Review required | TBD | Not assessed |
| v5.0.0-V11.5.1 | 2 | Random Values | Review required | TBD | Not assessed |
| v5.0.0-V11.6.1 | 2 | Public Key Cryptography | Review required | TBD | Not assessed |
| v5.0.0-V12.1.1 | 1 | General TLS Security Guidance | Review required | TBD | Not assessed |
| v5.0.0-V12.1.2 | 2 | General TLS Security Guidance | Review required | TBD | Not assessed |
| v5.0.0-V12.1.3 | 2 | General TLS Security Guidance | Review required | TBD | Not assessed |
| v5.0.0-V12.2.1 | 1 | HTTPS Communication with External Facing Services | Review required | TBD | Not assessed |
| v5.0.0-V12.2.2 | 1 | HTTPS Communication with External Facing Services | Review required | TBD | Not assessed |
| v5.0.0-V12.3.1 | 2 | General Service to Service Communication Security | Review required | TBD | Not assessed |
| v5.0.0-V12.3.2 | 2 | General Service to Service Communication Security | Review required | TBD | Not assessed |
| v5.0.0-V12.3.3 | 2 | General Service to Service Communication Security | Review required | TBD | Not assessed |
| v5.0.0-V12.3.4 | 2 | General Service to Service Communication Security | Review required | TBD | Not assessed |
| v5.0.0-V13.1.1 | 2 | Configuration Documentation | Minimal API response models separate from persistence models | schemas.py; routers/*.py | Implemented; automated evidence |
| v5.0.0-V13.2.1 | 2 | Backend Communication Configuration | Strict request schemas reject unknown properties | schemas.py; test_journey.py | Implemented; automated evidence |
| v5.0.0-V13.2.2 | 2 | Backend Communication Configuration | Review required | TBD | Not assessed |
| v5.0.0-V13.2.3 | 2 | Backend Communication Configuration | Review required | TBD | Not assessed |
| v5.0.0-V13.2.4 | 2 | Backend Communication Configuration | Review required | TBD | Not assessed |
| v5.0.0-V13.2.5 | 2 | Backend Communication Configuration | Review required | TBD | Not assessed |
| v5.0.0-V13.3.1 | 2 | Secret Management | Review required | TBD | Not assessed |
| v5.0.0-V13.3.2 | 2 | Secret Management | Review required | TBD | Not assessed |
| v5.0.0-V13.4.1 | 1 | Unintended Information Leakage | Review required | TBD | Not assessed |
| v5.0.0-V13.4.2 | 2 | Unintended Information Leakage | Review required | TBD | Not assessed |
| v5.0.0-V13.4.3 | 2 | Unintended Information Leakage | Review required | TBD | Not assessed |
| v5.0.0-V13.4.4 | 2 | Unintended Information Leakage | Review required | TBD | Not assessed |
| v5.0.0-V13.4.5 | 2 | Unintended Information Leakage | Review required | TBD | Not assessed |
| v5.0.0-V14.1.1 | 2 | Data Protection Documentation | Review required | TBD | Not assessed |
| v5.0.0-V14.1.2 | 2 | Data Protection Documentation | Review required | TBD | Not assessed |
| v5.0.0-V14.2.1 | 1 | General Data Protection | Review required | TBD | Not assessed |
| v5.0.0-V14.2.2 | 2 | General Data Protection | Review required | TBD | Not assessed |
| v5.0.0-V14.2.3 | 2 | General Data Protection | Review required | TBD | Not assessed |
| v5.0.0-V14.2.4 | 2 | General Data Protection | Review required | TBD | Not assessed |
| v5.0.0-V14.3.1 | 1 | Client-side Data Protection | Review required | TBD | Not assessed |
| v5.0.0-V14.3.2 | 2 | Client-side Data Protection | Review required | TBD | Not assessed |
| v5.0.0-V14.3.3 | 2 | Client-side Data Protection | Review required | TBD | Not assessed |
| v5.0.0-V15.1.1 | 1 | Secure Coding and Architecture Documentation | Review required | TBD | Not assessed |
| v5.0.0-V15.1.2 | 2 | Secure Coding and Architecture Documentation | Review required | TBD | Not assessed |
| v5.0.0-V15.1.3 | 2 | Secure Coding and Architecture Documentation | Review required | TBD | Not assessed |
| v5.0.0-V15.2.1 | 1 | Security Architecture and Dependencies | Review required | TBD | Not assessed |
| v5.0.0-V15.2.2 | 2 | Security Architecture and Dependencies | Review required | TBD | Not assessed |
| v5.0.0-V15.2.3 | 2 | Security Architecture and Dependencies | Review required | TBD | Not assessed |
| v5.0.0-V15.3.1 | 1 | Defensive Coding | Review required | TBD | Not assessed |
| v5.0.0-V15.3.2 | 2 | Defensive Coding | Review required | TBD | Not assessed |
| v5.0.0-V15.3.3 | 2 | Defensive Coding | Review required | TBD | Not assessed |
| v5.0.0-V15.3.4 | 2 | Defensive Coding | Review required | TBD | Not assessed |
| v5.0.0-V15.3.5 | 2 | Defensive Coding | Review required | TBD | Not assessed |
| v5.0.0-V15.3.6 | 2 | Defensive Coding | Review required | TBD | Not assessed |
| v5.0.0-V15.3.7 | 2 | Defensive Coding | Review required | TBD | Not assessed |
| v5.0.0-V16.1.1 | 2 | Security Logging Documentation | Review required | TBD | Not assessed |
| v5.0.0-V16.2.1 | 2 | General Logging | Review required | TBD | Not assessed |
| v5.0.0-V16.2.2 | 2 | General Logging | Review required | TBD | Not assessed |
| v5.0.0-V16.2.3 | 2 | General Logging | Review required | TBD | Not assessed |
| v5.0.0-V16.2.4 | 2 | General Logging | Review required | TBD | Not assessed |
| v5.0.0-V16.2.5 | 2 | General Logging | Review required | TBD | Not assessed |
| v5.0.0-V16.3.1 | 2 | Security Events | Review required | TBD | Not assessed |
| v5.0.0-V16.3.2 | 2 | Security Events | Review required | TBD | Not assessed |
| v5.0.0-V16.3.3 | 2 | Security Events | Review required | TBD | Not assessed |
| v5.0.0-V16.3.4 | 2 | Security Events | Review required | TBD | Not assessed |
| v5.0.0-V16.4.1 | 2 | Log Protection | Review required | TBD | Not assessed |
| v5.0.0-V16.4.2 | 2 | Log Protection | Review required | TBD | Not assessed |
| v5.0.0-V16.4.3 | 2 | Log Protection | Review required | TBD | Not assessed |
| v5.0.0-V16.5.1 | 2 | Error Handling | Review required | TBD | Not assessed |
| v5.0.0-V16.5.2 | 2 | Error Handling | Review required | TBD | Not assessed |
| v5.0.0-V16.5.3 | 2 | Error Handling | Review required | TBD | Not assessed |
| v5.0.0-V17.1.1 | 2 | TURN Server | Review required | TBD | Not assessed |
| v5.0.0-V17.2.1 | 2 | Media | Review required | TBD | Not assessed |
| v5.0.0-V17.2.2 | 2 | Media | Review required | TBD | Not assessed |
| v5.0.0-V17.2.3 | 2 | Media | Review required | TBD | Not assessed |
| v5.0.0-V17.2.4 | 2 | Media | Review required | TBD | Not assessed |
| v5.0.0-V17.3.1 | 2 | Signaling | Review required | TBD | Not assessed |
| v5.0.0-V17.3.2 | 2 | Signaling | Review required | TBD | Not assessed |

Inventory count: 253 Level 1/2 requirements. Regenerate with `powershell -File infrastructure/scripts/generate-asvs-matrix.ps1`.
