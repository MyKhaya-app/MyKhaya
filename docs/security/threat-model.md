# Threat Model

## Protected assets

Accounts, sessions, Home membership, private coordination data, invitations, reminders, audit records, secrets, CI/CD integrity and backups.

## Trust boundaries

Browser, native mobile client, Caddy, FastAPI, workers, scheduler, PostgreSQL, Redis, email provider, future push provider, future external Wish List visitor, CI/CD and container registry.

## Principal threats

- Cross-Home data access
- Credential stuffing and account enumeration
- Session or invitation theft and replay
- Privilege escalation
- Mass assignment and object-property exposure
- Injection and XSS
- CSRF, open redirect and CORS misconfiguration
- SSRF through future external URLs
- Resource exhaustion and automated abuse
- Compromised dependencies or build pipeline
- Secret leakage
- Backup failure or destructive deployment
- Insufficient logging and exceptional-condition handling

Threat modelling must be updated for every new domain and public sharing feature.
