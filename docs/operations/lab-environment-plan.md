# Isolated Lab Environment — Phase 0.5 Operations

This documents the isolated Lab runtime implemented in `feature/multi-node-platform`. It does not implement Phase 1 node registration, mTLS issuance, Region/Node tables or PCC node-management UI.

## Implemented topology

* Compose project: `mykhaya-lab`.
* Node: `mk-lab-01`, environment `lab`, Region `uk`.
* Services: `caddy`, `web`, `api`, `worker`, `scheduler`, `migrate`, `postgres`, `redis`, `mailpit`.
* Domains: `lab.mykhaya.app`, `admin.lab.mykhaya.app`, `api.lab.mykhaya.app`, `status.lab.mykhaya.app`.
* PostgreSQL database: `mykhaya_lab`, with Lab-only credentials and volume.
* Networks: `mykhaya_lab_edge`, `mykhaya_lab_app`, `mykhaya_lab_data`.
* Volumes: `mykhaya_lab_postgres_data`, `mykhaya_lab_redis_data`, `mykhaya_lab_avatar_data`, `mykhaya_lab_caddy_data`, `mykhaya_lab_caddy_config`.

## Files implemented

| File | Purpose |
|---|---|
| `compose.lab.yml` | Isolated overlay with Lab-only networks, volumes, services and ports. |
| `.env.lab.example` | Lab environment contract with separate secrets, origins and test providers. |
| `infrastructure/caddy/Caddyfile.lab` | Dedicated Lab host routing and security headers. |
| `Makefile` | Guarded Lab lifecycle targets. |
| `infrastructure/scripts/lab-deploy.sh` | Guarded build, migration, deployment, health, log, stop and reset flow. |
| `infrastructure/scripts/lab-seed.sh` | Guarded synthetic fixture entrypoint. |
| `infrastructure/docker/init-db-lab.sh` | Lab-specific PostgreSQL role/database initialization. |
| `apps/api/mykhaya/config.py` | Minimal `lab` environment/build-channel support and secure Lab validation. |
| `apps/api/mykhaya/lab_seed.py` | Idempotent synthetic fixture command using `ManagedDemoService`. |

The base Compose services are reused through an overlay. Explicit Compose override tags ensure the merged configuration contains only the three Lab networks and five `mykhaya_lab_*` volumes.

## Setup and commands

From the multi-node worktree:

```text
Copy-Item .env.lab.example .env.lab
# Replace every CHANGE_ME value with independently generated Lab values.
make lab-up
make lab-health
make lab-seed
make lab-logs
make lab-update
make lab-rebuild
make lab-reset
make lab-down
```

`lab-update` applies migrations only to `mykhaya_lab` and restarts only the `mykhaya-lab` project. `lab-rebuild` rebuilds and redeploys while retaining Lab data. `lab-reset` requires typing `RESET LAB`, removes only Lab project volumes, recreates the stack, and permits `make lab-seed` afterwards. `lab-down` stops services while retaining data.

To remove Lab completely, first stop it and then run the same explicitly scoped Compose teardown from this worktree:

```text
docker compose --project-name mykhaya-lab --env-file .env.lab -f compose.yml -f compose.lab.yml down --volumes --remove-orphans
Remove-Item .env.lab
```

Do not use Docker-wide prune commands. This teardown is scoped to the `mykhaya-lab` project and its explicitly named Lab volumes.

## Manual DNS records

Do not change DNS automatically. Create these records manually only when the dedicated Lab ingress host is ready:

| Record | Type | Target |
|---|---|---|
| `lab.mykhaya.app` | A/AAAA | Dedicated Lab ingress host running Lab Caddy, not the production Edge VPS |
| `admin.lab.mykhaya.app` | A/AAAA | Same dedicated Lab ingress host |
| `api.lab.mykhaya.app` | A/AAAA | Same dedicated Lab ingress host |
| `status.lab.mykhaya.app` | A/AAAA | Same dedicated Lab ingress host |

The default `.env.lab.example` binds Caddy to loopback for safe local validation. Phase 0.75 uses the exact Lab hostnames with local `curl --resolve` mappings and Caddy's Lab-only internal TLS CA; no public DNS or Cloudflare changes are needed. For a remote Lab ingress, set `MYKHAYA_LAB_BIND_ADDRESS` and the operator/admin CIDR values explicitly to approved host/VPN interfaces. Do not use broad admin network ranges.

## Isolation and providers

Generate unique Lab values for secret/session signing, encryption, database roles, Redis and fixture credentials. Sessions remain Secure and host-only (`MYKHAYA_COOKIE_DOMAIN` empty); WebAuthn origins derive from the Lab admin URL. Lab uses Mailpit/non-delivering SMTP, disabled APNs, disabled Web Push, and requires Stripe test-mode prefixes (`sk_test_`, `pk_test_`, `whsec_`). It must never inherit `.env`, `.env.dev`, development PCC rows, production keys or real family data.

## Synthetic seed

`make lab-seed` invokes `mykhaya.lab_seed`, refuses any environment other than `lab`, and requires a local `MYKHAYA_LAB_FIXTURE_PASSWORD`. It uses the existing `ManagedDemoService` and `ManagedDemoType.demo` template to create or refresh one synthetic Home, owner, adult/child members, memberships/roles, complimentary Family entitlement, calendar/events, routines, reminders, meals/meal-plan participants and household lists/items. No real email, device token or database copy is used. Repeated runs refresh `fixture_key=lab-review` instead of duplicating rows.

## Acceptance gates

1. `dev.mykhaya.app` remains reachable and its working tree/Compose state is unchanged.
2. Lab starts with an empty Lab database and synthetic seed only.
3. Lab cannot resolve or mount development PostgreSQL/Redis/app-storage volumes.
4. Lab health, migration, worker and scheduler checks pass independently.
5. Lab session cookies, signing keys, encryption keys and node credentials differ from development.
6. Lab ingress routes only Lab hostnames and does not alter Cloudflare, production Caddy, DNS or VPS configuration.
7. Reset/rebuild is repeatable and cannot target development or production.
8. The eventual `mk-lab-01` registration uses management API v1 and does not grant PCC regional DB access.
