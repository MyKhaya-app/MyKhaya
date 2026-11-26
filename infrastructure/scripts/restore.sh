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
. "$(dirname "$0")/backup-config-mode.sh"
test "$#" -eq 1 || { echo "Usage: restore.sh /absolute/path/backup.sql.gz[.age]" >&2; exit 2; }
source_file="$1"
case "$source_file" in /*) ;; *) echo "Use an absolute backup path" >&2; exit 2;; esac
test -f "$source_file" || { echo "Backup does not exist" >&2; exit 2; }

# Objects keep the ownership and grants recorded in the backup, so the migration
# role can manage the restored schema. That needs the roles init-db.sh creates
# in every MyKhaya database; check before anything is changed.
database_query() { stack_compose exec -T postgres psql --username postgres --dbname mykhaya -AtX -v ON_ERROR_STOP=1 -c "$1" </dev/null; }
[ "$(database_query "select count(*) from pg_roles where rolname in ('mykhaya_migrator', 'mykhaya_app')" | tr -d '\r')" = 2 ] ||
  { echo "The target database has no MyKhaya roles; initialise it with the stack's own PostgreSQL service first. Nothing was changed." >&2; exit 1; }

verify_restored_ownership() {
  wrong=$(database_query "select
      (select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relkind in ('r', 'p', 'S', 'v', 'm')
          and pg_get_userbyid(c.relowner) <> 'mykhaya_migrator'
          and not exists (select 1 from pg_depend d where d.objid = c.oid and d.deptype = 'e'))
      + (select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relkind in ('r', 'p') and c.relname <> 'alembic_version'
          and not has_table_privilege('mykhaya_app', c.oid, 'SELECT')
          and not exists (select 1 from pg_depend d where d.objid = c.oid and d.deptype = 'e'))" | tr -d '\r') || wrong=unknown
  [ "$wrong" = 0 ] || {
    echo "The data was restored, but ownership or grants are not as MyKhaya created them ($wrong objects)." >&2
    echo "Do not run migrations or the application on it (docs/operations/backup-and-restore.md)." >&2
    exit 1
  }
  echo "Restored; ownership and grants verified."
}

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
      stack_compose exec -T postgres pg_restore --username postgres --dbname mykhaya \
        --clean --if-exists
    ;;
  *.sql.gz)
    echo "WARNING: restoring a legacy UNENCRYPTED backup." >&2
    gzip -t "$source_file"
    gzip -dc "$source_file" | stack_compose exec -T postgres pg_restore --username postgres \
      --dbname mykhaya --clean --if-exists
    ;;
  *)
    echo "Unrecognised backup file name; expected .sql.gz.age or .sql.gz" >&2
    exit 2
    ;;
esac
verify_restored_ownership
