# MyKhaya

> **Your family’s digital home.**

MyKhaya is a private coordination application for households, families and close groups of friends. This monorepo contains a single responsive Next.js web app (installable as a PWA), a FastAPI modular monolith, shared TypeScript packages and a Docker Compose deployment foundation.

## Branches

- `main`: stable and deployable; Anthony alone merges, tags and deploys it.
- `dev`: the source of all day-to-day development; Codex works and commits here.

## Local development (your own machine)

Requirements: Git, Make, Docker Compose v2.

```sh
cp .env.example .env
make up
```

- Product: `http://localhost:8080`
- Control Centre: `http://admin.localhost:8080`
- Public status: `http://status.localhost:8080`
- Mailpit: `http://localhost:8025`

See [`docs/operations/local-development.md`](docs/operations/local-development.md) for
port customization and how this differs from the persistent dev server below.

## Persistent development server

A separate, shared, NetBird-tunnelled server — not for your own laptop; see
[`docs/operations/local-development.md`](docs/operations/local-development.md) if
that's what you want instead.

Requirements: Git, Make, Docker Compose v2, Python 3, and curl or wget. Use the tracked
development overlay; no `compose.override.yml` is required:

```sh
cp .env.dev.example .env
# Edit every CHANGE_ME value.
make dev-up
```

Email verification is enabled by default. For local development without email delivery,
set `MYKHAYA_EMAIL_VERIFICATION_ENABLED=false` in `.env`; new accounts will be ready
immediately and existing unverified accounts can sign in. Keep it enabled in production.

- Product: `https://dev.mykhaya.app`
- Control Centre: `https://admin.dev.mykhaya.app` (network allow-list and separate operator account required)
- Public status: `https://status.dev.mykhaya.app`
- Mailpit (loopback only): `http://localhost:8025`
- Liveness: `http://localhost:8089/api/v1/health/live`
- Readiness: `http://localhost:8089/api/v1/health/ready`
- Build metadata: `http://localhost:8089/api/v1/health/build`

Use `make dev-update`, `make dev-logs`, `make test`, `make lint`, `make typecheck`,
`make backup` and `make prod`. PostgreSQL and Redis have no host port mappings. See
`docs/operations/dev-deployment.md` for NetBird Proxy, backups, rollback, and troubleshooting.

## Structure

- `apps/web`: responsive Next.js App Router product, installable as a PWA (mobile-first, single codebase for phone/tablet/desktop)
- `apps/api`: FastAPI API, worker, scheduler, Alembic migrations and tests
- `packages`: generated contract/types, client, tokens and shared configuration
- `infrastructure`: Caddy, database bootstrap and operational scripts
- `docs`: authoritative product, design, architecture, engineering, security and operations standards

Read `docs/engineering/engineering-standards.md` before changing code. Deployment and restore instructions live under `docs/operations/`. The ASVS matrix is an honest coverage inventory, not a compliance certificate.

Unfinished modules are controlled by server-side feature flags. All initial flags, including Calendar, default to disabled; see `docs/architecture/feature-flags.md`.

MyKhaya is a hosted service: the public site and signed-in household app remain at `mykhaya.app`; the privileged management plane is `admin.mykhaya.app`; the deliberately limited public status service is `status.mykhaya.app`. The Control Centre is not production-ready until mandatory WebAuthn/passkey authentication is implemented and independently reviewed.
