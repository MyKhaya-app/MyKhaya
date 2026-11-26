# PROD security migration: one command, two approved stages

**Status:** implemented and rehearsed with synthetic data and disposable Docker
resources only. Nothing here has been run on the production host. Every live step
needs the Owner, and synthetic results do not prove that the host is ready.

`infrastructure/scripts/prod-security-migrate.sh` takes production from its current
configuration to file-backed Docker Secrets (MK-SEC-001 v1.2):

| Stage | Change | Detail |
|---|---|---|
| 1. F-03 | one `.env` becomes one file per service | [prod-service-config-migration.md](prod-service-config-migration.md) |
| 2. Docker Secrets | every credential leaves the container environment and becomes a read-only file, granted per service | this page |

It finds the current stage from the protected state files in `/etc/mykhaya/prod/`
(`.service-env-state` and `.secrets-state`), never from a shell profile, and runs only
what remains. It never generates, rotates, prints or hashes a credential, removes or
renames a volume, rebuilds an image, changes a schema or rolls back by itself.

## What changes, and what restarts

| | Stage 1 | Stage 2 |
|---|---|---|
| api, worker, scheduler | recreated | recreated |
| **postgres** | not touched | **recreated once, same volume** (its environment holds three passwords, which cannot be removed from a running container) |
| redis, web, caddy | not touched | not touched (checked by container ID) |
| API interruption to budget | about 1 minute | about 2 minutes |

In the local rehearsal the API failed about 22 one-second probes over both stages
together; a production host will differ. Plan a 60-minute window: the checks take most of it and run before anything changes.
During an interruption web pages load, but API calls fail. Unchanged in both
stages: every credential value, database role and password, schema, volume, network,
port, domain, image, the field keyrings and the Apple key. The legacy `.env` and the F-03 files stay
in place as the rollback sources, so the exposure reduction is complete only when the
Owner later approves retiring them.

After stage 2 each process has a role and only its own secrets: the migrate process
holds the migration password alone, and the scheduler has presence flags instead of
DVLA, DVSA and Stripe webhook credentials. The grants are those of
`apps/api/mykhaya/process_roles.py`, as on DEV.

## Before the window

1. **A release containing this tooling is deployed normally**, in legacy mode
   (`make prod-update RELEASE=vX.Y.Z`), and has been stable. The migration reuses exactly
   those images and refuses any other checkout, tag, image or uncommitted change. The release
   before this tooling (v0.11.8) contains none of it, so this first update is a
   normal release with its own approval and database migrations. Because that update still runs
   the *old* deployment script, follow the bootstrap note in
   [backup-and-restore.md](backup-and-restore.md#production-deployment-preflight).
2. `sudo install -d -m 0750 -o "$USER" -g "$USER" /etc/mykhaya/prod` (once).
3. `MYKHAYA_FIELD_KEYS_HOST_DIR` and `MYKHAYA_APPLE_KEY_HOST_DIR` in `.env` name
   directories outside the checkout, not readable by other users.
4. The deployment account can use `sudo` (secret files are owned by root).
5. A PROD backup has been **restored and migrated in an isolated stack**; note the date
   ([backup-and-restore.md](backup-and-restore.md#restore-testing-is-mandatory)).
6. `MYKHAYA_SECRET_KEY`, both field keyrings, the Apple key and the backup identity are
   recoverable from escrow, apart from each other and from the backups.
7. The host name is confirmed by the Owner in writing.
8. No Home Migration is in progress. `completed`, `expired` and `discarded` packages do
   not block. `uploaded` and `importing` always do. Any other state blocks unless the
   Owner accepts that exact number with `--accept-unresolved-packages N`.

## Command sequence

As the deployment account, in the deployment checkout:

```sh
export MYKHAYA_PRODUCTION=1 MYKHAYA_RELEASE_TAG=vX.Y.Z
m() { sh infrastructure/scripts/prod-security-migrate.sh "$@" --expect-host CONFIRMED-HOST-NAME; }

m status                     # where production is now; changes nothing
make prod-backup             # then copy the three files off-host and verify them there
m backup-config              # then copy it off-host and test-decrypt it there
m check                      # every prerequisite; repeat until it passes

m apply --confirm-offhost-backup mykhaya-STAMP.manifest \
        --confirm-offhost-config-backup mykhaya-config-STAMP-ID.tar.age \
        --confirm-key-escrow \
        --confirm-restore-rehearsal YYYY-MM-DD
                             # type: MIGRATE PROD F-03
                             # type: MIGRATE PROD SECRETS

m accept                     # independent verification; repeat after a day
```

The backup must be less than two hours old when each stage starts. To pause between the stages,
answer the second question with anything else: production stays on F-03, which is a supported
state. Before continuing later, take a new `make prod-backup` **and** a new
`m backup-config` (which then holds the F-03 files), and run the same `apply`; it continues
with stage 2. `m provision` and `m verify` prepare and prove the secret files beforehand
without touching a service; `apply` does both if they have not been done.

## What is checked

`check` and `apply` refuse, and change nothing, unless all of this holds:

- **Host:** `--expect-host` matches; not root; no DEV configuration on the host; no
  `COMPOSE_*`, `DOCKER_*` or migration flags in the shell; enough disk space. One
  migration command at a time.
- **Release:** HEAD is exactly the tag, on `origin/main`, clean; every container runs
  that release's images.
- **Backup:** encrypted, recent, matching its manifest and the database's own record;
  off-host copies, escrow and restore evidence confirmed.
- **State:** the two state files agree with each other and with the configuration the
  running containers were created from; no database migration is running.
- **Volumes:** each service uses the expected volume. A volume whose Compose labels
  differ is reported and left alone. Container changes run without terminal input, so
  Compose can never ask to recreate a volume; nothing passes `--yes`.
- **Equivalence:** the F-03 files equal the running containers; every secret file equals
  the F-03 value, byte for byte; unconfigured credentials are empty files nothing reads.
- **Grants:** file owner `root`, mode `0440`, group `10001` (application) or `70`
  (PostgreSQL); the exact per-service grants in the merged model; runtime Settings accept
  the configuration in throwaway containers; redis, web and caddy keep their hash.

Before stage 2 a baseline is stored in `/etc/mykhaya/prod/.secrets-snapshot.json`
(names, times and counts only): database cluster identity, schema revision, volume
creation times, key-file metadata, container IDs and counts of encrypted values that
cannot be read. Afterwards `apply` verifies the running services against their contract,
the baseline, 30 seconds without a restart, health, and (as root) scans Docker metadata of running
**and stopped** containers, process arguments and logs for every secret. Only then is
the state recorded `active`. `accept` repeats all of it independently, and
also fails if a service has restarted at any time since it was created.

### Manual acceptance

Sign in with password and MFA, Google and Apple (web and native); Control Centre sign-in;
a test email; a push to PROD iOS, Android and web devices; a real Stripe webhook
delivery (create no charge for testing); a DVLA and a DVSA lookup; the Control Centre health cards; worker
and scheduler heartbeats; `make prod-backup`. These cannot be rehearsed synthetically.

## If something stops

`m status` always works and names the next step. Nothing is rolled back automatically.

| Stage shown | Meaning | Do |
|---|---|---|
| `legacy` | not started | `check`, `apply` |
| `f03-pending` | stage 1 started, not verified | fix, rerun the same `apply`, or `rollback` |
| `f03-rollback-pending` | stage 1 rollback unfinished | rerun `rollback` |
| `f03-active` | stage 1 done | `apply` continues |
| `secrets-pending` | stage 2 started, not verified | fix, rerun the same `apply`, or `rollback` |
| `secrets-rollback-pending` | stage 2 rollback not verified | rerun `rollback` |
| `secrets-active` | done | `accept` |
| `inconsistent` | state files contradict each other | stop; inspect both files |

While a stage is pending, ordinary deployments and direct rollbacks are refused; health,
logs and backups keep working. Resuming keeps the original baseline and requires the same
release. An application container left stopped by the interruption does not prevent a
resume. If PostgreSQL itself is not running, use `rollback`.

## Rollback

```sh
m rollback-check             # what is possible from here; changes nothing
m rollback                   # one stage at a time, after a typed phrase
```

| From | Goes to | Type | Recreates |
|---|---|---|---|
| `secrets-*` | F-03 files | `ROLL BACK PROD SECRETS` | postgres (same volume), api, worker, scheduler |
| `f03-*` | legacy `.env` | `ROLL BACK PROD TO LEGACY` | api, worker, scheduler |

A rollback changes the **configuration only**. It never reverses a schema change,
restores data or changes a credential. If data must be recovered, that is a separate,
Owner-approved restore of a verified backup
([backup-and-restore.md](backup-and-restore.md)), never an Alembic downgrade.

Roll back if `accept` reports anything, a service restarts, a provider that worked
stops working, or encrypted data cannot be read. If a credential was changed only in
the secret files after the migration, `rollback-check` warns: the F-03 value would return.

## After the migration

- `make prod-update`, `prod-health`, `prod-logs`, `prod-backup` and `prod-restore` use
  the active configuration automatically in every session.
- Settings live in `/etc/mykhaya/prod/file-backed/*.env`. To change a credential,
  change the F-03 file first (the source for `verify`), then the secret file as root,
  keeping owner and mode. Rotation is a separate, approved task.
- Never run `docker compose` by hand on this host.

## Local verification

`infrastructure/tests/test_prod_secrets.py` covers the contract, merged model, mode
selection in every state combination, and the orchestrator's rules.
`infrastructure/scripts/check-prod-secrets-migration.sh` (also in CI) runs the real
scripts, images and PostgreSQL in a disposable nested Docker daemon: refusals, both
stages, interruption before and after container replacement, resume, rollback to F-03
and to legacy, volume and encrypted-data preservation, exposure scans, and an isolated
restore followed by an Alembic migration.
