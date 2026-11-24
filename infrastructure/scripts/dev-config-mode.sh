# DEV configuration mode for host tools (sourced, not executed).
#
# backup.sh, restore.sh, restore-files.sh and billing-readiness.sh run outside
# dev-deploy.sh. This selects the same Compose model the DEV deployment uses,
# from its cutover state files, so those tools keep working after the F-03 and
# Docker Secrets cutovers. Reading the state never changes it.
#
# Without a DEV state file (every workstation, and DEV before cutover) nothing
# changes: stack_compose stays the bare `docker compose`. A cutover or rollback
# that is in progress still resolves, so a backup can always be taken first.
# The caller defines die() and has the repository root as working directory.

dev_select_mode() {
  DEV_TOOL_MODE=legacy
  dev_tool_state=${MYKHAYA_DEV_SERVICE_ENV_STATE:-/etc/mykhaya/dev/.service-env-state}
  if [ ! -e "$dev_tool_state" ] && [ ! -L "$dev_tool_state" ]; then return 0; fi
  . "$1/cutover-state.sh"
  dev_tool_base=$(dirname -- "$dev_tool_state")
  dev_tool_f03=$(cutover_read_state "$dev_tool_state") || exit 1
  dev_tool_secrets=$(cutover_read_state "$dev_tool_base/.secrets-state") || exit 1
  case "$dev_tool_f03" in
    legacy|rollback-pending) return 0 ;;
  esac
  DEV_TOOL_MODE=service-env
  DEV_TOOL_ROOT=$dev_tool_base
  case "$dev_tool_secrets" in
    pending|active)
      DEV_TOOL_MODE=secrets
      DEV_TOOL_ROOT=$dev_tool_base/file-backed ;;
  esac
  [ -f "$DEV_TOOL_ROOT/compose.env" ] || die "the DEV configuration selected by the cutover state is missing"
}

dev_tool_compose() {
  dev_tool_overlays="-f compose.yml -f compose.dev.yml -f compose.dev.service-env.yml"
  [ "$DEV_TOOL_MODE" != secrets ] || dev_tool_overlays="$dev_tool_overlays -f compose.dev.secrets.yml"
  # Secrets the base files interpolate are forced blank, as in dev-deploy.sh.
  # shellcheck disable=SC2086 # a fixed list of options
  MYKHAYA_DB_PASSWORD= MYKHAYA_MIGRATION_DB_PASSWORD= MYKHAYA_POSTGRES_ADMIN_PASSWORD= \
    MYKHAYA_APNS_PRIVATE_KEY= MYKHAYA_DEV_CONFIG_ROOT="$DEV_TOOL_ROOT" \
    docker compose --env-file "$DEV_TOOL_ROOT/compose.env" $dev_tool_overlays "$@"
}
