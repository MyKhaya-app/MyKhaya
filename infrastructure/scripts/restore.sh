#!/bin/sh
set -eu
test "$#" -eq 1 || { echo "Usage: restore.sh /absolute/path/backup.sql.gz" >&2; exit 2; }
source_file="$1"
test -f "$source_file" || { echo "Backup does not exist" >&2; exit 2; }
gzip -t "$source_file"
case "$source_file" in /*) ;; *) echo "Use an absolute backup path" >&2; exit 2;; esac
gzip -dc "$source_file" | docker compose exec -T postgres pg_restore --username postgres --dbname mykhaya --clean --if-exists --no-owner
