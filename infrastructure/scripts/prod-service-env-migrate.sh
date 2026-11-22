#!/bin/sh
# One-command PROD service-specific configuration migration (F-03).
#
#   MYKHAYA_PRODUCTION=1 MYKHAYA_RELEASE_TAG=vX.Y.Z \
#     sh infrastructure/scripts/prod-service-env-migrate.sh --check --expect-host HOST
#
# Actions: --check (read-only), --backup-config, --apply, --status,
# --rollback-check. The runbook is docs/operations/prod-service-config-migration.md.
# The logic lives in prod_service_env_migration.py; the container cutover
# itself is the normal prod-deploy.sh update of the deployed release.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT"
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[ "${MYKHAYA_PRODUCTION:-}" = 1 ] || die "set MYKHAYA_PRODUCTION=1 explicitly on the production host"
[ "$(id -u)" -ne 0 ] || die "run as the deployment account, not root"
command -v python3 >/dev/null 2>&1 || die "python3 is required"
command -v docker >/dev/null 2>&1 || die "Docker is required"
# Everything this creates (reports, backups, staging) is private.
umask 077
# -I: ignore PYTHON* variables and user site-packages.
exec python3 -I "$ROOT/infrastructure/scripts/prod_service_env_migration.py" "$@"
