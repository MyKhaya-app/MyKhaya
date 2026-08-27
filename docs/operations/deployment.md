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

## Upgrade and rollback

1. Take and verify an off-host encrypted backup.
2. Record current image digests and migration revision.
3. Pull the candidate images, run migrations, then replace services with health-based ordering.
4. Exercise login, Home membership and a cross-Home denial check.
5. To roll back, restore prior image digests. If a migration is not backward compatible, stop writes and restore the verified pre-upgrade database backup. Never improvise schema rollback against live data.

## Release ownership

Codex validates and reports `dev` readiness. Anthony alone merges `dev` to `main`, creates the matching `v<VERSION>` tag and deploys that tagged revision. Workflows validate and build; they do not publish or deploy automatically.

Containers log JSON or structured records to stdout. Alert on health failures, repeated authentication denials, queue failures, backup failures and storage capacity. Keep exactly one scheduler replica.
