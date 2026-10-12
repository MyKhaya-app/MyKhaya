# Sensitive-Field Keys: Provisioning, Escrow and Restore

This runbook covers the keyrings used by `mykhaya.crypto` for application-level
encryption of Tier-1 fields and for keyed lookup tokens (blind indexes). See
the Phase 1 Sensitive Data Protection audit for the design rationale.

**Status:** Phase 2A (library, key loading) is commissioned on DEV. **Phase 2B
(Driveway dual-write) is disabled by default** and commissioned on DEV only. Phase
2C adds an operator-run backfill for missing ciphertext. See
[Phase 2B: Driveway dual-write](#phase-2b-driveway-dual-write) and
[Phase 2C: backfill](#phase-2c-backfill-missing-driveway-ciphertext) below. While a
keyring is unprovisioned, the services log `sensitive_field_keys_not_provisioned`
and run normally.

> **Phase 2B gate.** No production field may be encrypted until the
> [recovery exercise](#recovery-exercise-phase-2b-gate) below **and** an
> encrypted-backup restore test
> ([backup-and-restore.md](backup-and-restore.md#phase-2b-prerequisite-mandatory-gate))
> have both succeeded and been recorded. This applies to enabling
> `MYKHAYA_DRIVEWAY_FIELD_ENCRYPTION_WRITE` in production.

## Phase 2B: Driveway dual-write

**Current state**

- Migration `0115_vehicle_ciphertext` adds nullable `vehicles.registration_ciphertext`
  and `vehicles.vin_ciphertext` (TEXT, no index, no constraint, no default).
- `MYKHAYA_DRIVEWAY_FIELD_ENCRYPTION_WRITE` defaults to **`false`**. Off, Driveway
  behaves exactly as before and writes no ciphertext.
- On, every registration/VIN write (Driveway create/update and Home Migration import,
  all through `mykhaya.driveway_sensitive`) also stores an AES-256-GCM envelope. It is
  bound to the vehicle's id and to its column (purposes `vehicle.registration` /
  `vehicle.vin`). Unchanged values are not re-encrypted, and clearing a value clears
  both columns. If no field-encryption keyring is usable, the write fails with a 503
  and nothing is committed; it never writes plaintext only.
- Whenever a plaintext value changes, its ciphertext is either re-encrypted (flag on)
  or cleared (flag off), so a ciphertext can never describe an old value.
- **Plaintext remains authoritative.** Every read (API, UI, reminders, provider
  logic) uses `registration` / `vin`. Ciphertext is never serialised, logged,
  audited or included in Home Migration packages; import re-derives it for the new
  row.
- **No backfill has occurred.** Vehicles written while the flag was off have no
  ciphertext.
- **Ciphertext must not yet be treated as a recoverable representation.** It is a
  partial, redundant copy. Backups, restores and every recovery decision still rely
  on the plaintext columns until a later phase says otherwise.

**Verification tool (read-only, counts only):**

```sh
docker compose exec -T api python -m mykhaya.tools.driveway_ciphertext_check
```

It decrypts each populated ciphertext with the application's keyring and binding,
compares it with the plaintext, and prints counts (`*_verified`, `*_mismatch`,
`*_decrypt_failed`, `*_without_ciphertext`, …). It never prints a value, envelope or
ID and runs in a `READ ONLY` transaction. Exit status 0 means every populated
ciphertext matches.

**Rollout sequence (DEV first; PROD only after the Phase 2B gate)**

1. Deploy the migration and code with `MYKHAYA_DRIVEWAY_FIELD_ENCRYPTION_WRITE=false`
   (the default) through the normal deployment process.
2. Verify normal Driveway operation: list, create, edit, photo and reminders behave
   as before. `driveway_ciphertext_check` shows `*_ciphertext: 0`.
3. Enable dual-write in **DEV only**: set `MYKHAYA_DRIVEWAY_FIELD_ENCRYPTION_WRITE=true`
   in the DEV `.env`. The field-encryption keyring must already load
   (`sensitive_field_keys_loaded`).
4. Restart only `api`, `worker` and `scheduler` through the supported DEV deployment
   process (`make dev-update`/`dev-deploy.sh`), never by hand-editing containers.
5. Create and update **synthetic** DEV vehicles (made-up registrations and VINs):
   create with both, change each, clear each, and edit an unrelated field.
6. Verify ciphertext exists without displaying it: run `driveway_ciphertext_check`
   and confirm `registration_ciphertext` / `vin_ciphertext` counts rose. Never `SELECT`
   the columns to a terminal.
7. Confirm the same run reports `*_verified` equal to `*_ciphertext` and zero
   `*_mismatch` / `*_decrypt_failed` (decryption through application code).
8. Confirm the API still returns the plaintext contract only: vehicle list/detail
   responses contain `registration` (and `vin` for owner/admin) and no
   `*_ciphertext` field or `mkf1.` value.

To roll back, set the flag back to `false` and restart the same services. Plaintext
was never changed by the flag. Rows written while it was on keep a valid envelope
until their plaintext next changes, at which point it is cleared. The migration's
downgrade drops only the two ciphertext columns.

## Phase 2C: backfill missing Driveway ciphertext

`mykhaya.tools.driveway_ciphertext_backfill` fills **missing ciphertext only**. It
populates `registration_ciphertext` where `registration` is set and the ciphertext is
NULL, and `vin_ciphertext` likewise.

- **Operator-triggered only.** Nothing runs it automatically: no migration, startup,
  worker, scheduler or deployment hook (tests enforce this).
- **Dry-run is the default.** It counts what would change in a `READ ONLY`
  transaction and writes nothing. Writing requires `--apply`, plus
  `MYKHAYA_DRIVEWAY_FIELD_ENCRYPTION_WRITE=true` (so normal writes already keep
  ciphertext in step) and a usable field-encryption keyring. Otherwise it refuses
  with exit status 2 before touching any row.
- **Uses the same keyring and bindings as normal writes** (`registration_binding` /
  `vin_binding` on the vehicle id). It encrypts the stored plaintext exactly, with no
  trimming or normalisation.
- **Plaintext is never modified or removed.** No other column changes either,
  including `updated_at`, so open edit forms are not invalidated. Existing ciphertext
  is never replaced or re-encrypted, and NULL plaintext gets no ciphertext.
- **One transaction.** Any failure rolls everything back (exit status 1). Eligible rows
  are locked and each update is guarded on "ciphertext still NULL, plaintext
  unchanged", so a concurrent edit is never overwritten. Re-running is a no-op.
- **Counts only.** Output and logs never contain a registration, VIN, vehicle or Home
  ID, ciphertext or key material.
- **Plaintext remains authoritative.** Reads are **not** switched, and ciphertext is
  still not the sole recoverable representation.
- **This is not key rotation.** It never re-encrypts existing ciphertext under a newer
  key; rotation remains the separate procedure below.
- **This does not enable production rollout.** The Phase 2B gate (encrypted-backup
  restore test **and** key-escrow recovery exercise) still applies before
  dual-write, and therefore any backfill, in production.

**DEV procedure**

```sh
dc() { docker compose -f compose.yml -f compose.dev.yml exec -T api "$@"; }
dc python -m mykhaya.tools.driveway_ciphertext_check            # 1. baseline
dc python -m mykhaya.tools.driveway_ciphertext_backfill          # 2. dry-run
#                                                                   3. review counts
make backup                                                      # 4. fresh encrypted backup
dc python -m mykhaya.tools.driveway_ciphertext_backfill --apply  # 5. apply
dc python -m mykhaya.tools.driveway_ciphertext_check            # 6. verify
dc python -m mykhaya.tools.driveway_ciphertext_backfill --apply  # 8. re-run: 0 backfilled
```

Step 7: the check must report `registration_without_ciphertext = 0`,
`vin_without_ciphertext = 0`, and zero `*_mismatch` / `*_decrypt_failed`. Step 8: the
second `--apply` must report `registration_backfilled = 0` and `vin_backfilled = 0`.

## What the keys are, and what they are not

| Keyring | File | Used for |
|---|---|---|
| Field encryption | `field-encryption-keys.json` | AES-256-GCM encryption of individual sensitive values |
| Blind index | `blind-index-keys.json` | HMAC-SHA256 lookup tokens for equality search |

- **Independent of `MYKHAYA_SECRET_KEY`.** Rotating the session secret signs people
  out. It never affects data encrypted with these keyrings, and vice versa.
- **Never in PostgreSQL, never in a backup, never in git.** The database holds only
  ciphertext envelopes (`mkf1.<key_id>.<…>`) and tokens (`<key_id>.<hex>`).
- **Two separate keyrings.** Startup refuses identical key material in both.
- **Losing every copy of a field-encryption key that has encrypted data means
  permanently losing that data.** That is why the escrow and the recovery exercise
  are mandatory before Phase 2B.

## Document format

```json
{
  "format": "mykhaya-keyring-v1",
  "purpose": "field-encryption",
  "environment": "production",
  "active": "k2026a",
  "keys": { "k2026a": "<base64 of 32 random bytes>" }
}
```

- `environment` is enforced in both directions. Production refuses a `development`
  or `test` keyring, and development/test refuse a `production` keyring, so real
  keys can never be loaded on a developer machine.
- Key IDs are 1-24 characters of `a-z 0-9 - _`. Never reuse a retired ID.
- `active` selects the key for **new** writes. Every key listed stays readable.

## 1. Generate the production keyrings

Do this on the production host (or an equally trusted machine), in a private tmpfs
working directory. Never paste key material into chat, tickets, CI logs or shell
history. The generator writes the document only to stdout and validates it with the
application's own parser first. Key bytes come from `os.urandom`.

```sh
umask 077
work=$(mktemp -d -p /dev/shm mykhaya-keys.XXXXXX)   # RAM-backed, private
cd /path/to/MyKhayaApp
gen() {
  docker compose -f compose.yml -f compose.production.yml run --rm --no-deps -T \
    --entrypoint python api -m mykhaya.crypto.generate_keyring "$@"
}
gen --purpose field-encryption --environment production --key-id k2026a \
  > "$work/field-encryption-keys.json"
gen --purpose blind-index --environment production --key-id b2026a \
  > "$work/blind-index-keys.json"
```

Record the **non-secret fingerprints** in the operations log. They identify the exact
key material without revealing it:

```sh
for f in field-encryption-keys.json blind-index-keys.json; do
  docker compose -f compose.yml -f compose.production.yml run --rm --no-deps -T \
    -v "$work/$f:/keycheck/$f:ro" --entrypoint python api \
    -m mykhaya.crypto.generate_keyring --fingerprint "/keycheck/$f"
  sha256sum "$work/$f"
done
```

## 2. Escrow offline (before installing)

1. Copy both files from `$work` onto **two** independent offline media, for example
   two encrypted USB drives, or one drive plus a password-manager vault entry. Store
   them apart from each other, **never with database or file backups**, and
   **separately from the backup age identity**.
2. On each medium, verify the copy is **byte-for-byte identical**:
   `sha256sum <medium>/field-encryption-keys.json` must equal the value logged in
   step 1, and the same for the blind-index file.
3. Label each medium with environment, key IDs and date only. Never add the hostname
   or anything that helps match a stolen medium to stolen backups.
4. Record who holds each copy in the operations log (never the key material).

## 3. Install on the production host

The directory is bind-mounted **read-only** into `api`, `worker` and `scheduler` only,
through the `x-api` volume anchor in `compose.yml`. `postgres`, `migrate`, `web`,
`caddy`, `redis` and `test` never receive it, and it is never inside a backed-up path.

```sh
sudo install -d -m 0750 -o root -g 10001 /etc/mykhaya/field-keys
sudo install -m 0440 -o root -g 10001 "$work/field-encryption-keys.json" /etc/mykhaya/field-keys/
sudo install -m 0440 -o root -g 10001 "$work/blind-index-keys.json" /etc/mykhaya/field-keys/
shred -u "$work"/*.json && rmdir "$work"
```

`10001` is the API image's runtime UID/GID (`apps/api/Dockerfile`). Set the mount
source in the production `.env`:

```
MYKHAYA_FIELD_KEYS_HOST_DIR=/etc/mykhaya/field-keys
```

**Verify the mount scope** before restarting. Only `api`, `worker` and `scheduler`
may show a target:

```sh
docker compose -f compose.yml -f compose.production.yml config --format json |
  python3 -c 'import json,sys; c=json.load(sys.stdin)
for n,s in sorted(c["services"].items()):
    t=[v["target"] for v in s.get("volumes",[]) if v.get("target","").startswith("/run/secrets")]
    print(f"{n:10} {t}")'
```

Restart `api worker scheduler`. Each must log `sensitive_field_keys_loaded` with
`field_active_key_id=k2026a` and `blind_index_active_key_id=b2026a`. Key bytes are
never logged. A malformed, wrong-environment or half-provisioned configuration stops
startup with `KeyConfigurationError`. That is intentional: failing closed is safer
than serving with unreadable data.

When Phase 2B ships, set `MYKHAYA_SENSITIVE_FIELD_KEYS_REQUIRED=true` so a missing
keyring is fatal.

**Development/test only:** `MYKHAYA_FIELD_ENCRYPTION_KEYS` and
`MYKHAYA_BLIND_INDEX_KEYS` may hold the JSON documents directly (generate with
`--environment development`). Production **rejects** these variables at startup.
Tests never read them; they build deterministic test-only keyrings in code.

## 4. Restore keyrings from escrow (disaster recovery)

1. Rebuild the host and restore the database and file stores per
   [backup-and-restore.md](backup-and-restore.md), into an isolated stack first.
2. Take **one** escrow medium. Verify each file's SHA-256 against the operations log
   (**byte-for-byte equivalence**).
3. Install the files exactly as in step 3.
4. Confirm **cryptographic equivalence**: run the `--fingerprint` command against the
   installed files. The output (key IDs, active ID and per-key fingerprints) must
   match the logged values exactly. A fingerprint is HMAC-SHA256(key, fixed label),
   so equal fingerprints mean equal key bytes for every key ID, even if a copy was
   re-saved with different formatting.
5. Start `api worker scheduler` and confirm `sensitive_field_keys_loaded` with the
   logged active key IDs.
6. From Phase 2B on, also run that phase's verification command, which decrypts a
   sample of encrypted rows and reports counts only, and confirm zero failures
   before opening the stack to users.

If the first medium fails verification, use the second. Never "repair" a key file.

## Recovery exercise (Phase 2B gate)

Before any production field is encrypted, and again after every rotation:

1. On an isolated machine or stack, with **no access to the production key
   directory**, recover both keyrings from escrow alone (section 4, steps 2-4).
2. Confirm SHA-256 and fingerprints match the operations log.
3. Encrypt and decrypt a synthetic value with the recovered keyring (for example a
   short script calling `encrypt_sensitive_value` / `decrypt_sensitive_value` with a
   throwaway `FieldBinding`), then destroy the isolated copy.
4. Record date, operator, media used and result.

Pair it with the encrypted-backup restore test in
[backup-and-restore.md](backup-and-restore.md#phase-2b-prerequisite-mandatory-gate).
Both must pass.

## 5. Rotation (later)

1. Build the new keyring, keeping every existing key and making a new ID active:
   ```sh
   docker compose -f compose.yml -f compose.production.yml run --rm --no-deps -T \
     --entrypoint python api -m mykhaya.crypto.generate_keyring \
     --rotate /run/secrets/mykhaya/field-encryption-keys.json --key-id k2027a \
     > "$work/field-encryption-keys.json"
   ```
   (The `api` service already mounts the current keyring read-only at
   `/run/secrets/mykhaya`.)
2. Fingerprint it, escrow it (section 2) and only then install it in place of the
   old file (section 3). Restart `api worker scheduler` and confirm the new
   `field_active_key_id`.
3. New writes use the new key, and existing envelopes still decrypt with their
   recorded key ID. The re-encryption pass (Phase 2B onwards, built on
   `reencrypt_sensitive_value`) moves old rows to the active key and is idempotent.
4. Retire an old key only after the re-encryption pass reports zero rows on it. Keep
   its escrow copy until every backup that may contain such rows has expired.
5. Repeat the recovery exercise.

Blind-index keys rotate the same way. Lookups during the transition use
`blind_index_candidates`, so rows not yet re-indexed still match.
