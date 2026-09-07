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
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
avatar_destination="$backup_dir/mykhaya-${stamp}-avatars.tar.gz"
manifest="$backup_dir/mykhaya-${stamp}.manifest"
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

if [ "${MYKHAYA_PRODUCTION:-0}" = 1 ]; then
  avatar_dir="${MYKHAYA_AVATAR_HOST_DIR:-/var/lib/docker/volumes/mykhaya_avatar_data/_data}"
  if [ -d "$avatar_dir" ]; then
    tar -czf "$avatar_destination" -C "$avatar_dir" .
  else
    echo "Production avatar directory does not exist: $avatar_dir" >&2
    record_run false "Avatar storage was not available."
    exit 1
  fi
  {
    printf 'created_at=%s\n' "$started_at"
    printf 'database=%s\n' "$destination"
    printf 'avatars=%s\n' "$avatar_destination"
    printf 'git_commit=%s\n' "$(git rev-parse HEAD 2>/dev/null || echo unknown)"
    printf 'version=%s\n' "${MYKHAYA_VERSION:-unknown}"
  } > "$manifest"
fi

size_bytes="$(wc -c < "$destination" | tr -d ' ')"
record_run true "Backup completed and passed integrity verification." "$size_bytes"
if [ "${MYKHAYA_PRODUCTION:-0}" = 1 ]; then
  marker="${MYKHAYA_BACKUP_MARKER:-/var/lib/mykhaya/last-backup.ok}"
  mkdir -p "$(dirname "$marker")"
  printf '%s\n' "$started_at" > "$marker"
  chmod 600 "$marker"
fi
echo "$destination"
