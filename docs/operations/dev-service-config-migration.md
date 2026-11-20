# DEV service-specific configuration: migration and rollback

**Status:** Stage 3A (preparation). Prepared and verified locally with synthetic
configuration only. Nothing here has been run against the DEV server. Stage 3B
(the cutover) requires explicit Owner approval.

This runbook moves the persistent DEV deployment from the single repository root
`.env` to one file per service under `/etc/mykhaya/dev/`. The contract it
enforces is defined in
[`infrastructure/scripts/service_env_contract.py`](../../infrastructure/scripts/service_env_contract.py)
and explained in [service-configuration-contracts.md](service-configuration-contracts.md).
PROD is unaffected: it never loads `compose.dev.service-env.yml`.

## What changes

| | Legacy (today) | Service-specific |
|---|---|---|
| Selection | default | `MYKHAYA_DEV_CONFIG_ROOT=/etc/mykhaya/dev` |
| Compose interpolation | repository `.env` | `/etc/mykhaya/dev/compose.env` (non-secret) |
| api / worker / scheduler | whole `.env` | `common.env` + own file |
| migrate | whole `.env` | `migrate.env` only |
| postgres | interpolated from `.env` | `postgres.env` |
| test | whole `.env` | tracked synthetic `.env.dev.test.example` |
| worker / scheduler mounts | every API volume + Apple key | only what they use |

Every value that `compose.dev.yml` pins (URLs, hosts, CORS, environment, cookie
and MFA policy) is unchanged and is restated by the overlay; a parity test fails
if the two ever diverge. Hardening (read-only root filesystem, dropped
capabilities, no-new-privileges, tmpfs, healthchecks, restart and logging) is
inherited unchanged.

The scheduler's service-monitoring runner authenticates to SMTP and Stripe and
decides DVLA/DVSA applicability from credential presence, so it keeps those
provider values when they are configured through the environment. The worker
no longer receives Stripe, OAuth, DVLA or DVSA values; the API no longer receives
the PostgreSQL bootstrap passwords or the watchdog URL.

## Prerequisites

1. Stage 3A changes are committed to `dev` by the Owner and present on the server.
2. Docker Compose 2.24.4 or later (`docker compose version`). The deploy script
   refuses older versions.
3. A verified, restorable PostgreSQL backup taken immediately before cutover
   (`make backup`, see [backup-and-restore.md](backup-and-restore.md)).
4. A maintenance window: postgres, api, worker and scheduler containers are
   recreated (data volumes are kept).

## 0. Read-only host preflight

**Before anything else, the Owner must identify the authorised DEV host and the
deployment path in writing.** Do not guess an address or connect to an
unconfirmed SSH host. Then run, on that host as the deployment account, from the
deployment checkout. Nothing here changes state or prints a secret value.

```sh
hostname; whoami; pwd                                                               # host, account, path
git rev-parse --show-toplevel; git branch --show-current; git rev-parse --short HEAD; git status --short | head
docker version --format '{{.Server.Version}}'; docker compose version --short       # Compose >= 2.24.4
printenv COMPOSE_PROJECT_NAME MYKHAYA_DEV_CONFIG_ROOT MYKHAYA_DEV_SERVICE_ENV_STATE  # expect: all empty
docker ps -a --format '{{.Names}} {{.Status}} {{.Label "com.docker.compose.project"}}'
docker compose -f compose.yml -f compose.dev.yml ps --format '{{.Name}} {{.Status}}'
docker volume inspect mykhaya_dev_home_migration_data --format '{{.Name}} {{.CreatedAt}} {{index .Labels "com.docker.compose.project"}}'
docker ps -a --filter volume=mykhaya_dev_home_migration_data --format '{{.Names}} {{.Status}}'
grep -E '^MYKHAYA_(FIELD_KEYS|APPLE_KEY)_HOST_DIR=|^MYKHAYA_APPLE_PRIVATE_KEY_FILE=' .env | sed 's/=.*/=<set>/'
sed -n 's/^MYKHAYA_\(FIELD_KEYS\|APPLE_KEY\)_HOST_DIR=//p' .env                       # paths only, not keys
for d in $(sed -n 's/^MYKHAYA_\(FIELD_KEYS\|APPLE_KEY\)_HOST_DIR=//p' .env) ./secrets/field-keys ./secrets/apple; do
  [ -e "$d" ] && sudo stat -c '%a %U:%G %n' "$d" "$d"/* 2>/dev/null                # modes/owners only
done
ls -ld /etc/mykhaya /etc/mykhaya/dev 2>&1; stat -c '%a %U:%G %n' .env
df -h / /var/lib/docker
```

Record, and have the Owner confirm, before approving cutover:

| Item | Required answer |
|---|---|
| Host and path | The authorised DEV host and the checkout used by `make dev-*` |
| Commit and branch | `dev`, clean, containing the committed F-03 changes |
| Docker / Compose | Compose 2.24.4 or later |
| Project identity | `mykhaya`; `COMPOSE_PROJECT_NAME` unset; containers labelled `mykhaya` |
| Home Migration volume | `mykhaya_dev_home_migration_data` exists and at least one container (running or stopped) references it |
| Apple key | Directory and file path; outside the checkout or planned for copy; file not readable by others |
| Field keyrings | Directory; outside the checkout or planned for copy; files not readable by others |
| Configuration ownership | `/etc/mykhaya/dev` creatable as `0750` by the deployment account; root `.env` not world-readable |
| Backup and recovery | A verified encrypted PostgreSQL backup from today, and an approved, encrypted recovery method covering `/etc/mykhaya/` (never `backups/`, the repository or a cloud-synced folder) |
| Disk space | Room for one extra set of images |

## Commands that bypass the deploy script

Only `infrastructure/scripts/dev-deploy.sh` (`make dev-*`) honours the
configuration mode and the cutover state. On the DEV host, the local-workstation
targets `make init`, `up`, `down`, `backend-rebuild`, `migrate` and `reset` refuse
to run once the cutover state file exists
(`infrastructure/scripts/dev-host-guard.sh`): they run bare `docker compose` with
`compose.yml` and the root `.env`, without `compose.dev.yml`, and `make reset` runs
`docker compose down -v`, which deletes persistent volumes. Run
`sh infrastructure/scripts/dev-deploy.sh state-init` in step 2 so these guards
apply from the start. The state file never exists on a workstation, so local
development, `make test` and the E2E harness are unaffected.

Manual `docker compose -f compose.yml -f compose.dev.yml run|up` commands (for
example the platform-owner bootstrap) are not guarded and use the root `.env`;
after cutover add
`--env-file /etc/mykhaya/dev/compose.env -f compose.dev.service-env.yml`. Once the
root `.env` is retired (a separate, later step), every such bypass fails closed
because Compose cannot find the env file. Never run `docker compose down` on the
DEV host.

## Volume safety

The pre-start validator (`validate_backend_config.py`, also used by PROD) runs
throwaway probe containers in its own Compose project. Before the F-03
correction, the probe declared the stack's own fixed-name volume
(`mykhaya_dev_home_migration_data`, `mykhaya_prod_home_migration_data`) and its
`down --volumes` cleanup deleted it whenever no container, running or stopped,
still referenced it. Home Migration packages are not backed up, so that loss
would have been unrecoverable. The corrected validator:

- gives every declared volume a name inside a unique, random probe project, and
  fails closed if any volume is external;
- proves before any probe container exists that every probe volume and network
  is probe-scoped and that no probe volume already exists;
- never uses `down --volumes`, and removes only volumes carrying both the probe's
  Compose project label and its name prefix.

## 1. Inventory (names only)

On the DEV server, from the repository directory:

```sh
sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' .env | sort
grep -E '^MYKHAYA_(FIELD_KEYS|APPLE_KEY)_HOST_DIR=' .env | sed 's/=.*/=<set>/'
```

Record where the field keyrings and the Apple key currently live. If either
variable is unset, Compose has been using `./secrets/...` inside the repository
checkout. The new layout refuses key directories inside the repository, so move
them under `/etc/mykhaya/dev/` in step 2 (keep the originals until stabilised).
The documented DEV Apple key location is `/etc/mykhaya/dev/apple`.

## 2. Create the root and key directories

```sh
sudo install -d -m 0750 -o "$USER" -g "$USER" /etc/mykhaya/dev
sh infrastructure/scripts/dev-deploy.sh state-init    # records "legacy"; arms the Makefile guards
# Only if the keys are not already outside the repository:
sudo install -d -m 0750 -o root -g 10001 /etc/mykhaya/dev/secrets/field-keys
sudo install -d -m 0750 -o root -g 10001 /etc/mykhaya/dev/secrets/apple
```

Key files: mode `0440` (or `0640`), owner `root`, group `10001` (the container
user), as in [sensitive-field-keys.md](sensitive-field-keys.md). Never world-readable.
Copy keys with `install -m 0440 -o root -g 10001 SRC DEST`; never print them.

## 3. Generate the service files from the legacy `.env`

```sh
python3 infrastructure/scripts/service_env_contract.py \
  --split-legacy-env .env --out /etc/mykhaya/dev
```

The tool never prints a value, never overwrites an existing file, and creates
secret files `0600` (`compose.env`, `common.env` `0640`). It builds the database
URLs exactly as `compose.yml` does today and reports, by name only:

- pinned names that had no effect and are dropped;
- names that are not settings at all (for example `MYKHAYA_SMTP_STARTTLS`);
- for each service, what it no longer receives.

Review that report. Every entry must be either a credential the service does not
use or a pinned/obsolete name.

The tool reads `.env` exactly as Docker Compose does. A value may span several
lines only inside quotes, as a PEM key such as `MYKHAYA_APNS_PRIVATE_KEY` usually
does (`KEY="-----BEGIN ...` on one line, `...-----"` on the last). Double-quoted
values decode `\n`, `\t`, `\r`, `\\`, `\"` and `\$`; single-quoted values are
literal; unquoted values are one line, with literal backslashes (the one-line
`\n` form used for FCM keys is preserved as written). The tool refuses rather
than guesses wherever Compose would silently change a value: an unterminated
quote, text after a closing quote, a line that is neither an assignment nor
inside quotes, an unquoted multiline key (Compose keeps only its first line), or
a `$` that Compose would interpolate (write `$$`, or use single quotes). Errors
name the line and variable only, never a value. Generated files are written in
full only after every file has been read back and matched exactly.

To see how a multiline value is quoted without displaying it, print only its
first character after `=` and the last character of its final line:

```sh
awk -v k=MYKHAYA_APNS_PRIVATE_KEY 'index($0, k"=")==1 {print "opens with:", substr($0, length(k)+2, 1)}' .env
```

`"` or `'` means the value is quoted and Compose reads the whole key. Anything
else means Compose has only ever passed its first line to the worker, so APNs
signing cannot currently work; fix the quoting in the legacy `.env` (and verify
APNs delivery) before splitting. Then make sure `compose.env` contains the
absolute key directories from step 1:

```text
MYKHAYA_FIELD_KEYS_HOST_DIR=/etc/mykhaya/dev/secrets/field-keys
MYKHAYA_APPLE_KEY_HOST_DIR=/etc/mykhaya/dev/apple
```

Do not change any credential, DVLA environment (DEV keeps its authorised
environment, including production DVLA), Stripe sandbox value, Apple/Google
registration, SMTP, APNs or FCM value. The templates `.env.dev.*.example`
document each file if a value has to be added by hand.

## 4. Validate without touching containers

```sh
MYKHAYA_DEV_CONFIG_ROOT=/etc/mykhaya/dev sh infrastructure/scripts/dev-deploy.sh config-check
```

This checks file presence, the exact allow-list and deny-list per file,
permissions and ownership, placeholders, DEV/PROD separation (no live Stripe key,
production Firebase project, production APNs topic or production paths),
database roles and passwords against `postgres.env`, identical shared secrets,
and that the merged Compose model gives each service exactly its restated values
plus its own files. It builds, stops and restarts nothing. Fix every reported
item and repeat until it passes.

## 5. Cut over

```sh
export MYKHAYA_DEV_CONFIG_ROOT=/etc/mykhaya/dev   # also add to the deploy account's profile
make dev-up
sh infrastructure/scripts/dev-deploy.sh state     # expect: active
```

`make dev-up` runs the full preflight (configuration contract, merged-model
provenance, ports, network drift), builds images, validates the merged runtime
configuration in throwaway containers, and only then records the cutover state
**pending** in `/etc/mykhaya/dev/.service-env-state`. It then starts postgres and
redis, migrates, replaces api, worker, scheduler, web and caddy, runs liveness
and readiness checks, and records **active** only after they pass.

| State | Meaning | Legacy `make dev-up` |
|---|---|---|
| absent / `legacy` | before cutover, or after a completed rollback | allowed |
| `pending` | cutover started, not yet verified healthy | refused |
| `active` | service-env deployed and healthy | refused |
| `rollback-pending` | deliberate rollback started, not yet complete | refused without the rollback flag |

If the deployment stops for any reason after validation (failed migration,
unhealthy service, failed readiness, interruption), the state stays **pending**:
nothing can silently redeploy the legacy root `.env`. Recover by fixing the cause
and rerunning `make dev-up` with the variable set (each step is idempotent), or
roll back deliberately. Failures during validation leave the state and every
running container untouched. Later routine updates in `active` stay `active`,
even if they fail. The state file is written atomically, holds no secret, and an
unrecognised or linked state file stops every deployment until it is inspected.

Live acceptance after cutover (not covered by local tests): sign-in (password,
MFA, Apple, Google), Control Centre access and MFA, a test email from the
Control Centre, a push to a registered DEV device, a Stripe sandbox checkout and
webhook, a DVLA/DVSA lookup, monitoring states in the Control Centre, and worker
and scheduler heartbeats.

Keep the legacy root `.env` unchanged until the Owner declares DEV stable; it is
the rollback source.

## Rollback

Rollback restores the previous configuration mapping without touching data,
schemas, credentials or keys:

```sh
unset MYKHAYA_DEV_CONFIG_ROOT    # and remove it from the deploy account's profile
MYKHAYA_DEV_LEGACY_ENV_ROLLBACK=1 make dev-up
sh infrastructure/scripts/dev-deploy.sh state    # expect: legacy
```

The rollback runs the legacy preflight and validation first, records
**rollback-pending** before recreating containers, and records **legacy** after
the health checks pass. If it fails part-way, the state stays rollback-pending and
the same command (with the flag) resumes it; running service-env `make dev-up`
instead abandons the rollback and resumes the cutover. Setting both
`MYKHAYA_DEV_CONFIG_ROOT` and the rollback flag is refused.

If the Compose or deploy-script revision itself must be reverted, deploy the
previous commit as described in [dev-deployment.md](dev-deployment.md#failure-behavior-and-rollback)
(`git switch --detach PREVIOUS_COMMIT` with `MYKHAYA_DEV_ALLOW_NON_DEV_BRANCH=1`).
The legacy path never reads `/etc/mykhaya/dev`, so the new files can stay in place
for a later retry. Do not delete or rotate keys, restore a backup, or run an
Alembic downgrade as part of a configuration rollback.

**Partially recreated services.** Each deploy step is idempotent. If the new
configuration fails after postgres and redis were recreated but before the
application tier, the old application containers keep running and the state is
pending. Either rerun service-env `make dev-up`, or run the rollback command: it
recreates postgres (same volume, so data and passwords are
unchanged), runs migrations (a no-op) and replaces api, worker and scheduler with
the legacy configuration.

**Failed migration.** Migrations run before any application container is
replaced; a failure stops the deploy with the previous api, worker and scheduler
still running. A configuration-only change should never need a migration: if one
fails, the cause is credentials or connectivity (preflight already checks the
migration URL against `postgres.env`). Inspect the `migrate` output and the
Alembic revision before retrying or rolling back.

Verified locally with synthetic data: service-env to legacy and back on real
containers, each recreating postgres, api, worker and scheduler, with zero
migrations applied, unchanged schema and data, readiness passing, and the
isolation checks passing again after roll-forward; a forced migration failure
left the running application containers untouched. The state transitions are
covered by `infrastructure/tests/test_dev_cutover_state.py` (interrupted
deployment, failed build, validation, migration and readiness, partial
recreation, explicit and failed rollback, idempotent reruns, corrupt state).

## Recovery matrix

A configuration rollback restores **only** the configuration mapping. Each other
kind of recovery is separate:

| What | Restored by configuration rollback? | How it is recovered |
|---|---|---|
| Compose configuration (service files, overlay, cutover state) | **Yes** | `MYKHAYA_DEV_LEGACY_ENV_ROLLBACK=1 make dev-up` (above). The `/etc/mykhaya/dev` files stay in place for a retry. |
| Application images and code | No | Deploy the previous commit: `git switch --detach PREVIOUS_COMMIT` and `MYKHAYA_DEV_ALLOW_NON_DEV_BRANCH=1 make dev-up` ([dev-deployment.md](dev-deployment.md#failure-behavior-and-rollback)). F-03 itself changes no application code. |
| Database schema (migrations) | **No. A Compose or configuration rollback can never reverse a schema change.** | The F-03 cutover adds no migration; deploy from the same commit, so `migrate` is a no-op. Older code may run on a newer schema only if that schema is backward-compatible. Never run an Alembic downgrade against live data. |
| Database contents | No | Restore the verified encrypted backup taken before cutover (`make restore`, [backup-and-restore.md](backup-and-restore.md)). Restoring is destructive and needs explicit Owner approval. |
| Home Migration packages | No | **Not recoverable.** Packages (`/data/home-migrations` on `mykhaya_dev_home_migration_data`) are deliberately excluded from backups and expire after `MYKHAYA_HOME_MIGRATION_PACKAGE_TTL_HOURS` (default 24). A lost package can only be regenerated by a new export from the source Home, if that Home still exists; any upload, dry-run or import progress is lost. See the pre-cutover check below. |
| Field-encryption keyrings and the Apple signing key | No | F-03 copies keys, never moves, rotates or regenerates them; keep the originals until the Owner declares DEV stable. A lost keyring is recoverable only through escrow ([sensitive-field-keys.md](sensitive-field-keys.md)). |
| `MYKHAYA_SECRET_KEY` | No | Copied byte-for-byte from the legacy `.env`; the validator requires every service to hold the same value. Never change it during cutover: it signs sessions and decrypts Control Centre secrets (SMTP, push, Stripe) stored in the database ([backup-and-restore.md](backup-and-restore.md#encrypted-platform-secrets-smtp-push-stripe)). |

**Home Migration pre-cutover check (read-only; required before approval).**
Confirm no package is in flight and the volume is referenced by a container:

```sh
docker compose -f compose.yml -f compose.dev.yml exec -T postgres psql -U postgres -d mykhaya -Atc \
  "select status, count(*) from home_migration_packages where completed_at is null group by status"
docker ps -a --filter volume=mykhaya_dev_home_migration_data --format '{{.Names}} {{.Status}}'
```

If any package is not completed, finish or abandon that migration first, or have
the Owner accept its loss in writing. The validator correction prevents the probe
from deleting this volume, but nothing can restore a package that is lost.

## Local verification

`infrastructure/tests/compose.dev-service-env.local-test.yml` runs the real DEV
merge on a workstation without published ports, with no internet egress, and
with the fixed-name Home Migration volume renamed into the test project.
`infrastructure/tests/synthetic_dev_config.py` writes a complete synthetic root.
Never use either on the DEV server.
