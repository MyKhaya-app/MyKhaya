#!/bin/sh
set -eu
umask 077
backup_dir="${MYKHAYA_BACKUP_DIR:-./backups}"
mkdir -p "$backup_dir"
destination="$backup_dir/mykhaya-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
docker compose exec -T postgres pg_dump --username postgres --dbname mykhaya --format=custom | gzip -9 > "$destination"
gzip -t "$destination"
echo "$destination"
