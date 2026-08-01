# Deployment and Operations

## Local foundation

1. Copy `.env.example` to `.env` and replace every placeholder with independently generated secrets.
2. Run `make up`; use `http://localhost:8080` and local-only Mailpit at `http://localhost:8025`.
3. Run `make test`, `make lint` and `make typecheck` before publishing changes.

Development HTTP is deliberately marked by `MYKHAYA_ENVIRONMENT=development` and non-secure cookies. Hosted and home-server production-like deployments use HTTPS and `compose.production.yml`; configuration refuses production startup with insecure cookies.

## Home server and VPS

Use the same immutable `web` and `api` image digests in both environments. Change only domains, secrets, SMTP, resource sizing and backup destinations. Run `docker compose -f compose.yml -f compose.production.yml config` before deployment, then `pull`, `run --rm migrate`, and `up -d`. Only ports 80/443 on Caddy are public. PostgreSQL and Redis remain on an internal network and the host firewall denies them.

For Cloudflare, restrict origin ingress to Cloudflare IP ranges, configure Caddy trusted proxies from the published ranges, preserve the direct socket peer as the trust decision, and test client-IP/rate-limit behaviour before enabling proxying.

## Upgrade and rollback

1. Take and verify an off-host encrypted backup.
2. Record current image digests and migration revision.
3. Pull the candidate images, run migrations, then replace services with health-based ordering.
4. Exercise login, Home membership and a cross-Home denial check.
5. To roll back, restore prior image digests. If a migration is not backward compatible, stop writes and restore the verified pre-upgrade database backup. Never improvise schema rollback against live data.

## Release channels and tags

- Development deployments may run from `dev` and should identify themselves as non-production.
- Stable production deployments must run from `main` or a stable tag.
- Stable tags follow `vMAJOR.MINOR.PATCH` and map to the same value in `VERSION`.
- Do not publish development builds as `latest`.

If registry publishing is introduced, prefer:

- development tags: `mykhaya:dev`, optional `mykhaya:dev-<sha>`
- stable tags: `mykhaya:latest`, `mykhaya:<major>.<minor>.<patch>`, `mykhaya:<major>.<minor>`, `mykhaya:<major>`

Only advance `latest` after an approved stable release.

Containers log JSON or structured records to stdout. Alert on health failures, repeated authentication denials, queue failures, backup failures and storage capacity. Keep exactly one scheduler replica.
