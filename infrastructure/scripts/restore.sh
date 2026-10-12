#!/bin/sh
# Restore a PostgreSQL backup made by backup.sh. See
# docs/operations/backup-and-restore.md — always restore into an isolated
# stack first and complete the documented restore test.
#
#   restore.sh /absolute/path/mykhaya-<stamp>.sql.gz.age   (encrypted, current)
#   restore.sh /absolute/path/mykhaya-<stamp>.sql.gz       (legacy plaintext)
#
# Encrypted backups need the offline age identity, supplied only for the
# duration of the restore:
#   MYKHAYA_BACKUP_AGE_IDENTITY=/path/to/offline/identity.txt
# The identity is read by `age -d` directly; it is never copied, logged or
# written next to the backups.
set -eu
test "$#" -eq 1 || { echo "Usage: restore.sh /absolute/path/backup.sql.gz[.age]" >&2; exit 2; }
source_file="$1"
case "$source_file" in /*) ;; *) echo "Use an absolute backup path" >&2; exit 2;; esac
test -f "$source_file" || { echo "Backup does not exist" >&2; exit 2; }

case "$source_file" in
  *.sql.gz.age)
    identity="${MYKHAYA_BACKUP_AGE_IDENTITY:-}"
    test -n "$identity" || {
      echo "Set MYKHAYA_BACKUP_AGE_IDENTITY to the offline age identity file." >&2; exit 2;
    }
    test -f "$identity" || { echo "The age identity file does not exist." >&2; exit 2; }
    command -v age >/dev/null 2>&1 || { echo "The age tool is not installed." >&2; exit 2; }
    # Authenticate and decompress fully before touching the database: age
    # verifies every chunk, and gzip -t verifies the stream end to end.
    age -d -i "$identity" "$source_file" | gzip -t ||
      { echo "Backup failed decryption or integrity verification." >&2; exit 1; }
    age -d -i "$identity" "$source_file" | gzip -dc |
      docker compose exec -T postgres pg_restore --username postgres --dbname mykhaya \
        --clean --if-exists --no-owner
    ;;
  *.sql.gz)
    echo "WARNING: restoring a legacy UNENCRYPTED backup." >&2
    gzip -t "$source_file"
    gzip -dc "$source_file" | docker compose exec -T postgres pg_restore --username postgres \
      --dbname mykhaya --clean --if-exists --no-owner
    ;;
  *)
    echo "Unrecognised backup file name; expected .sql.gz.age or .sql.gz" >&2
    exit 2
    ;;
esac
