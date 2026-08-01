# Control Centre Deployment

1. Create DNS A/AAAA records for `mykhaya.app`, `admin.mykhaya.app` and `status.mykhaya.app` at the Caddy edge.
2. Set the three URLs/domains, exact trusted-proxy range and explicit admin source CIDRs.
3. Leave PostgreSQL, Redis, API, worker and scheduler on internal Compose networks.
4. Run Alembic upgrade, deploy all processes, and verify hostname isolation and secure cookie attributes.
5. Enable bootstrap briefly, run `docker compose exec api python -m mykhaya.bootstrap_platform_owner --email ... --display-name ...`, then disable bootstrap and restart.
6. Complete WebAuthn implementation/enrolment before enabling production operator access.

Recommended controls: VPN or identity-aware gateway, hardware keys, restricted patched devices, least-privilege operator accounts, centralized logs/alerts, and an approved break-glass credential held offline with two-person use and immediate rotation/review.

Rollback must preserve migration data. Rolling back application code does not imply dropping platform tables.
