# Deployment and Operations

## Persistent development foundation

1. Copy `.env.dev.example` to `.env` and replace every placeholder with independently generated secrets.
2. Run `make dev-up`; public HTTPS is provided by NetBird Proxy and Mailpit stays local-only at `http://localhost:8025`.
3. Run `make test`, `make lint` and `make typecheck` before publishing changes.

The persistent development server uses `compose.dev.yml`, HTTPS public URLs, and secure
cookies. See `dev-deployment.md` for the supported installation and one-command update
workflow. Production deployments continue to use `compose.production.yml`; configuration
refuses production startup with insecure cookies.

## Home server and VPS

Use the same immutable `web` and `api` image digests in both environments. Change only domains, secrets, SMTP, resource sizing and backup destinations. Run `docker compose -f compose.yml -f compose.production.yml config` before deployment, then `pull`, `run --rm migrate`, and `up -d`. Only ports 80/443 on Caddy are public. PostgreSQL and Redis remain on an internal network and the host firewall denies them.

For Cloudflare, restrict origin ingress to Cloudflare IP ranges, configure Caddy trusted proxies from the published ranges, preserve the direct socket peer as the trust decision, and test client-IP/rate-limit behaviour before enabling proxying.

## New required setting before the next production deploy

`MYKHAYA_NATIVE_API_URL` (ADR 0010's direct-to-API origin for future native/bearer
clients) must be set to `https://api.mykhaya.app` in production's `.env` before the
next deploy — `Settings.validate_admin_and_status_url_configuration` now validates it
the same way as `MYKHAYA_ADMIN_URL`/`MYKHAYA_STATUS_URL` (valid https URL, host present
in `MYKHAYA_TRUSTED_HOSTS`), and its class-level default (`http://api.localhost:8080`)
fails that check in production. `api.mykhaya.app` is already served by
`infrastructure/caddy/Caddyfile.production` and already present in the default
`trusted_hosts` list, so no other production change is required — only adding this one
setting to the real, deployed `.env`.

## Driveway / DVLA integration (UAT)

Vehicle lookup credentials live only in `.env`, never in the database or a
PCC text field — see `Settings.dvla_environment`/`dvla_uat_*`/`dvla_production_*`
in `apps/api/mykhaya/config.py`. To switch environments:

1. Set `MYKHAYA_DVLA_ENVIRONMENT` to `uat` or `production` (blank/unset is a
   valid "not configured" state — no lookup provider runs, and Driveway's
   vehicle lookup always offers manual entry).
2. Fill in the matching endpoint/key pair only — `MYKHAYA_DVLA_UAT_ENDPOINT`
   + `MYKHAYA_DVLA_UAT_API_KEY`, or the `_PRODUCTION_` equivalents. There is
   no fallback between the two: an incomplete UAT configuration never uses
   the production endpoint or key, and selecting `production` never uses UAT
   credentials.
3. Redeploy (or restart `api`/`worker`/`scheduler`) so the new `.env` values
   are picked up.

PCC's Settings page (Driveway integrations card) reflects the active
environment (labelled "UAT"/"Production", never the raw value), whether an
API key is configured, the endpoint in use, current health, and the last
successful/failed lookup — the key itself is never displayed or returned by
any API response. Use its "Test connection" control (an admin-entered
registration, never persisted as a vehicle) to verify connectivity safely
before relying on the integration.

Never commit a real API key to `.env.example` or any tracked file — if one
is ever accidentally committed, rotate it with DVLA immediately and treat
the old key as compromised.

## Upgrade and rollback

1. Take and verify an off-host encrypted backup.
2. Record current image digests and migration revision.
3. Pull the candidate images, run migrations, then replace services with health-based ordering.
4. Exercise login, Home membership and a cross-Home denial check.
5. To roll back, restore prior image digests. If a migration is not backward compatible, stop writes and restore the verified pre-upgrade database backup. Never improvise schema rollback against live data.

## Release ownership

Codex validates and reports `dev` readiness. Anthony alone merges `dev` to
`main`, creates the GitHub release tag `vX.Y.Z` and deploys that tagged revision
with `make prod-update RELEASE=vX.Y.Z`. Workflows validate and build; they do
not publish or deploy automatically.

Containers log JSON or structured records to stdout. Alert on health failures, repeated authentication denials, queue failures, backup failures and storage capacity. Keep exactly one scheduler replica.
