# MyKhaya service configuration contracts

Contract for the approved service-specific DEV/PROD configuration architecture.
The namespaced `.env.*.example` files at repository root contain placeholders and
must never be copied over a live environment file.

**DEV (Stage 3A):** the exact per-file allow-lists and deny-lists are defined in
[`infrastructure/scripts/service_env_contract.py`](../../infrastructure/scripts/service_env_contract.py),
which is authoritative; this document explains them. They are applied by
`compose.dev.service-env.yml` when `MYKHAYA_DEV_CONFIG_ROOT` is set. The
migration and rollback procedure is in
[dev-service-config-migration.md](dev-service-config-migration.md). **PROD** is
unchanged and still uses the root `.env`. No PROD service templates are
published yet: a later, separately approved PROD stage will produce them from
this contract (the Stage 1 drafts used the wrong database roles and disabled
scheduler monitoring, so they were not committed).

## Rules

- `common.env` contains shared non-sensitive values only.
- API, worker, scheduler, migration, PostgreSQL and test files are explicit
  service contracts; no service inherits the root deployment `.env`.
- PostgreSQL bootstrap passwords are not application-service credentials.
- Provider credentials are supplied only after runtime proof that a service calls
  that provider.
- Production Apple and field-encryption keys remain external, read-only mounts.
- DEV and PROD have separate configuration roots and credentials.
- Test and E2E services use synthetic values and never consume a deployment `.env`.

## Current compatibility constraints

`apps/api/mykhaya/config.py` declares `env_file=".env"`. Process environment
variables take precedence, but a `.env` in a container working directory would
still be an unintended fallback. Verified: `.dockerignore` excludes `.env` and
`.env.*`, the API Dockerfile copies only named paths, no Compose file mounts a
`.env` or the repository into `/app`, images contain no `.env`, and `/app` is not
writable by the runtime user. Regression tests in
`infrastructure/tests/test_dev_service_env.py` keep it that way. Removing the
declaration (so settings never read a file) is recommended as a small, separately
approved application change.

Alembic imports `get_settings()` from `apps/api/migrations/env.py`; migrations
therefore currently construct the complete settings model. The intended
migration contract is narrow, but removing import-time dependencies requires a
separate application change and approval.

## Service contracts

### API

Requires environment/security policy, application DB and Redis URLs, public
URLs/hosts, authentication/MFA policy, enabled email/push/OAuth providers,
Stripe billing/webhook settings, enabled DVLA/DVSA providers, storage/limits,
monitoring and field-key configuration. It may read the external field-key and
Apple private-key mounts. It must not receive PostgreSQL administrator or
migration passwords. SMTP, Web Push and FCM stay because the Control Centre
reports their status and sends test messages from the API process. APNs is
worker-only, and the external watchdog URL is scheduler-only (PCC's manual
single-check runs never ping it).

### Worker

Requires application DB and Redis URLs, SMTP, Web Push, APNs and FCM delivery
settings, the field keyrings and legal-evidence storage (which also holds
transient Vehicle Report PDFs). Static reachability from `mykhaya.worker` shows
no Stripe, OAuth, DVLA or DVSA credential use, so they are denied. The worker's
watchdog needs only `MYKHAYA_MONITORING_ENABLED`. Mounts: legal-evidence storage
and the field keyrings only.

### Scheduler

Requires application DB and Redis URLs, scheduled-task and monitoring settings,
and the field keyrings. Stage 2 proved the Stripe webhook IP sync needs no Stripe
secret. Stage 3A found that the **service-monitoring runner** (enabled on DEV)
does need provider configuration when a provider is configured through the
environment rather than the Platform Control Centre:

| Scheduler receives | Only when | Read by | Why |
|---|---|---|---|
| `SMTP_HOST`, `_PORT`, `_USERNAME`, `_PASSWORD`, `_CONNECTION_SECURITY`, `_TIMEOUT_SECONDS`, `_REPLY_TO`, `EMAIL_DELIVERY_CONFIGURED`, `EMAIL_FROM` | SMTP configured by environment | `check_smtp` via `resolve_smtp_config` | Authenticated SMTP login; the resolver reads all nine |
| `STRIPE_SECRET_KEY` | Stripe configured by environment | `check_stripe_api` | Authenticated balance read (`Authorization: Bearer`) |
| `STRIPE_WEBHOOK_SECRET` | as above | `check_stripe_webhooks` | Counts as configured only with the secret present |
| `STRIPE_BILLING_CONFIGURED`, `STRIPE_FAMILY_MONTHLY_PRICE_ID`, `STRIPE_FAMILY_ANNUAL_PRICE_ID` | as above | `Settings.validate_stripe_configuration` | A configured flag without these fails startup |
| `DVLA_ENVIRONMENT` + the selected environment's endpoint and API key only | DVLA enabled | `check_dvla_connectivity` (`dvla_configured`) | Applicability needs the key present; only the hostname is probed |
| `DVSA_ENABLED`, `DVSA_TOKEN_URL`, `DVSA_CLIENT_ID`, `DVSA_CLIENT_SECRET`, `DVSA_API_KEY`, `DVSA_API_BASE_URL` | DVSA enabled | `check_dvsa_*` (`dvsa_configured`) | Applicability needs all four credentials present; only hostnames are probed |
| `APPLE_SIGN_IN_ENABLED`, `GOOGLE_SIGN_IN_ENABLED` (+ optional JWKS URLs) | always | `check_apple_sign_in`, `check_google_sign_in` | Public JWKS fetch; no secret |
| `MONITORING_WATCHDOG_URL` | dead-man's switch used | engine full cycle | Only the scheduler pings it |

Never supplied to the scheduler: APNs, FCM and VAPID private keys, the Apple
private key, the Google client secret, the Stripe publishable key and acquisition
flags, `DVSA_SCOPE`/`DVSA_ENVIRONMENT`, the non-selected DVLA environment's pair,
and every PostgreSQL bootstrap password. The validator enforces all of these.
Monitoring stays accurate because a provider the API uses through the environment
must be supplied identically to the scheduler (checked by name, values compared in
memory); a provider configured in the Platform Control Centre needs nothing here,
because the scheduler reads it from the database with `MYKHAYA_SECRET_KEY`.

Withholding these would make monitoring report a live provider as "not
applicable", which is dishonest monitoring (Charter principle 6). They are
therefore permitted in `scheduler.env`, identical to `api.env`. A follow-up
application change could replace the DVLA/DVSA presence test with a non-secret
flag so the scheduler no longer needs those credentials. The scheduler also
sends the external watchdog ping. Mounts: avatar, meal-image, vehicle-photo and
Home Migration storage (demo-Home expiry and package purge) and the field
keyrings; no support attachments, legal evidence or Apple key.

### Migrate

Functional requirement is the migration DB URL plus the minimum values required
by current `Settings` construction during Alembic import. It must not receive
provider, notification, field-key, Apple private-key or PostgreSQL administrator
credentials. If current validation requires one, report it as a compatibility
finding rather than silently changing application behaviour.

### PostgreSQL, Redis, Web and Caddy

PostgreSQL receives bootstrap values only. Redis receives only Redis-specific
configuration. Web receives safe URLs and build metadata only. Caddy receives
domains, routing and trusted-proxy configuration only. None receives provider
credentials or application signing keys.

### Test and E2E

Use synthetic database, Redis, signing-key and provider-disabled values. They
must not inherit developer or deployment `.env` files or production key mounts.

## Contract variable ownership (DEV)

- `compose`: Compose interpolation only (bind address, ports, proxy CIDRs, admin
  networks, locale, key host directories). Non-secret; never loaded into a container.
- `common`: values api, worker and scheduler must agree on (field-key policy and
  file paths, Driveway encryption flags, monitoring enabled).
- `api`, `worker`, `scheduler`, `migrate`, `postgres`: as described above.
- `test`: not in the DEV root. The test service loads the tracked synthetic
  `.env.dev.test.example`, whose hosts exist only in the isolated test stack.

Values that `compose.dev.yml` pins (environment, URLs, hosts, CORS, cookie and MFA
policy, build channel) are rejected in service files: an environment entry beats
an env_file entry, so they would silently have no effect. Host-specific pinned
values (proxy CIDRs, admin networks, locale) are interpolated from `compose.env`.
Every service's `MYKHAYA_SECRET_KEY` must be identical (sessions and Control
Centre secret decryption); database URLs must use `mykhaya_app` (runtime) or
`mykhaya_migrator` (migrate) with the passwords in `postgres.env`.

The overlay restates each service's environment with `environment: !override`
rather than inheriting through the `<<: *api` anchor, and replaces `env_file`
and the worker/scheduler `volumes`. Key-level `!reset` is not used: Compose
ignores it when an intermediate file (here `compose.dev.yml`) also touches the
same mapping, which was confirmed during Stage 3A and would have left the
interpolated database URL in place.

## Stage 2 isolated runtime verification

`compose.isolated.yml` is a standalone stack (project `mykhaya-f03-isolated`)
with synthetic PostgreSQL, Redis, Mailpit, migrate, API, worker, scheduler and
an optional `tests`-profile test service. It never includes `compose.yml` or a
deployment overlay, publishes no ports, and attaches every service only to the
`internal: true` network `f03-data`, so no container has internet egress.

Always invoke it with the explicit project name and the synthetic interpolation
file, which stops Compose from reading the repository root `.env`:

```sh
docker compose -p mykhaya-f03-isolated \
  --env-file infrastructure/tests/isolated-compose.env \
  -f compose.isolated.yml --profile tests <command>
```

Typical sequence: `build`; `up -d --wait postgres redis mailpit`; `up migrate`;
`up -d --wait api` then `up -d worker scheduler`; stop api/worker/scheduler
before `run --rm --no-deps -T test python -m pytest`, so the daemons do not
consume outbox rows that tests assert on. Clean up with
`down -v --remove-orphans` using the same project and file arguments; this
removes only the project's containers, network and volumes. Never use
`docker system prune` or `docker volume prune`.

Worker and scheduler disable the image healthcheck, as in `compose.yml`: it
probes the API port, which they never serve. Their liveness evidence is the
`operational_heartbeats` table.

Runtime findings (2026-11-19):

- The isolated common fixture must satisfy `Settings` validation: `BUILD_CHANNEL`
  is `development` or `stable`, and non-localhost development URLs require
  `COOKIE_SECURE=true`. The PROD common template therefore uses `stable`.
- `isolated-test.env` must carry the backend test-suite contract that CI uses
  (the `compose.yml` `test` service overrides: localhost CORS/trusted hosts,
  PCC admin networks, the pinned test proxy CIDR, raised auth rate limits,
  `ADMIN_MFA_REQUIRED=false`, `COOKIE_SECURE=false`, `/tmp` storage). With
  narrower values, 1,413 tests fail on the origin guard. These are test-only
  synthetic values and never apply to a deployed service.
- The full suite leaves several thousand synthetic outbox rows. If worker and
  scheduler are started afterwards they drain them (about 9 jobs/s) to Mailpit
  before a newly enqueued probe is reached; two suite rows with deliberately
  minimal payloads fail with `KeyError` and back off as designed.
- Migrations need only the migration DB URL plus `MYKHAYA_SECRET_KEY` and the
  common values that `Settings` validates at Alembic import time.
- The scheduler's Stripe webhook IP-feed sync runs without any Stripe secret;
  with no egress it records a sanitised `ConnectError` and continues.
- Images contain no `.env`, and `/app` is not writable by the runtime user, so the
  `env_file=".env"` fallback in `config.py` cannot load a file at runtime. The
  declaration itself remains; removing it is a separate application change.
- The isolated stack does not replicate `compose.yml` hardening (`read_only`,
  `cap_drop`, `no-new-privileges`, tmpfs). The Stage 3A DEV overlay does not need
  it to: it inherits that hardening from `compose.yml`, verified by tests and on
  running containers.

## Layout, permissions and rollback

DEV layout (`MYKHAYA_DEV_CONFIG_ROOT`, normally `/etc/mykhaya/dev/`, mode 0750):
`compose.env` and `common.env` (0640), `api.env`, `worker.env`, `scheduler.env`,
`migrate.env` and `postgres.env` (0600 or 0640), and key directories referenced
by absolute paths from `compose.env` (0750, files 0440/0640, never readable by
others). The validator rejects a root or key directory inside the repository or
on a production path, symbolic links, world-readable secret files, group- or
world-writable files, and any other `*.env` file in the root. The PROD layout is
not yet implemented. Local workstations keep their ignored root `.env`.

Environment files are Compose inputs, not application-working-directory mounts.
Backup exclusion and recovery of the configuration root must be verified on the
DEV host. The DEV rollback procedure (configuration mapping, Compose and script
revision, partial recreation and failed migrations) is in
[dev-service-config-migration.md](dev-service-config-migration.md); it changes no
database data and rotates no credentials.
