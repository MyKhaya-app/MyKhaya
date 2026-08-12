#!/bin/sh
# See docs/operations/backup-and-restore.md. Records every attempt (success or
# failure) into the backup_runs table so the Platform Control Centre's Backup
# Service health card reflects reality instead of assuming health from the
# presence of a backup directory — see mykhaya.routers.platform's /health
# endpoint. The application itself never triggers a backup; this script (run by
# cron/an operator) is the only writer of that table.
set -eu
umask 077
backup_dir="${MYKHAYA_BACKUP_DIR:-./backups}"
mkdir -p "$backup_dir"
destination="$backup_dir/mykhaya-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

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

if ! docker compose exec -T postgres pg_dump --username postgres --dbname mykhaya --format=custom \
    | gzip -9 > "$destination"; then
  record_run false "pg_dump or compression failed."
  echo "Backup failed: pg_dump or compression failed." >&2
  exit 1
fi

if ! gzip -t "$destination"; then
  record_run false "The backup archive failed integrity verification."
  echo "Backup failed: archive integrity check failed." >&2
  exit 1
fi

size_bytes="$(wc -c < "$destination" | tr -d ' ')"
record_run true "Backup completed and passed integrity verification." "$size_bytes"
echo "$destination"
