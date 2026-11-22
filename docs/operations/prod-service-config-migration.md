# PROD service-specific configuration: migration, recovery and rollback

**Status:** prepared and verified locally with synthetic configuration and
disposable Docker resources only. Nothing here has been run on the production
host. Running `--apply` requires explicit Owner approval.

This runbook moves the production deployment from the single repository root
`.env` to one file per service under `/etc/mykhaya/prod/`, with one command.
The contract it enforces is the PROD profile of
[`infrastructure/scripts/service_env_contract.py`](../../infrastructure/scripts/service_env_contract.py)
(`--profile prod`), explained in
[service-configuration-contracts.md](service-configuration-contracts.md). The
DEV equivalent is [dev-service-config-migration.md](dev-service-config-migration.md);
PROD differs from it deliberately where `compose.production.yml` differs from
`compose.dev.yml`.

## Scope: an intermediate stage, not the final secrets architecture

F-03 is an intermediate **service-env** migration. It narrows which service
receives which value; it does not change how values are delivered:

- Credentials are still supplied to containers as **environment variables**
  (from each service's env file), as they were from the root `.env`.
- Database passwords remain **embedded in the connection URLs**
  (`MYKHAYA_DATABASE_URL` in `api.env`, `worker.env`, `scheduler.env` and
  `migrate.env`); PostgreSQL's bootstrap passwords are still Compose
  interpolation values.
- Anyone with **Docker daemon access** on the host (root, the `docker` group,
  or the deployment account) can read these values, for example with
  `docker inspect` or `docker compose config`. The files are `0600`, but that
  protects them only from other unprivileged host users.
- The final **file-backed Docker secrets** implementation remains outstanding
  under MK-SEC-001 v1.2. It needs application changes as well as Compose
  changes: today only the Apple key and the field keyrings are read from files.

## What changes, and what does not

| | Legacy (today) | Service-specific |
|---|---|---|
| Selection | no state file | `/etc/mykhaya/prod/.service-env-state` is `pending` or `active` (automatic; no shell profile) |
| Compose interpolation | repository `.env` | `/etc/mykhaya/prod/compose.env` and `postgres.env` |
| api / worker / scheduler | whole `.env` | `common.env` + own file |
| migrate (`mykhaya_migrator`) | whole `.env` | `common.env` + `migrate.env` |
| postgres, redis, web, caddy | interpolated from `.env` | **identical configuration**, interpolated from the PROD root; never recreated by this change |
| worker / scheduler mounts | every API volume + Apple key | only what they use (as verified on DEV) |

Unchanged: every credential value (copied byte for byte, never rotated or
regenerated), PostgreSQL roles and data, Redis, every named volume including
`mykhaya_prod_home_migration_data`, the field keyrings and Apple key (same
host paths, never read, copied or re-permissioned), Caddy, Cloudflare,
NetBird, trusted proxies, MFA and cookie policy, the release images, and the
database schema. The legacy `.env` is left in place as the rollback source.

How the guarantees are enforced:

- **Configuration-only.** The cutover is the normal `prod-deploy.sh update`
  of the release that is already deployed, with `MYKHAYA_PROD_REUSE_IMAGES=1`:
  images are verified against the tag and commit and reused, never rebuilt or
  pulled. A rebuild would refresh OS packages and unpinned Python dependencies,
  which would be an unrelated application change. Release metadata, including
  the original build time, is exported unchanged. Migrations run (a no-op:
  the database must already be at the release's single Alembic head).
- **Parity.** Before anything changes, every value each service keeps is
  compared in memory with what the running container has now; any difference
  fails the check. Only names are reported.
- **No PostgreSQL recreation by the cutover.** An `env_file` entry alone
  changes a Compose service's hash. PostgreSQL's definition is therefore left
  untouched and its three bootstrap passwords are interpolated from
  `postgres.env`; the check proves postgres, redis, web and caddy keep their
  hash. Only api, worker and scheduler are recreated. A value scan proves no
  other service can contain a PostgreSQL password except each application's
  own database URL.

### PostgreSQL and Redis at later updates: not guaranteed

Nothing prevents Compose from recreating PostgreSQL or Redis at a later
`prod-deploy.sh update`; this is the same as in legacy mode. `update` runs
`up -d` for the application services, and Compose recreates a dependency
whose resolved configuration changed. That happens when:

- a later release changes the `postgres` or `redis` definition (image,
  command, environment, volumes); or
- `postgres.env` or `compose.env` is edited after the cutover.

Without such a change they are not recreated (tested for a configuration-only
update and a normal rebuilding update after cutover). The data stays in the
named volumes either way. Editing a password in `postgres.env` does **not**
change the database role's password (initialisation runs only on an empty
volume); it only recreates the container. Rotate database credentials through
a separate, approved procedure.

`--check` on an active cutover reports this drift before the next update
("its running configuration differs from the PROD root; the next update would
recreate it"), along with any application service whose running environment
no longer matches its file.

## Prerequisites

1. A release containing this tooling has been approved, tagged on `main`, and
   deployed normally (`make prod-update RELEASE=vX.Y.Z`). In legacy mode the
   new code changes nothing. That first update still runs the previous
   release's copy of `prod-deploy.sh`; from this release on, `update`
   re-executes the checked-out release's own script after checkout.
2. Docker Compose 2.24.4 or later; no user-namespace remapping or rootless
   Docker.
3. The Owner has confirmed the production host name in writing (it is passed
   as `--expect-host`; never guess it).
4. A maintenance window (see [Downtime](#expected-downtime)).

## 0. Read-only inventory (names only)

On the production host, as the deployment account, from the deployment
checkout. Nothing here changes state or prints a value.

```sh
hostname; whoami; git describe --exact-match --tags HEAD; git status --short | head
docker compose version --short
printenv COMPOSE_PROJECT_NAME COMPOSE_FILE DOCKER_HOST MYKHAYA_PROD_CONFIG_ROOT   # expect: all empty
sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' .env | sort                       # names only
stat -c '%a %U:%G %n' .env
grep -E '^MYKHAYA_(FIELD_KEYS|APPLE_KEY)_HOST_DIR=' .env | sed 's/=.*/=<set>/'
ls -ld /etc/mykhaya /etc/mykhaya/prod 2>&1
```

If `MYKHAYA_FIELD_KEYS_HOST_DIR` or `MYKHAYA_APPLE_KEY_HOST_DIR` is not set,
Compose has been mounting `./secrets/...` from the checkout. The PROD
contract refuses key directories inside the repository, so set both paths in
`.env` to the existing host directories first (for example the documented
`/etc/mykhaya/field-keys`), and confirm with the Owner. An **empty** key
directory that nothing is configured to read is accepted as "not provisioned"
(a warning; sensitive-field keyrings stay behind the Phase 2B gate). It is
refused as soon as `MYKHAYA_SENSITIVE_FIELD_KEYS_REQUIRED`, a Driveway
encryption flag or a `*_FILE` path needs keys from it.

## 1. Create the configuration root (once)

```sh
sudo install -d -m 0750 -o "$USER" -g "$USER" /etc/mykhaya/prod
```

This is the only manual host change. From now on `make up/down/reset/init/
backend-rebuild/migrate` are refused on this host (`dev-host-guard.sh`):
`make reset` runs `docker compose down -v`, which deletes volumes.

## 2. Check (read-only)

```sh
MYKHAYA_PRODUCTION=1 MYKHAYA_RELEASE_TAG=vX.Y.Z \
  sh infrastructure/scripts/prod-service-env-migrate.sh --check --expect-host <confirmed-host-name>
```

`--check` changes no running container, volume, credential, key or
configuration file. It fetches `origin/main` and the tag (Git refs only),
reads the running containers' metadata and environment in memory, runs
read-only `SELECT`s in PostgreSQL, runs short-lived probe containers (the
network-isolated key-directory probe, and the runtime validator in its own
Compose project with renamed volumes), validates the generated files in a
private staging directory inside the root that it removes afterwards, and
writes a sanitised report to `/var/lib/mykhaya/migration-reports/`.

It checks, and every failure is reported by name, never by value:

| Phase | Checks |
|---|---|
| host | `MYKHAYA_PRODUCTION=1`; host name equals `--expect-host`; not root or UID 10001; no DEV configuration on the host; no `COMPOSE_*`/`DOCKER_HOST`/`DOCKER_CONTEXT` overrides in the shell or `.env`; no `compose.override.yml`; `.env` regular and not readable by others; root owned by the deployment account, `0750`/`0700`; cutover state readable; Compose ≥ 2.24.4; no userns/rootless; free space for Docker data, checkout, root and reports |
| release | tag fetched, HEAD exactly the tag, tag on `origin/main`, clean tree, `validate_version.py`, exactly one Alembic head |
| stack | one running container per service in project `mykhaya`; every application image carries the tag, commit and one build time, and is what the containers run; production/stable; database at the release head |
| backup | `backup-preflight.sh`; marker no older than **2 hours**; the matching manifest's artefacts exist, are age-encrypted and match their checksums; the latest `backup_runs` row is that successful run |
| home-migration | `mykhaya_prod_home_migration_data` exists and a container references it; **zero** packages `uploaded` or `importing` (no override exists) |
| configuration | legacy `.env` parses exactly as Compose reads it; every name is placed, pinned, host-only, or explicitly accepted with `--accept-dropped NAME`; the seven files pass the PROD contract (allow/deny lists, permissions, DEV markers, database roles and passwords, protected key directories); the merged model passes allow-lists, provenance and the bootstrap-password scan; runtime `Settings` accept every service |
| parity | every retained value equals the running container's; mounts keep their sources; postgres, redis, web and caddy keep their configuration hash |

`--check` succeeds only when everything passes; it then lists the operator
gates `--apply` still requires.

## 3. Operator gates (manual confirmation required)

These cannot be proven from the host, so `--apply` requires an explicit
confirmation for each and records it in the report.

1. **Fresh database and file backup, copied off-host.** `make prod-backup`
   no more than two hours before `--apply`. Copy the three artefacts to the
   approved encrypted off-host UK storage and verify their SHA-256 there
   against the manifest. Pass `--confirm-offhost-backup <manifest file name>`.
   The scheduled restore rehearsal
   ([backup-and-restore.md](backup-and-restore.md#restore-testing-is-mandatory))
   remains the proof that backups restore; record its latest result in the
   operations log before approval.
2. **Encrypted configuration backup, copied off-host and test-decrypted.**

   ```sh
   MYKHAYA_PRODUCTION=1 MYKHAYA_RELEASE_TAG=vX.Y.Z \
     sh infrastructure/scripts/prod-service-env-migrate.sh --backup-config --expect-host <confirmed-host-name>
   ```

   This writes `mykhaya-config-<stamp>-<id>.tar.age` and a manifest to
   `/var/lib/mykhaya/config-backups/` (mode `0700`; deliberately **not** the
   backup directory, which is copied off-host with database backups, so the
   backup identity alone never unlocks every provider credential). It holds the
   legacy `.env` and any existing PROD service files, encrypted to the backup
   age recipients; plaintext never touches disk; key material is never
   included. Off-host recovery procedure:
   - copy the file and its `.manifest.json` through the approved encrypted
     channel to the disaster-recovery secret record (the same record that holds
     `MYKHAYA_SECRET_KEY`, never a cloud-sync folder);
   - there, verify `sha256sum` against the manifest;
   - on the offline machine that holds the backup identity, test decryption
     without writing plaintext: `age -d -i <identity> FILE | tar -tvf -`
     must list `legacy.env` (and `prod/*.env` if present). Do not extract on a
     networked machine.

   Pass `--confirm-offhost-config-backup <file name>`. A local backup alone
   never qualifies: the file must match its manifest and the `.env` must be
   unchanged since it was taken.
3. **Key escrow.** Confirm the sensitive-field keyrings (if provisioned) are
   recoverable from escrow ([sensitive-field-keys.md](sensitive-field-keys.md))
   and the Apple key from its escrow or the Apple developer account. Pass
   `--confirm-key-escrow`. The migration never reads, copies or changes keys;
   it records their metadata before and verifies it after.
4. **No Home Migration in flight**, checked automatically; finish or discard
   any uploaded or importing package first.

## 4. Apply

```sh
MYKHAYA_PRODUCTION=1 MYKHAYA_RELEASE_TAG=vX.Y.Z \
  sh infrastructure/scripts/prod-service-env-migrate.sh --apply --expect-host <confirmed-host-name> \
    --confirm-offhost-backup mykhaya-<stamp>.manifest \
    --confirm-offhost-config-backup mykhaya-config-<stamp>-<id>.tar.age \
    --confirm-key-escrow
```

Sequence (it stops at the first failure; nothing is ever rolled back
automatically):

1. Every `--check` phase again, plus the three confirmations. Any finding:
   **REFUSED**, nothing changed, state unchanged.
2. A metadata-only snapshot (`/etc/mykhaya/prod/.cutover-snapshot.json`,
   `0600`): release, commit, Alembic revision, `.env` metadata, key directory
   metadata, the postgres/redis/web/caddy container IDs, volume creation
   times, image IDs.
3. The seven files are written (never overwriting; all or none), all `0600`,
   and validated in place.
4. `prod-deploy.sh update` of the same tag in service-env mode, reusing the
   images: validation (contract, merged model, runtime, Caddy), backup marker,
   then state **pending**, migrations with `mykhaya_migrator` (no-op),
   `up -d` (recreates only api, worker and scheduler), `prod-health.sh`.
5. Verification against the snapshot: the running api, worker and scheduler
   receive exactly their contract (nothing from the root `.env`), with their
   contract's mounts, release metadata and the same images. Compose's
   `com.docker.compose.project.environment_file` label must be present and
   name exactly the PROD root's `compose.env` and `postgres.env`, in that
   order; a missing, malformed or different label fails verification, because
   the container's configuration source cannot then be proven. Postgres,
   redis, web and caddy are the same containers and still match the PROD
   root's configuration hash; the Alembic revision, key metadata, `.env` and
   every volume are unchanged; health checks pass.
6. Only then is the state recorded **active**, and the report written.

Then run live acceptance (manual, not covered by local tests): password sign-in
and MFA, Apple and Google sign-in (web and native), Control Centre access with
MFA, a Control Centre test email, a push to registered iOS (APNs) and Android
(FCM) PROD devices, Stripe webhook delivery (observe a real event; do not
create charges for testing), a DVLA and a DVSA lookup, the Control Centre
monitoring states, worker and scheduler heartbeats, and `make prod-backup`
(which now uses the service files).

## Expected downtime

Builds are skipped and nothing is restarted before the swap, so the window is
the replacement of api, worker and scheduler only. In the local real-container
rehearsal the API was unavailable for **about 40 seconds** from `up` to
readiness (a production host may differ; budget 30–90 seconds). During that
time Caddy returns 502 for API calls; the web front end stays up but its API
calls fail. PostgreSQL, Redis, web and Caddy are not restarted. Background jobs
pause while worker and scheduler restart. Plan a 15-minute window including the
checks; `--apply`'s own checks run before anything changes.

## After the cutover

- `make prod-update RELEASE=…`, `make prod-health`, `make prod-logs`,
  `make prod-backup` and `make prod-restore*` select the service files
  automatically from the state file, in every SSH session.
- Configuration changes are made in `/etc/mykhaya/prod/*.env`, not `.env`;
  `prod-deploy.sh validate` re-checks the contract.
- `make prod-install` refuses (the host is installed).
- Keep the legacy `.env` unchanged until the Owner declares PROD stable: it is
  the rollback source. Retiring it is a separate, later change.
- Re-run `--backup-config` after the cutover so the off-host record also holds
  the generated service files.
- `prod-deploy.sh state` and `--status` show the mode and state.

## Recovery states

| State | Meaning | Legacy deployment | What to do |
|---|---|---|---|
| absent / `legacy` | not started, or rolled back | allowed | `--check` |
| `pending` | cutover started, not verified | **refused** | `--status`, read the report, fix the cause, rerun the same `--apply` (it resumes safely: existing files are validated against `.env`, never regenerated; the original snapshot is kept), or roll back |
| `active` | verified | **refused** (service-env is used) | normal operations |
| `rollback-pending` | rollback started, not finished | refused without the flag | rerun the rollback command, or resume the cutover with `--apply` |

`prod-health.sh`, `prod-logs.sh`, `--status` and the backup scripts work in
every state, so an interrupted migration can always be diagnosed and backed
up. A linked or unrecognised state file stops every deployment until inspected.

| Failure | Result |
|---|---|
| any `--check` finding, missing confirmation | refused; nothing changed |
| validation inside `prod-deploy.sh` | stopped before `pending`; nothing changed |
| migration fails | `pending`; no application container replaced; inspect migrate output and the Alembic revision; never downgrade |
| a service fails to start or health fails | `pending`; nothing rolled back; containers as Compose left them |
| post-cutover verification fails | `pending` with the failing checks in the report; nothing rolled back |
| interruption (SSH drop, reboot) | the state shows where it stopped; rerun `--apply` |

## Rollback

```sh
MYKHAYA_PRODUCTION=1 MYKHAYA_RELEASE_TAG=vX.Y.Z \
  sh infrastructure/scripts/prod-service-env-migrate.sh --rollback-check
# Only with Owner approval:
MYKHAYA_PRODUCTION=1 MYKHAYA_PROD_LEGACY_ENV_ROLLBACK=1 MYKHAYA_PROD_REUSE_IMAGES=1 \
  MYKHAYA_RELEASE_TAG=vX.Y.Z sh infrastructure/scripts/prod-deploy.sh update
```

`--rollback-check` confirms the legacy `.env` is present and unchanged and the
checkout is still the release the cutover used, and prints the command. The
rollback is the normal update in legacy mode, reusing the images: state
`rollback-pending`, migrations (no-op), api/worker/scheduler recreated from the
root `.env`, health checks, then `legacy`. PostgreSQL, Redis, web and Caddy are
not recreated. The `/etc/mykhaya/prod` files stay for a later retry.

The same command rolls back an unfinished cutover (`pending`, for example
after a failed health check). If the rollback itself stops, the state stays
`rollback-pending`, ordinary deployments are refused, and the same command is
rerun once the cause is fixed.

Known limits, to resolve before relying on rollback in production:

- `--rollback-check` compares the checkout with the release the cutover used,
  so it refuses after any later release, even though a legacy rollback may
  still be possible. Treat that as "review manually", not as "eligible".
- It does not detect a value changed in `/etc/mykhaya/prod/*.env` after the
  cutover. A rollback restores the legacy `.env` values; if a credential was
  changed only in the PROD files, the rolled-back services would use the old
  value. Until `.env` is retired, make no credential change in the PROD files
  without the Owner deciding how rollback is preserved.
- `--check` on an active cutover compares with the cutover snapshot, so after
  a later release it also reports the newer containers and images as
  differences. Those expected findings appear alongside any real drift, so
  after a later release `--check` fails and each finding must be read
  individually.

| What | Restored by the configuration rollback? | How it is recovered |
|---|---|---|
| Service configuration mapping | **Yes** | the rollback above |
| Images and code | not changed by the cutover | redeploy a previous tag through `make prod-update` |
| Database schema | not changed (no migration) | **never** downgrade; restore the verified backup only with Owner approval |
| Database contents | not changed | restore the verified encrypted backup (destructive; Owner approval) |
| Home Migration packages | not touched; not in backups | cutover only runs with none in flight |
| Field keyrings, Apple key | never read, copied or changed | escrow ([sensitive-field-keys.md](sensitive-field-keys.md)) |
| `MYKHAYA_SECRET_KEY` and every credential | copied byte for byte, never rotated | the legacy `.env`, and the off-host configuration backup |

## Security notes

- Nothing prints, logs or reports a credential: values are parsed and compared
  in memory; reports, the snapshot and errors carry names and metadata only.
- Every file is created with `umask 077`; the service files, snapshot, reports
  and configuration backup are `0600`, their directories `0700`/`0750`.
- The cutover state lives in the root, is written atomically through the same
  helper DEV uses (`cutover-state.sh`), holds no secret, and only the
  migration's verification records `active`.
- No network exposure, port, firewall, TLS, MFA or proxy setting changes.
- Manual `docker compose -f compose.yml -f compose.production.yml up …`
  commands are not guarded (Compose cannot be), and while the legacy `.env`
  exists they would recreate services with the legacy configuration. Use only
  the `make prod-*` commands and the scripts on this host.

## Local verification

`infrastructure/tests/test_prod_service_env.py` covers the PROD contract,
the merged model against the legacy production model (parity, hashes,
hardening, mounts, provenance, password scan) and the script safety
invariants. `infrastructure/tests/test_prod_cutover.py` runs the real scripts
end to end in a throwaway Git checkout with a simulated daemon: success,
missing secrets, wrong permissions, missing/stale/corrupt backup, invalid
release, wrong or DEV host, in-flight Home Migration, unclassified names,
partial files, failed migration, failed health check, unverified cutover,
retry, rollback (after success, and from `pending` after a failed health
check), a missing, malformed or unexpected `environment_file` label,
PostgreSQL, Redis, volume and Home Migration artefact preservation across
later updates, configuration drift detection, and fail-closed legacy
commands. The simulated daemon removes volumes on `volume rm` and
`down -v`, so destructive calls are observable. These tests use synthetic
values and a simulated daemon; they do not prove behaviour on the
production host.
