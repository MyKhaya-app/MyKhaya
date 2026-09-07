# Multi-Node Platform — Phase 0 Contracts

Status: design-only. This document records the approved compatibility boundary; it does not change runtime behaviour.

## Current baseline

MyKhaya remains one repository and a modular monolith. The API is `apps/api/mykhaya`; the web/PCC application is `apps/web`; deployment is Compose-first (`compose.yml`, `compose.dev.yml`, `compose.production.yml`); Caddy is the edge reverse proxy. `apps/api/mykhaya/db.py` exposes one application database session factory and `apps/api/migrations/env.py` migrates one configured database.

The current deployment runs `web`, `api`, `worker`, `scheduler`, `migrate`, PostgreSQL, Redis and Mailpit. `apps/api/mykhaya/routers/health.py` provides live/ready/version/build endpoints; `platform_health.py` aggregates DB, Redis, migration, worker, scheduler and backup state for PCC. `worker.py` and `scheduler.py` share the configured DB/Redis pair. Authentication and browser sessions are implemented in `routers/auth.py`, `dependencies.py`, `security.py` and `platform_security.py`; PCC uses separate admin sessions and CSRF controls.

The current protected deployment is `dev.mykhaya.app`. It contains a real family Home and must be treated as stateful user data. Existing `infrastructure/scripts/dev-deploy.sh`, `update-dev.sh`, `.env.dev.example` and `infrastructure/caddy/Caddyfile.dev` remain the source of truth for that workflow. They must not be repurposed for Lab.

## Environment, region and node contracts

These are independent dimensions:

| Concept | Phase 0 contract |
|---|---|
| Environment | `lab`, `development`, `production`; describes operational isolation and data trust level. |
| Region | A deployment/data-residency label such as `uk`; never use `lab`, `development` or `production` as a Region. |
| Node | A named MyKhaya application deployment, uniquely identified by an immutable node ID and assigned one environment and one Region. |
| Home placement | A Home eventually has one owning Region and one owning node. Placement is explicit; no implicit default or automatic cross-node movement. |

Initial intended inventory:

| Node | Environment | Region | Data |
|---|---|---|---|
| `mk-lab-01` | `lab` | `uk` | synthetic fixture data only |
| `mk-dev-01` | `development` | `uk` | existing protected family Home; registration deferred |
| `mk-uk-01` | `production` | `uk` | future production data owner |

PCC remains the control plane and the single Users/Homes/subscriptions/admin experience. It must not proxy ordinary family traffic or connect directly to regional PostgreSQL databases. Regional applications remain available without PCC.

## PCC and management boundary

The future PCC Nodes/Regions UI belongs under the existing platform router (`apps/api/mykhaya/routers/platform.py`) and web control-centre routes (`apps/web/app/control-centre/**`). It will use narrow, versioned management APIs and a routing directory, not direct regional DB access.

Management API v1 is the planned boundary:

* `GET /api/v1/platform/regions`
* `POST /api/v1/platform/regions`
* `GET /api/v1/platform/nodes`
* `POST /api/v1/platform/nodes`
* `GET /api/v1/platform/nodes/{node_id}`
* `POST /api/v1/platform/nodes/{node_id}/heartbeat`
* `POST /api/v1/platform/nodes/{node_id}/registration/complete`
* `POST /api/v1/platform/nodes/{node_id}/certificates/rotate`
* `POST /api/v1/platform/nodes/{node_id}/revoke`

The public contract must carry `api_version`, `node_id`, `environment`, `region_code`, software version/build, schema/migration revision, capabilities and observed timestamp. Heartbeats are authenticated node-management calls, idempotent, bounded in size and never accepted as proof of application-user identity.

Node status is reported from the node's existing health/build surfaces (`health.py`, `platform_health.py`, `status_aggregation.py`) through a dedicated management adapter. PCC stores directory/status metadata only; it does not mirror household records.

## Dependency tiers

* Tier 0: local node availability — PostgreSQL, Redis, API, web, worker, scheduler, migrations.
* Tier 1: node-local integrations — SMTP/PCC email configuration, APNs/Web Push, Stripe configuration, Mailpit in Lab.
* Tier 2: control-plane observability — PCC directory, node heartbeat, version and audit reporting.
* Tier 3: edge/routing — Cloudflare, dedicated Edge VPS, Caddy and routing metadata; deferred.

Tier 2/3 failure must not make Tier 0 user traffic unavailable. NetBird remains only a current development-network convenience; it is not an application or reference-architecture dependency.

## Single-node assumptions to retire later

The assumptions are concentrated in `config.py`'s environment literal and URL validation, `db.py`/Alembic's single configured database, `models.py`'s Home/Membership model without placement, `billing/` and `entitlements.py`'s same-database Home subscription lookup, `platform.py`'s direct PCC database queries, Compose's one project/network/volume namespace, and the deployment scripts' one environment model. `Caddyfile.dev` and `Caddyfile.production` also encode one edge per deployment.

Phase 0 deliberately does not alter these assumptions. Phase 1 must add placement metadata additively and route only through a management API; it must not move existing data or require PCC-to-node PostgreSQL connectivity.

## Protected development and Lab policy

The current checkout and `dev.mykhaya.app` are protected. Never reset, clean, stash, switch, migrate, redeploy or alter their Compose state as part of this programme. Work belongs on `feature/multi-node-platform`, preferably in `../mykhaya-multinode`.

Lab is a separate deployment, not a copy of development. It has separate PostgreSQL and Redis databases/volumes, Compose project, app storage, session/signing/encryption secrets, node credentials, routing metadata, workers, scheduler, email/APNs/Stripe test configuration and ingress. Only synthetic fixtures may be seeded.

