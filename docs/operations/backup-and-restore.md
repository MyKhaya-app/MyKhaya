# Backup and Restore

`make backup` / `make prod-backup` (`infrastructure/scripts/backup.sh`) produce, in `MYKHAYA_BACKUP_DIR` (default `backups/`, mode `umask 077`):

| Artefact | Contents |
|---|---|
| `mykhaya-<stamp>.sql.gz.age` | Custom-format `pg_dump`, gzip-compressed, **age-encrypted** |
| `mykhaya-<stamp>-files.tar.gz.age` | All persistent file stores (`avatars`, `support-attachments`, `vehicle-photos`, `meal-images`), **age-encrypted** |
| `mykhaya-<stamp>.manifest` | Non-secret metadata: encryption mode, artefact names, SHA-256 of each ciphertext, file stores included, commit, version |

Redis is coordination state and is not the authoritative backup. Home Migration packages (`/data/home-migrations`) are **deliberately excluded**: they are short-lived plaintext Home copies purged after use, and backing them up would keep them far beyond that lifecycle.

## Encryption model (age, public-key)

Both artefacts are streamed through `age -R <recipients>` as they are produced. **Plaintext never touches disk.** The backup host holds only the **public** recipient(s); the matching **private identity is kept offline** and is supplied only for a restore. So a stolen backup *and* a compromised backup host still do not reveal the data.

- Recipients file: `MYKHAYA_BACKUP_AGE_RECIPIENTS_FILE`, default `/etc/mykhaya/backup-recipients.txt`, holding one `age1…` public key per line (more than one line = any listed identity can restore).
- The script **refuses** to run if the recipients file contains a private key (`AGE-SECRET-KEY`), if `MYKHAYA_BACKUP_AGE_IDENTITY` is set in its environment, or if `age` is missing.
- **Production never writes an unencrypted backup.** Without a recipients file it fails, records the failure in `backup_runs` and writes nothing. Outside production, an unencrypted backup needs an explicit `MYKHAYA_BACKUP_ALLOW_PLAINTEXT=1`, with a warning.
- Each producer's exit status is checked separately (POSIX `sh` pipelines otherwise hide a failed `pg_dump`/`tar`). Artefacts are written as `.partial` and renamed only after the age header and non-empty checks pass. A failed run leaves no artefact and no success marker.
- `MYKHAYA_BACKUP_DIR` and `MYKHAYA_BACKUP_AGE_RECIPIENTS_FILE` are read from the environment first, then from `.env`, then the defaults. The preflight below uses exactly the same resolution.

### Runtime dependencies

| Needed for a backup | Why | If it is unavailable |
|---|---|---|
| `postgres` service running | `pg_dump` runs inside it. Its Compose labels identify the project's volumes, and its already-present, pinned image (which ships `tar`) is reused for the file-store helper, so no extra image is pulled. | The run fails, records `succeeded=false` in `backup_runs` (if the database is reachable), publishes nothing and leaves the success marker untouched. |
| The four file-store named volumes exist | They are mounted directly. | The run fails the same way and names the missing volume. |
| `api` / `worker` / `scheduler` / `web` | **Not needed.** | A stopped or unhealthy `api` no longer blocks backups or restores. |

The file stores are read by a throwaway helper container that mounts the named volumes **read-only** (`--network none`, read-only root filesystem, `--cap-drop ALL`, `no-new-privileges`, uid 10001, no environment, no secrets). It does **not** go through `docker compose exec api`. The application container holds every application secret; the helper holds none, so this is strictly narrower access than before as well as one fewer dependency. `restore-files.sh` uses the same helper with writable mounts, so file stores can be restored on a rebuilt host **before** the application is started (create the volumes first with `docker compose create api`, which starts nothing).

## Production deployment preflight

`infrastructure/scripts/backup-preflight.sh` runs inside `prod-deploy.sh validate`, and as the **first step of `prod-deploy.sh update`**, before any fetch, checkout, build, migration or restart. If any check fails, the deployment stops with nothing changed. It verifies:

1. `age` is installed.
2. The recipients file exists and is readable.
3. It holds **age public recipients only**: at least one `age1…` key, no `AGE-SECRET-KEY`, and no other non-comment lines.
4. It is not writable by group or others.
5. The backup destination exists (or can be created) and is writable.
6. No private identity is exposed to the backup process: `MYKHAYA_BACKUP_AGE_IDENTITY` is not set in the environment or in `.env`, and no file inside the backup directory contains an age private key.

It never relaxes `backup.sh`'s refusal to write a plaintext backup in production.

**First deployment of this release (bootstrap).** `prod-deploy.sh update` runs the copy of the script that is currently checked out, which predates the preflight. So, before deploying this release, run the release's own preflight manually from the checkout directory:

```sh
git fetch origin "refs/tags/$TAG:refs/tags/$TAG"
git show "refs/tags/$TAG:infrastructure/scripts/backup-preflight.sh" > /tmp/mykhaya-backup-preflight.sh
MYKHAYA_ROOT="$PWD" sh /tmp/mykhaya-backup-preflight.sh && rm /tmp/mykhaya-backup-preflight.sh
```

Then take an encrypted backup with the new tooling (`make prod-backup` after the update, or the release's `backup.sh` extracted the same way) **before** relying on it.

### One-time setup

On a trusted offline machine:

```sh
age-keygen -o mykhaya-backup-identity.txt     # PRIVATE — escrow offline, never on the server
age-keygen -y mykhaya-backup-identity.txt     # prints the public recipient (age1…)
```

On the production host (Debian/Ubuntu: `apt install age`):

```sh
sudo install -d -m 0755 /etc/mykhaya
echo "age1…" | sudo tee /etc/mykhaya/backup-recipients.txt >/dev/null
sudo chmod 0644 /etc/mykhaya/backup-recipients.txt
```

Escrow the identity on two independent offline media, kept **apart from the backups and apart from the sensitive-field keyrings** (see [sensitive-field-keys.md](sensitive-field-keys.md)). Losing every copy of the identity makes every backup unrecoverable.

## Restore testing is mandatory

1. Start an isolated stack with new volumes and no public ingress.
2. Supply the offline identity only for the duration of the restore:
   `MYKHAYA_BACKUP_AGE_IDENTITY=/media/offline/mykhaya-backup-identity.txt make restore FILE=/absolute/path/to/mykhaya-<stamp>.sql.gz.age`
   (decryption and gzip integrity are fully verified before `pg_restore` starts), then
   `MYKHAYA_BACKUP_AGE_IDENTITY=… make restore-files FILE=/absolute/path/to/mykhaya-<stamp>-files.tar.gz.age`.
   Check each artefact's SHA-256 against the manifest first.
3. Run migrations, start the application, verify readiness, record counts for users/Homes/memberships/audit/outbox, open a vehicle photo and an avatar, and complete a login plus cross-Home denial check.
4. Record the backup identifier, restore duration, tester and result. Destroy the isolated restored data securely after the test, and remove the identity from the restore machine.

## Legacy plaintext backups

Unencrypted `*.sql.gz` dumps made before this change can still be restored with `make restore FILE=…sql.gz` (a warning is printed). They are **never** modified or deleted automatically, and no deployment step touches them. Retire them only by following this procedure, in order, and record each step in the operations log:

1. **Create** a new encrypted backup: `make prod-backup`.
2. **Verify ciphertext only.** The backup directory must contain only `*.age` artefacts and the manifest for that run. Check that each artefact starts with the `age-encryption.org/v1` header (`head -c 21 FILE`) and that its SHA-256 matches the manifest. Searching the artefacts for any known plaintext value must find nothing.
3. **Restore it successfully**, into an isolated stack, using the offline identity (see *Restore testing is mandatory* above), and pass every verification step.
4. **Only then** deal with each legacy dump. Either encrypt it (`age -R /etc/mykhaya/backup-recipients.txt -o FILE.age FILE`, verify as in step 2, then securely delete the plaintext original), or securely delete it (`shred -u FILE` on non-copy-on-write storage; on cloud/SSD/CoW storage delete it and rely on volume encryption, because overwriting is not guaranteed). Remember any copies outside the host, such as off-host transfers and sync folders (see the cloud-sync warning below).

If step 3 fails, stop and keep the legacy dumps. They may be the only restorable backup.

A Docker volume, filesystem snapshot without database consistency, or an untested dump is not a backup claim.

`backups/` is gitignored and must never be committed; it is a working directory for `make backup`/`make restore`, not long-term storage. Dumps left here contain real user data and must be moved to an approved backup destination and deleted locally. In particular, do not run `make backup` inside a checkout that lives under a personal cloud-sync folder (Dropbox, OneDrive, Nextcloud, iCloud Drive, etc.) without first confirming that folder's sync scope excludes `backups/` — git ignoring a path only keeps it out of version control, it does not stop a filesystem-level sync client from uploading it.

## Encrypted platform secrets (SMTP, push, Stripe)

Platform-Admin-managed secrets (SMTP password, push VAPID private key, Stripe Test/Live
secret keys and webhook signing secrets) are stored encrypted in the database via
`mykhaya.secrets_crypto`, using a key derived from `MYKHAYA_SECRET_KEY` — never stored
in the database itself. A database backup/restore therefore only recovers usable
secrets if the restoring environment has the **same** `MYKHAYA_SECRET_KEY` as the
environment the backup was taken from; restoring into an environment with a different
`MYKHAYA_SECRET_KEY` (e.g. a fresh disaster-recovery deployment that generated its own)
restores the ciphertext but leaves it undecryptable (`SecretDecryptionError`), the same
way it would after a deliberate key rotation. The affected settings pages fail closed
(`configured=False`) rather than crash in this case, and the credential must simply be
re-entered — treat `MYKHAYA_SECRET_KEY` as part of what a disaster-recovery runbook
needs to restore alongside the database, not something backups regenerate on their own.

## Sensitive-field keyrings

Data encrypted by `mykhaya.crypto` (from Phase 2B) uses keyrings that are deliberately
**not** in the database, **not** in these backups and **not** derived from
`MYKHAYA_SECRET_KEY`. A restored database is only readable with the escrowed keyrings.
Restore them per [sensitive-field-keys.md](sensitive-field-keys.md). Never store them
next to, or inside, a backup.

## Phase 2B prerequisite (mandatory gate)

**No production field may be encrypted with `mykhaya.crypto` until both of these have
succeeded and been recorded in the operations log:**

1. An **encrypted-backup restore test**: a production `make prod-backup` restored with
   the offline age identity into an isolated stack, passing every check in *Restore
   testing is mandatory*.
2. A **key-escrow recovery exercise**: the production keyrings recovered from offline
   escrow alone, installed on an isolated stack, with fingerprints matching production
   (see [sensitive-field-keys.md](sensitive-field-keys.md#recovery-exercise-phase-2b-gate)).

Until both have passed, Phase 2B work must not enable any encrypted write in production.
