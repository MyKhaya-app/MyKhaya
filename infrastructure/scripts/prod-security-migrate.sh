#!/bin/sh
# PROD security migration (MK-SEC-001 v1.2): legacy .env -> F-03 per-service
# files -> file-backed Docker Secrets. Run by the Owner on the PROD host, from
# the deployed release checkout, as the deployment account (never root; single
# steps use sudo). See docs/operations/prod-docker-secrets-migration.md.
#
#   MYKHAYA_PRODUCTION=1 MYKHAYA_RELEASE_TAG=vX.Y.Z \
#     sh infrastructure/scripts/prod-security-migrate.sh ACTION --expect-host HOST
#
#   status          current state and inventory (read-only)
#   check           every prerequisite of the next stage (changes no service)
#   backup-config   age-encrypted backup of the configuration files
#   provision       create file-backed/ from the F-03 files (changes no service)
#   verify          prove the provisioned files equal the F-03 values
#   apply           run the remaining stages, each after a typed approval
#   accept          independently verify the running deployment
#   rollback-check  which rollback is possible from here
#   rollback        roll back one stage, after a typed approval
#
# Nothing here generates, rotates, prints or hashes a credential, removes a
# volume, downgrades a schema or rolls anything back automatically.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT"
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[ "${MYKHAYA_PRODUCTION:-}" = 1 ] || die "set MYKHAYA_PRODUCTION=1 explicitly on the production host"
[ "$(id -u)" -ne 0 ] || die "run as the deployment account, not root"
command -v python3 >/dev/null 2>&1 || die "python3 is required"
command -v docker >/dev/null 2>&1 || die "Docker is required"
umask 077
exec python3 -I -B "$ROOT/infrastructure/scripts/prod_security_migration.py" "$@"
