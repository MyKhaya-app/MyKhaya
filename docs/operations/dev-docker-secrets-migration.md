# DEV Docker Secrets: cutover and rollback

**Status:** implemented and rehearsed with synthetic credentials in a disposable
Docker daemon (`infrastructure/scripts/check-dev-secrets-migration.sh`, also run by
CI). Not run on the DEV server. Every live step below needs the Owner's approval and
is run by the Owner. PROD is unaffected: it never loads `compose.dev.secrets.yml`.

This moves DEV from the F-03 per-service environment files
([dev-service-config-migration.md](dev-service-config-migration.md)) to Compose file
secrets with a process role per service (MK-SEC-001 v1.2). Nothing is generated or
rotated: each secret file holds the value DEV already uses.

## What changes

| | F-03 | File-backed |
|---|---|---|
| Credentials | environment variables | `/run/secrets/<name>`, mounted only into the services granted them |
| Configuration root | `/etc/mykhaya/dev` | `/etc/mykhaya/dev/file-backed` (generated; F-03 files untouched) |
| Process role | unset | `api`, `worker`, `scheduler`, `migrate` |
| Migrator | holds `MYKHAYA_SECRET_KEY` | holds only the migration database password |
| Scheduler | DVLA, DVSA and Stripe webhook credentials | non-secret presence flags |
| API push-health card | reads the FCM key | reads `MYKHAYA_FCM_PRIVATE_KEY_PRESENT` |
| Field keyrings, Apple key file | read-only directory mounts | the same mounts, read by the hardened reader |
| Volumes, networks, ports, project name | | unchanged |

Files are `root:10001` (application) or `root:70` (PostgreSQL), mode 0440, in 0750
directories. Compose ignores `uid`, `gid` and `mode` for file secrets, so this
ownership is the access control. A credential that is not configured is an empty file
that no setting refers to.

Administrative commands (`docker exec` in the api container) run under the api role.
This is provisional: no dedicated `cli` role is enabled.

**Known limits.** Redis credentials (K-05) are Phase 2B. The PostgreSQL image reads
`POSTGRES_PASSWORD_FILE` itself and may keep the value in its own process environment;
it is not in Docker metadata, and only root or the postgres user could read it. Anyone
with Docker daemon access is root-equivalent and can read any secret.

## State and safety rules

`/etc/mykhaya/dev/.secrets-state` holds `legacy` (not started), `pending`, `active` or
`rollback-pending`, with the same rules as the F-03 state.

- The cutover needs F-03 `active` and can be started only by
  `dev-secrets-cutover.sh`, after its checks and a typed confirmation.
- While it is `pending`, `active` or `rollback-pending`, the F-03 and legacy
  configurations are refused unless a rollback is chosen deliberately.
- A missing PostgreSQL volume is refused; a new database is never created.
- The deploy script replaces api, worker and scheduler **together**. There is no
  per-service cutover.

## Before you start

1. F-03 is active and stable, and DEV runs this commit:
   `make dev-update` with `MYKHAYA_DEV_CONFIG_ROOT=/etc/mykhaya/dev`.
2. `age` is installed and `/etc/mykhaya/backup-recipients.txt` (or
   `MYKHAYA_BACKUP_AGE_RECIPIENTS_FILE` in `compose.env`) holds the public key.
3. An encrypted backup from the last 24 hours: `make backup`. Set
   `MYKHAYA_BACKUP_DIR` in `compose.env` if it is not `./backups`.
4. A DEV backup has been **restored successfully** into an isolated stack
   ([backup-and-restore.md](backup-and-restore.md)).
5. `MYKHAYA_SECRET_KEY`, both field keyrings and the age identity are escrowed, apart
   from each other and from the backups, and an encrypted off-host copy of
   `/etc/mykhaya/dev` exists.
6. No Home Migration package is in progress.
7. Nobody is changing Control Centre credentials, MFA or Home join codes during the
   window (the encrypted-data counts are compared before and after).

## Cutover

As the deployment account, from the DEV checkout:

```sh
s=infrastructure/scripts/dev-secrets-cutover.sh
sh $s status        # read-only: where DEV is now
sh $s check         # prerequisites; stops at the first one that fails
sh $s provision     # sudo: creates file-backed/ and verifies it; no service changes
sh $s verify        # sudo: can be repeated at any time
MYKHAYA_DEV_ATTEST="backup-restored keys-escrowed" sh $s cutover   # type: MIGRATE DEV
```

`status`, `check`, `provision` and `verify` change no service. `check` and `verify`
start only the isolated, read-only probe containers that `config-check` uses. `cutover`
repeats `check` and `verify`, records a non-secret baseline (database identity, schema
revision, volume creation times, encrypted-data counts), asks for confirmation, then:

1. validates the merged configuration in throwaway containers;
2. records `pending`;
3. recreates postgres on the same volume (redis is unchanged);
4. runs migrations as the keyless migrate role (normally none to apply);
5. replaces api, worker and scheduler together, then web, caddy and mailpit;
6. records `active` after liveness and readiness pass;
7. runs `accept`: roles, no credential in any container environment, no restarts, the
   baseline unchanged, and a scan (as root) of Docker metadata, process arguments and
   logs for every provisioned secret.

Afterwards add `MYKHAYA_DEV_SECRETS=1` (with `MYKHAYA_DEV_CONFIG_ROOT`) to the
deployment account's profile. Without it, `make dev-update` refuses to run.

### Manual acceptance

Sign in with password and MFA, Google and Apple; Control Centre sign-in; a test email
and Web Push from the Control Centre; a push to an iOS and an Android DEV device; a
Stripe sandbox checkout and webhook; a DVLA and a DVSA lookup; the Control Centre
health and monitoring cards (FCM must still read configured); worker and scheduler
heartbeats. Run `sh $s accept` again after a day.

### Stop and roll back if

- `accept` reports anything, or the baseline differs;
- a service restarts, or readiness fails;
- a provider that worked before stops working;
- encrypted data cannot be read.

## Rollback

```sh
sh infrastructure/scripts/dev-secrets-cutover.sh rollback   # type: ROLL BACK DEV
```

This works from `pending`, `active` and `rollback-pending`. It returns every service
to the untouched F-03 files, on the same volumes, with the same credentials and no
schema change, then compares the baseline. Remove `MYKHAYA_DEV_SECRETS` from the
profile. The `file-backed` directory stays for a retry. If a rollback stops part-way,
run it again. Rolling back F-03 itself is a separate, later step and is refused until
this one is complete.

If F-03 settings change after a rollback, `verify` reports the difference. Move
`file-backed` aside deliberately and provision again.

## Changing a credential while active

The F-03 files are the source for `verify`, so change the F-03 value first. Then
replace the secret file as root, keeping its owner and mode, and run
`MYKHAYA_DEV_SECRETS=1 make dev-up`. Rotation is a separate, approved task.

## Retiring the F-03 and legacy files

Not part of this procedure. Keep the root `.env` and the F-03 files until the Owner
declares DEV stable; they are the rollback source. They still hold every credential,
so the exposure reduction is complete only once they are retired.
