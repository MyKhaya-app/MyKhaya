# MyKhaya

> **Your family’s digital home.**

MyKhaya is a private coordination application for households, families and close groups of friends. This monorepo contains a Next.js web app, Expo native shell, FastAPI modular monolith, shared TypeScript packages and a Docker Compose deployment foundation.

## Branches

`main`
Stable production releases only.

`dev`
Active development and integration.

Normal pull requests target `dev`. Release pull requests target `main`.

## Start locally

Requirements: Docker Compose. Copy `.env.example` to `.env`, replace every placeholder, then run:

```sh
make up
```

Email verification is enabled by default. For local development without email delivery,
set `MYKHAYA_EMAIL_VERIFICATION_ENABLED=false` in `.env`; new accounts will be ready
immediately and existing unverified accounts can sign in. Keep it enabled in production.

- Product: `http://localhost:3000` (`http://localhost:8080` is also available)
- Control Centre: `http://admin.localhost:8080` (network allow-list and separate operator account required)
- Public status: `http://status.localhost:8080`
- Control Centre: `http://admin.localhost:8080` (network allow-list and separate operator account required)
- Public status: `http://status.localhost:8080`
- Mailpit (loopback only): `http://localhost:8025`
- Liveness: `http://localhost:3000/api/v1/health/live`
- Readiness: `http://localhost:3000/api/v1/health/ready`
- Build metadata: `http://localhost:3000/api/v1/health/build`

Use `make logs`, `make test`, `make lint`, `make typecheck`, `make backup` and `make prod`. PostgreSQL and Redis have no host port mappings.

## Structure

- `apps/web`: responsive Next.js App Router product
- `apps/mobile`: native Expo shell
- `apps/api`: FastAPI API, worker, scheduler, Alembic migrations and tests
- `packages`: generated contract/types, client, tokens and shared configuration
- `infrastructure`: Caddy, database bootstrap and operational scripts
- `docs`: authoritative product, design, architecture, engineering, security and operations standards

Read `docs/engineering/engineering-standards.md` before changing code. Deployment and restore instructions live under `docs/operations/`. The ASVS matrix is an honest coverage inventory, not a compliance certificate.

MyKhaya is a hosted service: the public site and signed-in household app remain at `mykhaya.app`; the privileged management plane is `admin.mykhaya.app`; the deliberately limited public status service is `status.mykhaya.app`. The Control Centre is not production-ready until mandatory WebAuthn/passkey authentication is implemented and independently reviewed.
