# Local Developer Workstation

This is the workflow for running MyKhaya on your own machine — a laptop or desktop,
not a shared server. It is deliberately separate from
[`dev-deployment.md`](dev-deployment.md) (the persistent, NetBird-tunnelled
development *server*) and from [`deployment.md`](deployment.md) (production). All
three use different Compose file combinations on purpose; see "Why three workflows"
below if you're unsure which one you need.

## Start

```sh
cp .env.example .env
make up
```

`make up` (and `make init`/`make reset`) automatically copies
`compose.override.yml.example` to `compose.override.yml` the first time, alongside the
existing `.env` copy — no other setup step is required. Both copied files are
untracked (`.gitignore`); edit them freely for your own machine without affecting
anyone else or getting picked up by git.

`.env.example`'s defaults use port **8080**. If that port is already taken on your
machine, change it in *two* places together:

1. `compose.override.yml`'s `MYKHAYA_DEV_HOST_PORT` (or edit the `ports:` line
   directly).
2. The matching port number in `.env`'s `MYKHAYA_ADMIN_URL`, `MYKHAYA_STATUS_URL`,
   `MYKHAYA_PUBLIC_WEB_URL`, `MYKHAYA_CORS_ORIGINS`, and `MYKHAYA_TRUSTED_HOSTS`.

(`infrastructure/caddy/Caddyfile` — the local-workstation Caddy config — itself stays
fixed at container-internal port 8080; only the host-side published port changes.)
Startup validates this alignment and fails loudly with a clear message if the two
drift apart — see `Settings.validate_admin_and_status_url_configuration` in
`apps/api/mykhaya/config.py`.

## URLs

With the default port 8080:

- Product: `http://localhost:8080`
- Control Centre: `http://admin.localhost:8080`
- Public status: `http://status.localhost:8080`
- Mailpit (loopback only): `http://localhost:8025`

## Other commands

`make down`, `make logs`, `make build`, `make backend-rebuild`, `make migrate`,
`make test`, `make lint`, `make typecheck`, `make seed`. `make reset` recreates the
stack **and drops all local data volumes** (`docker compose down -v`) — only use it
when you want a genuinely empty database.

## Why three workflows

| | Compose files | Caddy port publish | Hostnames |
|---|---|---|---|
| **Local workstation** (this doc) | `compose.yml` + `compose.override.yml` (auto-merged, no `-f` flags — plain `docker compose`/`make up`) | `compose.override.yml`, host-only | `localhost`, `admin.localhost`, `status.localhost` |
| **Persistent dev server** ([dev-deployment.md](dev-deployment.md)) | `compose.yml` + `compose.dev.yml` explicitly (`-f compose.yml -f compose.dev.yml`) — **never** `compose.override.yml` | `compose.dev.yml`, `MYKHAYA_DEV_HOST_PORT`/`MYKHAYA_DEV_BIND_ADDRESS` | `dev.mykhaya.app` + subdomains, behind NetBird Proxy HTTPS |
| **Production** ([deployment.md](deployment.md)) | `compose.yml` + `compose.production.yml` | `compose.production.yml`/reverse proxy | real domains, HTTPS only |

`compose.override.yml` and `compose.dev.yml` are never combined — each targets a
different, single environment. If you find yourself passing `-f` flags by hand to get
the app running locally, something has drifted from this table; fix the relevant
Compose file instead of memorizing a longer command.
