# MyKhaya service configuration contracts

Contract for the approved service-specific DEV/PROD configuration architecture.
The namespaced `.env.*.example` files at repository root contain placeholders and
must never be copied over a live environment file.

**DEV (Stage 3A):** the exact per-file allow-lists and deny-lists are defined in
[`infrastructure/scripts/service_env_contract.py`](../../infrastructure/scripts/service_env_contract.py),
which is authoritative; this document explains them. They are applied by
`compose.dev.service-env.yml` when `MYKHAYA_DEV_CONFIG_ROOT` is set. The
migration and rollback procedure is in
[dev-service-config-migration.md](dev-service-config-migration.md).

**PROD:** the same module's PROD profile (`--profile prod`) is applied by
`compose.production.service-env.yml` once the cutover state in
`/etc/mykhaya/prod/.service-env-state` is pending or active; the one-command
migration is in [prod-service-config-migration.md](prod-service-config-migration.md).
Until then PROD uses the root `.env`, unchanged. The PROD files are generated
from the production `.env` by the migration, so no PROD templates are
published (the Stage 1 drafts used the wrong database roles and disabled
scheduler monitoring, so they were not committed).

**Intermediate stage (DEV and PROD).** F-03 is an intermediate service-env
migration: it limits which service receives which value, not how values are
delivered. Credentials are still supplied as container environment variables;
database passwords remain embedded in the `MYKHAYA_DATABASE_URL` connection
URLs, and PostgreSQL's bootstrap passwords are Compose interpolation values.
Anyone with Docker daemon access on the host can read them (`docker inspect`,
`docker compose config`). The final file-backed Docker secrets
implementation remains outstanding under MK-SEC-001 v1.2; it needs application
changes too, because only the Apple key and the field keyrings are read from
files today.

PROD differs from DEV only where `compose.production.yml` differs from
`compose.dev.yml`:

- `compose.production.yml` pins only environment, channel, secure cookies and
  administrator MFA, so the installation values production Settings require
  (URLs, CORS, trusted hosts and proxies, administrator networks, registration
  ceiling, locale defaults) live in `common.env`, which migrate also loads.
- Caddy's domains and trusted proxy CIDRs, the key host directories, the web
  service's email flag and the host backup settings are in `compose.env`.
- `postgres.env` is an interpolation source (a second `--env-file`), not an
  `env_file`, so PostgreSQL's service definition and Compose hash are
  unchanged and it is never recreated by the migration. A value scan proves
  its passwords reach no other service except each application's own database
  URL.
- Environment-supplied field keyrings are forbidden in every file (production
  rejects them at startup). An empty key directory that nothing reads is
  accepted as "not provisioned" (warning only).
- The worker's file carries the APNs and FCM values Compose used to
  interpolate, with the same defaults, so its environment is unchanged.
- DEV identities (the DEV host name, iOS bundle, native return scheme,
  Firebase project, test-mode Stripe keys and DEV paths) are rejected.

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

Alembic (`apps/api/migrations/env.py`) reads only `MigrationSettings`
(`environment`, `database_url` and the optional migration password file, from
the process environment; it has no `.env` fallback) and imports the model
metadata through the
side-effect-free `mykhaya.db_base`, so migrations no longer construct the
application `Settings` and run with `MYKHAYA_SECRET_KEY` absent. The application
services still require the key and fail closed at startup without it. The
deployment contracts are not narrowed yet: DEV and PROD `migrate.env` still carry
the key until a separately approved change removes it.

### DEV file-backed secrets (implemented; not deployed)

The `dev-secrets` profile in `service_env_contract.py` and `compose.dev.secrets.yml`
add a third DEV mode after F-03: Compose file secrets with exact per-service grants and
a process role per service. `SECRET_FILE_SPECS` is the single list of secrets and the
services that receive each; tests keep it equal to the application's role matrix. The
cutover, its rollback and the remaining limits are in
[dev-docker-secrets-migration.md](dev-docker-secrets-migration.md). PROD and the F-03
DEV profile are unchanged and refuse Compose secrets.

### File-backed secrets (application side)

Every secret that can be supplied as a file is declared once in the central
registry `apps/api/mykhaya/secret_registry.py` (MK-SEC-001 v1.2 SEC-093): the
setting it fills, its `*_FILE` variable, its §6.3 credential identifier, its
format and whether it is required. The roles allowed to hold each one come from
the §6.3 grants in `mykhaya.process_roles`. **No deployment sets any `*_FILE`
variable yet.** With none set, configuration behaves exactly as before.

| Variable | Credential | Format |
|---|---|---|
| `MYKHAYA_SECRET_KEY_FILE` | K-01 (required, by either form) | single line |
| `MYKHAYA_DATABASE_PASSWORD_FILE` | K-02 (application), K-03 (migrator) | single line |
| `MYKHAYA_SMTP_PASSWORD_FILE` | K-06 | single line |
| `MYKHAYA_VAPID_PRIVATE_KEY_FILE` | K-07 | single line |
| `MYKHAYA_APNS_PRIVATE_KEY_FILE` | K-08 | PEM |
| `MYKHAYA_FCM_PRIVATE_KEY_FILE` | K-09 | PEM |
| `MYKHAYA_GOOGLE_CLIENT_SECRET_FILE` | K-11 | single line |
| `MYKHAYA_STRIPE_SECRET_KEY_FILE` | K-12 | single line |
| `MYKHAYA_STRIPE_WEBHOOK_SECRET_FILE` | K-13 | single line |
| `MYKHAYA_DVLA_UAT_API_KEY_FILE` | K-14 | single line |
| `MYKHAYA_DVLA_PRODUCTION_API_KEY_FILE` | K-15 | single line |
| `MYKHAYA_DVSA_CLIENT_ID_FILE`, `MYKHAYA_DVSA_CLIENT_SECRET_FILE`, `MYKHAYA_DVSA_API_KEY_FILE` | K-16 | single line |
| `MYKHAYA_MONITORING_WATCHDOG_URL_FILE` | K-17 | single line |

Each file is read in-process by the shared hardened reader
`mykhaya.secret_files` (SEC-017), never by an entrypoint script and never
through pydantic's `secrets_dir`. The path must be absolute, normalised and
inside `/run/secrets/` (where Compose file secrets are mounted); a symbolic link
anywhere in the path is refused. The file is opened without following links or
blocking and validated through its open descriptor: it must be a regular UTF-8
file with no NUL bytes. A single-line secret is at most 4 KiB and must have no
embedded line breaks or surrounding whitespace; one trailing line ending is
removed and nothing else, so the value is used byte for byte. A PEM key is at
most 16 KiB and must be exactly one `BEGIN`/`END` block with nothing around it;
`\n` and `\r\n` line endings are both accepted. A JSON document is at most
64 KiB and must be one object with no duplicate keys. No more than the limit
plus one byte is ever read.

Setting a literal and its `*_FILE` variable together is rejected, and a blank
variable means unset. Under `MYKHAYA_PROCESS_ROLE`, a role never even opens a
file for a credential it is not granted. File values go straight into the same
masked (`SecretStr`) settings and the same validation as the environment form;
nothing is cached, copied into the environment or logged. Errors name only the
setting and the failure category, never the path or the value. Platforms
without descriptor-relative, no-follow opening (Windows) refuse every file
source.

Three file settings keep their established loaders for compatibility: the Apple
sign-in key (`MYKHAYA_APPLE_PRIVATE_KEY_FILE`, K-10) and the field-encryption
and blind-index keyrings (`MYKHAYA_FIELD_ENCRYPTION_KEYS_FILE`,
`MYKHAYA_BLIND_INDEX_KEYS_FILE`, K-18 and K-19). They are declared in the
registry but are not yet read by the hardened reader, which would refuse
symbolic links and paths outside `/run/secrets/` that those loaders accept
today. Moving them needs the deployed file layout confirmed first.

### Database credentials (SEC-086, SEC-086a)

`MYKHAYA_DATABASE_URL` may carry the password, as every deployment does today,
or omit it and take it from `MYKHAYA_DATABASE_PASSWORD_FILE`. In file-backed
mode the password is attached to SQLAlchemy's structured `URL` object inside the
process (`mykhaya.db_credentials`), for both the application engine
(`mykhaya.db`) and Alembic. It is never percent-encoded by hand, written back
into a URL string or an environment variable, or shown in a diagnostic.
Alembic receives the URL object directly rather than through its configuration
file, which would misread a percent-encoded password. A URL that still contains a
password, or names no user, is rejected when a password file is set. There is no
literal `MYKHAYA_DATABASE_PASSWORD` variable. The application (`mykhaya_app`,
K-02) and the migrator (`mykhaya_migrator`, K-03) each resolve their own URL and
password, and process roles keep each to its own identity. A legacy
password-bearing URL is used exactly as before and is not newly validated.

In production (Owner decision D-WP4-01), both the application and the migrator
refuse to start unless `MYKHAYA_DATABASE_URL` was set explicitly. They never use
the class default URL, and they refuse the placeholder passwords this repository
ships. Those are the default's `mykhaya` and the env-template markers
(`replace-with-…`, `CHANGE_ME…`, `GENERATE_A_…`, `__SET_IN_…`), refused whether
they arrive in the URL (including percent-encoded) or in
`MYKHAYA_DATABASE_PASSWORD_FILE`. Errors never quote the URL or password.
Development and test keep the default URL temporarily for legacy compatibility.

### Alembic (SEC-088)

`apps/api/migrations/env.py` builds its engine directly from the `URL` object of
`MigrationSettings` and never writes a URL into Alembic's configuration. Offline
(`--sql`) runs use the same URL with the password removed, so generated SQL holds
no credentials. `apps/api/alembic.ini` keeps only a password-free placeholder
that nothing reads. The migrator runs `alembic upgrade head` with no URL or
password on its command line, migration revisions import no application code,
and SQLAlchemy's connection errors name the user but never the password. WP-1's
keyless `MigrationSettings` and WP-2's migrate-role enforcement are unchanged.
Offline SQL can be rendered only up to revision `0015_colour_palette`, because
revision `0016` reads table data; every revision runs online.

### PostgreSQL bootstrap passwords

`infrastructure/docker/init-db.sh` creates the `mykhaya_migrator` and
`mykhaya_app` roles on the first start of an empty data volume. The postgres
image never runs it against an existing volume, so a deployed database cannot be
re-initialised or have its passwords changed by it. Each role's password comes
from exactly one of `MYKHAYA_MIGRATION_DB_PASSWORD` or
`MYKHAYA_MIGRATION_DB_PASSWORD_FILE`, and of `MYKHAYA_DB_PASSWORD` or
`MYKHAYA_DB_PASSWORD_FILE`; setting both, or neither, stops initialisation. A
file is checked with the same rules as the application's reader (see
*File-backed secrets*): absolute, normalised, under `/run/secrets/`, no
symbolic links, a regular file of at most 4 KiB, no NUL bytes, valid UTF-8,
one line with one trailing line ending removed, not empty and no surrounding
whitespace. The database and the application therefore always use the same
bytes. A shell cannot read without following links the way the application
does, so the script checks each path component before opening the file and
then reads only through that open descriptor.

Passwords reach `psql` only through its standard input, written by shell
builtins, and are quoted by `psql` itself. They never appear in a process's
arguments. Statement logging, error-statement logging and activity tracking
are switched off for that session, and `psql` reports errors tersely, so no log
repeats the statement. Messages name variables and failure categories only.
The superuser password uses the postgres image's own `POSTGRES_PASSWORD` or
`POSTGRES_PASSWORD_FILE`, which the image passes to `initdb` through a file
descriptor and refuses to accept together. An empty legacy password now stops
initialisation; previously it created a role that could not log in.

If initialisation stops part-way, the image leaves a partly initialised data
directory, and a restart skips initialisation. This risk applies only to a newly
created, empty volume. An operator removes that disposable volume before
retrying, after confirming it holds no data. Nothing removes or re-initialises a
volume automatically, and an existing persistent volume is never re-initialised
(Owner decision D-WP4-02: the image's entrypoint is not redesigned in WP-4).

### Continuous integration

The `quality` workflow runs `infrastructure/scripts/check-phase1-secrets.sh`
after building the images. With disposable containers and synthetic values it:
- bootstraps PostgreSQL from file and legacy passwords containing quotes,
  backslashes, URL delimiters, shell syntax and non-ASCII characters;
- proves real SCRAM logins and refusals from another container;
- checks every refused file case and that an existing volume is never
  re-initialised;
- runs the migrate role with no key present (upgrade, downgrade, upgrade) using
  a file-backed password, and confirms it refuses the key;
- renders offline SQL and checks failed connections, logs, `psql` arguments and
  every process argument for credentials;
- connects the `api` role with a file-backed password.

Static guards in `infrastructure/tests/test_phase1_secret_guards.py` and
`apps/api/tests/test_security_guards.py` keep Compose credential interpolation
to the listed legacy values, keep passwords off command lines and pin the
registry, the role grants and this documentation.

### Process roles (enabled only by the DEV file-backed mode)

`MYKHAYA_PROCESS_ROLE` (`api`, `worker`, `scheduler`, `migrate`, `test`, `cli`)
names the process a configuration belongs to (MK-SEC-001 v1.2 SEC-103). **Only
`compose.dev.secrets.yml` sets it; nothing deployed does yet.** While it is unset, configuration behaves exactly as
before. When it is set, the application enforces the MK-SEC-001 §6.3
credential-access matrix (`apps/api/mykhaya/process_roles.py`): a credential the
role is not granted is rejected if present, a credential another role needs is
never required of this one (SEC-102), and errors name variables and credential
identifiers, never values. Blank variables count as absent, so Compose's blanking
of inherited values keeps working.

| Role | Holds | Rejected if present |
|---|---|---|
| `api`, `cli` | application key, app database role, SMTP, VAPID, Apple, Google, Stripe key and webhook secret, DVLA UAT and production keys, DVSA, keyrings | migration or superuser database credential, APNs key, FCM key, monitoring watchdog URL |
| `worker` | application key, app database role, SMTP, VAPID, APNs, FCM, keyrings | Apple, Google, Stripe, DVLA, DVSA, watchdog URL, migration or superuser credential |
| `scheduler` | application key, app database role, SMTP, Stripe key, watchdog URL, keyrings | VAPID, APNs, FCM, Apple, Google, Stripe webhook secret, DVLA, DVSA, migration or superuser credential |
| `migrate` | migration database role only (`MigrationSettings`) | application key (including `_FILE`), every other credential, Redis URL, presence flags |
| `test` | synthetic values | requires `MYKHAYA_ENVIRONMENT=test`; refuses live Stripe keys |

Application roles require `MYKHAYA_DATABASE_URL` with the `mykhaya_app` role and a
password (in the URL or from `MYKHAYA_DATABASE_PASSWORD_FILE`); `migrate`
requires the `mykhaya_migrator` role. `cli` has no §6.3 row
and provisionally follows `api` in code; that does not authorise enabling the
role for administrative tasks that need different privileges. The API holds the
VAPID key (K-07) because the Control Centre sends Web Push test messages itself;
it does not hold the FCM key (K-09), which only the worker uses to send. The DVLA
UAT/production split is not enforced by role, because DEV is authorised to call
the production DVLA and DVSA APIs, with its own isolated credentials and provider
permissions. Redis credentials (K-05) are Phase 2B.

The scheduler's monitoring needs only to know whether DVLA, DVSA and Stripe
webhooks are configured (SEC-101). Under the `scheduler` role it reads the
non-secret flags `MYKHAYA_DVLA_API_KEY_PRESENT`, `MYKHAYA_DVSA_CREDENTIALS_PRESENT` and
`MYKHAYA_STRIPE_WEBHOOK_SECRET_PRESENT` instead of the credentials, with the same check
outcomes. A flag is required whenever its provider is selected (DVLA environment
set, DVSA enabled or configured, Stripe billing configured), so a missing flag
can never silently mark a check "not configured". The flags are ignored for every
other role.

The Apple sign-in key and the keyrings use the hardened reader whenever a role is set,
and a role not granted the Apple key never opens it. With no role, their loaders are
unchanged.

The DEV file-backed mode resolves these differences from the F-03 contracts (PROD would
need the same):

- **Migrator (SEC-089).** Deploy this code first; then remove
  `MYKHAYA_SECRET_KEY` from `migrate.env` and make the `MIGRATE` contract in
  `infrastructure/scripts/service_env_contract.py` forbid it (it currently
  requires it); set `MYKHAYA_PROCESS_ROLE=migrate` for migrate only; and stop
  pinning `MYKHAYA_APNS_DELIVERY_CONFIGURED` for migrate (the shared
  `apns-disabled` block), because the role rejects presence flags.
- **Scheduler (SEC-101).** Replace the scheduler's DVLA keys, DVSA credentials
  and Stripe webhook secret with the presence flags, and update the `SCHEDULER`
  contract to match.
- **API.** The contract still allows the FCM private key, which the matrix denies
  to the API. Its only use there is the Control Centre push-health card's
  "FCM configured" indicator, which reads the non-secret
  `MYKHAYA_FCM_PRIVATE_KEY_PRESENT` under the `api` role. The flag is required whenever
  FCM delivery is configured, and is never used to send.

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

Functional requirement is the migration DB URL (and, in file-backed mode, its
password file). Alembic reads only `MigrationSettings`, so it needs no
application key. It must not receive provider, notification, field-key, Apple
private-key or PostgreSQL administrator credentials. If current validation
requires one, report it as a compatibility finding rather than silently changing
application behaviour.

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
- At the time of this verification, migrations needed the migration DB URL plus
  `MYKHAYA_SECRET_KEY` and the common values that `Settings` validated at Alembic
  import time. Migrations now read only `MigrationSettings` (see above); the
  contract still supplies the key until it is narrowed.
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
world-writable files, and any other `*.env` file in the root. Local
workstations keep their ignored root `.env`.

PROD layout (`/etc/mykhaya/prod/`, selected by the cutover state file in it,
root 0750): `compose.env`, `common.env`, `api.env`, `worker.env`,
`scheduler.env`, `migrate.env` and `postgres.env`, all 0600 (the migration
creates them with `umask 077`), plus the state file and the cutover snapshot;
any other `*.env` file is rejected. Key directories stay at the existing external host paths named
in `compose.env`. The same location, permission and file rules apply.

- **Implemented in the repository:** the PROD profile, overlay, migration and
  mode-aware deployment, backup and restore scripts, verified locally with
  synthetic configuration and disposable Docker resources only.
- **Not deployed:** nothing has been run on the production host. PROD still
  runs from its root `.env` (state absent, legacy mode) until the Owner
  approves `--apply` ([prod-service-config-migration.md](prod-service-config-migration.md)).

Environment files are Compose inputs, not application-working-directory mounts.
Backup exclusion and recovery of the configuration root must be verified on the
DEV host. The DEV rollback procedure (configuration mapping, Compose and script
revision, partial recreation and failed migrations) is in
[dev-service-config-migration.md](dev-service-config-migration.md); it changes no
database data and rotates no credentials.
