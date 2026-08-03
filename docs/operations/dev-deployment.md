# Persistent Development Deployment

This is the supported deployment path for the long-running `dev` server. It uses
`compose.yml` as the shared base and the tracked `compose.dev.yml` overlay. It does not
use `compose.override.yml`. PostgreSQL and Redis remain on Docker-internal networks,
Mailpit binds only to loopback, and Caddy exposes one configurable HTTP origin for an
external HTTPS reverse proxy.

## First installation

Requirements are Git, GNU Make, Docker Engine with Docker Compose v2, Python 3, and
either `curl` or `wget`.

```sh
git clone --branch dev https://github.com/MyKhaya-app/MyKhaya.git
cd MyKhaya
cp .env.dev.example .env
nano .env
make dev-up
```

Replace every `CHANGE_ME` value with an independently generated secret. Restrict
`MYKHAYA_ADMIN_ALLOWED_NETWORKS` to the operator NetBird addresses that may use the
Control Centre, preferably explicit `/32` entries. Set
`MYKHAYA_DEV_PROXY_TRUSTED_CIDRS` to the exact NetBird Proxy peer `/32` where possible.
The broader `100.64.0.0/10` examples are functional defaults, not the preferred final
allow-list.

`make dev-up` validates the host, builds all images without stopping a running stack,
starts and checks the private data services, runs Alembic migrations, replaces the app
services, prints container status, and verifies liveness and readiness. The public URLs
are HTTPS, so secure cookies remain enabled even though NetBird Proxy connects to Caddy
over HTTP.

## DNS and NetBird Proxy

Create or delegate these names to NetBird Proxy:

- `dev.mykhaya.app`
- `admin.dev.mykhaya.app`
- `status.dev.mykhaya.app`

Configure three HTTPS proxy routes and preserve the incoming `Host` header:

```text
dev.mykhaya.app        -> http://SERVER_NETBIRD_IP:8080
admin.dev.mykhaya.app  -> http://SERVER_NETBIRD_IP:8080
status.dev.mykhaya.app -> http://SERVER_NETBIRD_IP:8080
```

Change `8080` in both NetBird and `MYKHAYA_DEV_HOST_PORT` if the default is unavailable.
Keep `MYKHAYA_DEV_BIND_ADDRESS=0.0.0.0`, or bind to the server's specific NetBird IP.
Do not expose this HTTP port to the public internet; allow it only over NetBird or the
host firewall.

The tracked development Caddyfile accepts only the three development hosts plus
`localhost`/`127.0.0.1`. Caddy trusts incoming forwarded client information only from
`MYKHAYA_DEV_PROXY_TRUSTED_CIDRS`, replaces rather than blindly passes the upstream
forwarding headers, preserves `Host`, and tells the application that public requests
used HTTPS. The API independently trusts forwarding only from its private Docker proxy
network.

## Updating

Maintain a current, verified backup as described below. The complete update command is:

```sh
make dev-update
```

The command requires the local `dev` branch and a clean working tree, apart from ignored
local `.env` secret files. It fetches `origin/dev`, fast-forwards only, reports settings
that were added to `.env.dev.example`, builds images, runs migrations, starts the updated
services, and performs health checks. It never invokes `docker compose down -v`, deletes
a volume, or requires local edits to tracked deployment files.

If a newly required setting is reported, compare `.env.dev.example` with `.env`, add the
setting, and rerun `make dev-update`. A non-fast-forward update stops before deployment
and must be investigated rather than merged on the server.

## Logs and health checks

```sh
make dev-logs
make dev-health
docker compose -f compose.yml -f compose.dev.yml ps
```

Direct server checks intentionally use the `localhost` Caddy site:

```sh
curl -fsS http://127.0.0.1:8080/api/v1/health/live
curl -fsS http://127.0.0.1:8080/api/v1/health/ready
curl -fsS http://127.0.0.1:8080/api/v1/health/build
```

Mailpit is available only on the server at `http://127.0.0.1:8025` by default. Use an
SSH or NetBird tunnel if remote operator access is necessary; do not bind it publicly.

## Backups

Run `make backup`, verify the resulting gzip file, and copy it off-host using encrypted
transport and storage. A backup is only dependable after a documented restore test; see
`docs/operations/backup-and-restore.md`. PostgreSQL is authoritative. Redis is disposable
coordination state and is not a database backup.

## Failure behavior and rollback

Image builds complete before any currently running container is replaced. If a build
fails, the old stack continues to run. Migrations run before new API, worker, scheduler,
or web containers are started. If a migration fails, rollout stops and the previous app
containers remain in place. Alembic and PostgreSQL normally make each migration
transactional, but an unsuccessful migration still requires inspection: check the
`migrate` output, the Alembic revision, and database health before retrying.

The update command prints the previous commit as its rollback reference. For a
code-only rollback where the migrated schema is backward-compatible:

```sh
git switch --detach PREVIOUS_COMMIT
MYKHAYA_DEV_ALLOW_NON_DEV_BRANCH=1 make dev-up
```

After the incident, return the checkout to the supported update path with `git switch
dev`. Do not run an Alembic downgrade against live data merely to force old code to work.
If the new schema is not backward-compatible, stop writes and restore the verified
pre-update PostgreSQL backup, then deploy the previous commit. This is why backups must
precede schema-changing updates.

`make dev-down` uses `docker compose stop`; it does not remove containers, networks, or
persistent volumes.

## Troubleshooting

- **Missing `.env` or variables:** copy `.env.dev.example`, preserve existing secrets,
  and add the reported keys. Never commit `.env`.
- **Invalid JSON:** JSON list settings must use double-quoted strings, for example
  `["100.64.0.10/32"]`.
- **Occupied port:** change `MYKHAYA_DEV_HOST_PORT` or
  `MYKHAYA_DEV_MAILPIT_PORT`, or stop the unrelated listener. Preflight recognises ports
  already owned by this Compose project.
- **Docker unavailable:** start Docker Engine and confirm `docker info` and `docker
  compose version` work for the deployment account.
- **Wrong branch or dirty deployment files:** return to `dev` and restore tracked files
  from Git. Keep server-specific changes only in `.env`.
- **502 or failed readiness:** run `make dev-logs`, then inspect `api`, `web`, `postgres`,
  `redis`, and `caddy` health. Readiness requires both PostgreSQL and Redis.
- **Wrong site routing:** confirm NetBird preserves the original `Host` value and uses
  the exact domain-to-origin mappings above.
- **Control Centre returns 404:** confirm the client address forwarded through NetBird
  is included in `MYKHAYA_ADMIN_ALLOWED_NETWORKS`. A 404 is the deliberate network
  boundary response.

docker compose -f compose.yml -f compose.dev.yml run --rm --no-deps \
  -e MYKHAYA_ADMIN_BOOTSTRAP_ENABLED=true \
  api python -m mykhaya.bootstrap_platform_owner \
  --email you@example.com \
  --display-name "Your Name"
