# MyKhaya — First Major Codex Prompt

You are establishing the initial production-quality foundation for **MyKhaya**, a private coordination application for households, families and close groups of friends.

> **Your family's digital home.**

Before changing or creating code, read every relevant document under `docs/`, beginning with:

1. `docs/engineering/engineering-standards.md`
2. `docs/product/product-vision.md`
3. `docs/design/design-system.md`
4. `docs/design/branding.md`
5. `docs/architecture/system-overview.md`
6. `docs/security/security-baseline.md`
7. `docs/security/threat-model.md`

The repository documentation is authoritative. The canonical UI and branding reference is `docs/design/reference/authoritative-ui.png`.

## Non-negotiable identity requirement

MyKhaya must have its own consumer lifestyle identity and must not look like Kaya. Do not reuse Kaya layouts, navigation, components, dense administration patterns, terminology, dark infrastructure styling or generic dashboard conventions. Recreate the supplied reference faithfully as a responsive and accessible product interface.

## Task

Create the initial monorepo and secure platform foundation:

```text
mykhaya/
├── apps/
│   ├── web/       # Next.js App Router, strict TypeScript
│   ├── mobile/    # Expo / React Native shell
│   └── api/       # FastAPI modular monolith
├── packages/
│   ├── api-client/
│   ├── design-tokens/
│   ├── shared-types/
│   ├── eslint-config/
│   └── typescript-config/
├── infrastructure/
│   ├── caddy/
│   ├── docker/
│   └── scripts/
├── docs/
├── .github/workflows/
├── compose.yml
├── compose.override.yml
├── compose.production.yml
├── .env.example
├── Makefile
└── README.md
```

Use pnpm workspaces for TypeScript projects unless a documented repository constraint requires otherwise. Use isolated Python tooling for the API.

## Platform

- Next.js web application at `mykhaya.app`
- FastAPI API at `api.mykhaya.app`
- Expo native mobile shell
- PostgreSQL authoritative database
- Redis for bounded cache, rate limits and job coordination
- Durable background worker and one scheduler
- Caddy reverse proxy
- Docker Compose for local, home-server and first VPS deployment
- No Kubernetes, microservices, Elasticsearch or user-facing object storage

The same production images must move from the home test server to the VPS. Only configuration, secrets, domains and sizing change.

## Initial functional journey

1. Register
2. Verify email through local Mailpit
3. Sign in
4. Create first Home
5. View branded Home screen
6. Invite another adult
7. Invitee registers or signs in
8. Invitee accepts
9. Both users see shared membership
10. Cross-Home access is denied

Implement functional Home, People and Settings foundations. Other navigation destinations may use polished “Coming soon” states without dead links.

## Required initial routes

Web:

```text
/
/login
/register
/verify-email
/forgot-password
/reset-password
/onboarding
/home
/people
/settings
/settings/profile
/settings/security
/settings/home
```

API:

```text
/api/v1/health/live
/api/v1/health/ready
/api/v1/version
/api/v1/auth/*
/api/v1/users/me
/api/v1/groups
/api/v1/groups/{group_id}
/api/v1/groups/{group_id}/members
/api/v1/invitations/*
```

## Initial data model

Implement users, authentication identities, sessions, groups, memberships, invitations, audit events and outbox events using UUIDv7 where reliable and UTC timestamps. All reusable secrets and invitation/reset tokens are stored as hashes.

Initial membership roles: owner, administrator, adult_member, member and guest.

## Security

Implement the repository security baseline. OWASP ASVS 5.0.0 Level 2 is the minimum hosted-service target. Explicitly address OWASP Top 10:2025, OWASP API Security Top 10:2023, OWASP Mobile Top 10 2024 and current NCSC secure-development and software-security guidance.

Security requirements include central Home-scoped authorisation, cross-tenant tests, secure cookies, CSRF where applicable, CORS allow-listing, CSP and browser headers, safe redirects, rate and resource limits, restricted database credentials, non-root containers, secret scanning, dependency/SAST/container scans, SBOM generation, audit logging, safe errors, trusted proxy handling and tested backup restoration.

Do not store authentication secrets in browser localStorage. Do not expose PostgreSQL or Redis publicly. Do not weaken controls for local convenience.

## Docker and operations

Local Compose includes Caddy, web, API, PostgreSQL, Redis, worker, scheduler and Mailpit. Provide hot reload, health-based dependency ordering, migrations, logs, seed, reset, tests and production-like commands through a Makefile.

Production containers use multi-stage builds, non-root users, minimal images, graceful shutdown, health checks, stdout logging, dropped capabilities, `no-new-privileges` and read-only filesystems where practical.

Only Caddy binds public application ports. Document trusted proxy configuration for later Cloudflare use.

Provide home-server and VPS deployment, backup, restore, upgrade and rollback instructions. A Docker volume is not a backup.

## Quality gates

Create CI for formatting, linting, type checking, unit/integration/E2E tests, migrations, builds, secret scanning, dependency review, static analysis, container scanning, Compose/IaC scanning and SBOM generation.

Required tests include registration, verification, login, reset, session rotation and revocation, Home creation, invitation acceptance, role enforcement, removed-member access, cross-Home denial, token replay, mass assignment, CSRF/CORS, safe redirects, injection/XSS handling, headers, limits, worker processing and complete Playwright onboarding.

## Implementation workflow

Before coding:

1. Inspect the complete repository.
2. Read all relevant standards.
3. Produce a concise implementation plan.
4. Identify ambiguities or conflicts.
5. Record significant decisions through ADRs.

During coding:

- Keep changes coherent and reviewable.
- Do not bypass migrations or security controls.
- Do not duplicate API models manually across clients.
- Do not introduce general file storage.
- Do not use fake production data.
- Update documentation in the same change.

Before declaring completion:

1. Run all tests and checks.
2. Build every production image.
3. Start the production-like Compose stack.
4. Verify liveness and readiness.
5. Demonstrate onboarding and invitation end to end.
6. Demonstrate cross-Home denial.
7. Verify containers run with intended restrictions.
8. Restore a database backup successfully.
9. Review security findings and the ASVS matrix.
10. Provide an honest implementation summary and limitations.

Do not claim completion unless the evidence demonstrates the acceptance criteria.
