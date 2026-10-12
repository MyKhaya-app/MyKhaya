# Sensitive-Field Keys: Provisioning, Escrow and Restore

This runbook covers the keyrings used by `mykhaya.crypto` for application-level
encryption of Tier-1 fields and for keyed lookup tokens (blind indexes). See
the Phase 1 Sensitive Data Protection audit for the design rationale.

**Phase 2A status:** the library and key loading are in place, but **no data is
encrypted with these keys yet**. Provisioning them now is safe and is a
prerequisite for Phase 2B. While unprovisioned, the services log
`sensitive_field_keys_not_provisioned` and run normally.

> **Phase 2B gate.** No production field may be encrypted until the
> [recovery exercise](#recovery-exercise-phase-2b-gate) below **and** an
> encrypted-backup restore test
> ([backup-and-restore.md](backup-and-restore.md#phase-2b-prerequisite-mandatory-gate))
> have both succeeded and been recorded.

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
