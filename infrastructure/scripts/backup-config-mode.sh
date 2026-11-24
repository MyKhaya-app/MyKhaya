# Configuration mode for backup.sh, restore.sh and restore-files.sh (sourced).
#
# Outside production, and in production while the configuration is legacy,
# stack_compose is exactly the historical bare `docker compose` and host values
# come from .env. With the PROD service-specific configuration pending or
# active (F-03), stack_compose addresses the same `mykhaya` project through the
# PROD overlay, and MYKHAYA_ENV_FILE defaults to the PROD root's compose.env,
# which holds MYKHAYA_BACKUP_DIR and MYKHAYA_BACKUP_AGE_RECIPIENTS_FILE.
# Backups and restores work in every cutover state, including an interrupted
# one, so the system can always be backed up before recovery.

# On the DEV host, the DEV cutover state selects the DEV overlays the same way
# (dev-config-mode.sh). Workstations have no such state, so nothing changes.

stack_compose() { docker compose "$@"; }
# Historical default. It leaves restored objects owned by postgres, so the
# migrator cannot manage them; the DEV per-service modes keep the original
# ownership instead (the roles exist in any database init-db.sh created).
RESTORE_OWNER_OPTION=--no-owner

if [ "${MYKHAYA_PRODUCTION:-}" = 1 ]; then
  ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
  die() { printf '%b\n' "ERROR: $*" >&2; exit 1; }
  . "$ROOT/infrastructure/scripts/prod-config-mode.sh"
  prod_select_mode readonly
  if [ "$PROD_CONFIG_MODE" = service-env ]; then
    stack_compose() { prod_compose "$@"; }
    if [ -z "${MYKHAYA_ENV_FILE:-}" ]; then
      MYKHAYA_ENV_FILE=$PROD_ENV_SOURCE
      export MYKHAYA_ENV_FILE
    fi
  fi
else
  ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
  die() { printf '%b\n' "ERROR: $*" >&2; exit 1; }
  . "$ROOT/infrastructure/scripts/dev-config-mode.sh"
  dev_select_mode "$ROOT/infrastructure/scripts"
  if [ "$DEV_TOOL_MODE" != legacy ]; then
    stack_compose() { dev_tool_compose "$@"; }
    RESTORE_OWNER_OPTION=
    if [ -z "${MYKHAYA_ENV_FILE:-}" ]; then
      MYKHAYA_ENV_FILE=$DEV_TOOL_ROOT/compose.env
      export MYKHAYA_ENV_FILE
    fi
  fi
fi
