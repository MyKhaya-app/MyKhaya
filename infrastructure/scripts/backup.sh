#!/bin/sh
# See docs/operations/backup-and-restore.md. Records every attempt (success or
# failure) into the backup_runs table so the Platform Control Centre's Backup
# Service health card reflects reality instead of assuming health from the
# presence of a backup directory — see mykhaya.routers.platform's /health
# endpoint. The application itself never triggers a backup; this script (run by
# cron/an operator) is the only writer of that table.
#
# Encryption (age, public-key): the database dump and the persistent file
# stores are streamed through `age -R <recipients>` and only ciphertext ever
# touches disk. The host holds the *public* recipient(s) only; the matching
# private identity lives offline and is supplied solely at restore time
# (restore.sh). A plaintext backup is never written in production, and
# outside production only with an explicit MYKHAYA_BACKUP_ALLOW_PLAINTEXT=1.
#
# Required (production):
#   MYKHAYA_BACKUP_AGE_RECIPIENTS_FILE  default /etc/mykhaya/backup-recipients.txt
#                                       one `age1…` public key per line
# Optional (environment, else .env, else default):
#   MYKHAYA_BACKUP_DIR                  default ./backups
#   MYKHAYA_BACKUP_ALLOW_PLAINTEXT=1    non-production only, never in production
set -eu
umask 077
# Same resolution as backup-preflight.sh: environment, then .env, then the
# documented default — so the preflight verifies exactly what is used here.
env_value() {
  [ -f "${MYKHAYA_ENV_FILE:-.env}" ] || return 0
  sed -n "s/^$1=//p" "${MYKHAYA_ENV_FILE:-.env}" | tail -n 1 | tr -d '\r'
}
backup_dir="${MYKHAYA_BACKUP_DIR:-$(env_value MYKHAYA_BACKUP_DIR)}"
backup_dir="${backup_dir:-./backups}"
recipients_file="${MYKHAYA_BACKUP_AGE_RECIPIENTS_FILE:-$(env_value MYKHAYA_BACKUP_AGE_RECIPIENTS_FILE)}"
recipients_file="${recipients_file:-/etc/mykhaya/backup-recipients.txt}"
production="${MYKHAYA_PRODUCTION:-0}"
allow_plaintext="${MYKHAYA_BACKUP_ALLOW_PLAINTEXT:-0}"
mkdir -p "$backup_dir"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
manifest="$backup_dir/mykhaya-${stamp}.manifest"
# Persistent application file stores (directory name under /data in the
# application containers, and Compose volume key). Home Migration packages
# (/data/home-migrations) are deliberately excluded: they are short-lived
# plaintext Home copies purged after use, and backing them up would preserve
# them far beyond that lifecycle.
file_stores="avatars support-attachments vehicle-photos meal-images"
. "$(dirname "$0")/file-store-volumes.sh"
status_dir="$(mktemp -d)"
trap 'rm -rf "$status_dir"; rm -f "$backup_dir"/*.partial' EXIT

record_run() {
  succeeded="$1"
  detail="$2"
  size_bytes="${3:-NULL}"
  completed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  docker compose exec -T postgres psql --username postgres --dbname mykhaya -v ON_ERROR_STOP=1 \
    -c "INSERT INTO backup_runs (created_at, updated_at, started_at, completed_at, succeeded, size_bytes, detail)
        VALUES (now(), now(), '$started_at', '$completed_at', $succeeded, $size_bytes, '$detail');" \
    >/dev/null
}

fail() {
  record_run false "$1" || true
  echo "Backup failed: $1" >&2
  exit 1
}

# --- Decide encryption mode before anything is written ----------------------
encrypt=1
if [ ! -f "$recipients_file" ]; then
  if [ "$production" = 1 ]; then
    fail "Backup encryption recipients are not configured."
  elif [ "$allow_plaintext" = 1 ]; then
    encrypt=0
    echo "WARNING: writing an UNENCRYPTED non-production backup (MYKHAYA_BACKUP_ALLOW_PLAINTEXT=1)." >&2
  else
    echo "No age recipients file at $recipients_file." >&2
    echo "Configure MYKHAYA_BACKUP_AGE_RECIPIENTS_FILE, or for a throwaway non-production" >&2
    echo "backup set MYKHAYA_BACKUP_ALLOW_PLAINTEXT=1 explicitly." >&2
    fail "Backup encryption recipients are not configured."
  fi
fi
if [ "$encrypt" = 1 ]; then
  command -v age >/dev/null 2>&1 || fail "The age encryption tool is not installed."
  # A private identity must never sit beside the backups or be used to make them.
  if grep -q "AGE-SECRET-KEY" "$recipients_file"; then
    fail "The recipients file contains a private key; it must hold public keys only."
  fi
  grep -q "^age1" "$recipients_file" || fail "The recipients file has no age public key."
  if [ -n "${MYKHAYA_BACKUP_AGE_IDENTITY:-}" ]; then
    fail "A decryption identity is set in the backup environment; remove it."
  fi
  suffix=".age"
else
  suffix=""
fi

# seal FILE: read a stream on stdin and write it to FILE (encrypted unless
# plaintext was explicitly allowed outside production), via a .partial file
# that is only renamed into place once complete.
seal() {
  if [ "$encrypt" = 1 ]; then
    age -R "$recipients_file" -o "$1.partial"
  else
    cat > "$1.partial"
  fi
}

# Each producer's own exit status is written to a small file, because a POSIX
# sh pipeline only reports the status of its last command — without this a
# failed pg_dump/tar feeding gzip/age would look like success.
database_destination="$backup_dir/mykhaya-${stamp}.sql.gz${suffix}"
{
  docker compose exec -T postgres pg_dump --username postgres --dbname mykhaya --format=custom
  echo $? > "$status_dir/pg_dump"
} | gzip -9 | seal "$database_destination" || fail "Database backup encryption or write failed."
[ "$(cat "$status_dir/pg_dump" 2>/dev/null)" = 0 ] || fail "pg_dump failed."

files_destination="$backup_dir/mykhaya-${stamp}-files.tar.gz${suffix}"
# The file stores are read straight from their named volumes by a throwaway,
# locked-down helper container (read-only mounts, no network, no secrets,
# no capabilities) — NOT through the api container, so a stopped or
# unhealthy api never prevents a backup. See file-store-volumes.sh.
volume_mounts="$(file_store_volume_mounts ro)" || fail "Persistent file-store volumes could not be resolved."
helper_image="$(file_store_helper_image)" || fail "The backup helper image could not be resolved."
# shellcheck disable=SC2086 # fixed, space-separated mount/store lists.
{
  docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges --user 10001:10001 $volume_mounts \
    --entrypoint tar "$helper_image" -C /data -cf - $file_stores
  echo $? > "$status_dir/tar"
} | gzip -9 | seal "$files_destination" || fail "File-store backup encryption or write failed."
[ "$(cat "$status_dir/tar" 2>/dev/null)" = 0 ] || fail "Persistent file stores could not be archived."

# --- Verify before publishing ---------------------------------------------------
for partial in "$database_destination.partial" "$files_destination.partial"; do
  [ -s "$partial" ] || fail "A backup artefact is empty."
  if [ "$encrypt" = 1 ]; then
    # age's binary format begins with this exact header line. The content
    # itself can only be verified with the offline identity (restore test).
    head -c 21 "$partial" | grep -q "^age-encryption.org/v1" ||
      fail "A backup artefact is not age-encrypted."
  else
    gzip -t "$partial" || fail "The backup archive failed integrity verification."
  fi
done
mv "$database_destination.partial" "$database_destination"
mv "$files_destination.partial" "$files_destination"

checksum() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

{
  printf 'created_at=%s\n' "$started_at"
  printf 'encryption=%s\n' "$([ "$encrypt" = 1 ] && echo age || echo none)"
  printf 'database=%s\n' "$(basename "$database_destination")"
  printf 'database_sha256=%s\n' "$(checksum "$database_destination")"
  printf 'files=%s\n' "$(basename "$files_destination")"
  printf 'files_sha256=%s\n' "$(checksum "$files_destination")"
  printf 'file_stores=%s\n' "$file_stores"
  printf 'git_commit=%s\n' "$(git rev-parse HEAD 2>/dev/null || echo unknown)"
  printf 'version=%s\n' "${MYKHAYA_VERSION:-unknown}"
} > "$manifest"

size_bytes="$(cat "$database_destination" "$files_destination" | wc -c | tr -d ' ')"
if [ "$encrypt" = 1 ]; then
  record_run true "Encrypted backup completed and passed format verification." "$size_bytes"
else
  record_run true "Unencrypted non-production backup completed." "$size_bytes"
fi
if [ "$production" = 1 ]; then
  marker="${MYKHAYA_BACKUP_MARKER:-/var/lib/mykhaya/last-backup.ok}"
  mkdir -p "$(dirname "$marker")"
  printf '%s\n' "$started_at" > "$marker"
  chmod 600 "$marker"
fi
echo "$database_destination"
echo "$files_destination"
