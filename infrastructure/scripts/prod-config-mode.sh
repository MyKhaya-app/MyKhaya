# Production configuration mode (F-03), sourced by prod-deploy.sh,
# prod-health.sh, prod-logs.sh, prod-install.sh and the backup tooling.
# The caller sets ROOT (the repository root) and defines die().
#
# The mode is selected automatically from the cutover state file, never from a
# shell profile, so a fresh SSH session always uses the active configuration:
#   legacy (or absent)  the repository root .env, unchanged
#   pending | active    one file per service under the PROD root, layered
#                       through compose.production.service-env.yml
#   rollback-pending    an explicit rollback to legacy is in progress
# Deployments refuse every ambiguous state; see prod_select_mode.
#
# Docker Secrets (MK-SEC-001) is a further mode on top of an active F-03, with
# its own state file holding the same four values ("legacy" meaning F-03):
#   pending | active    file-backed/ under the PROD root, layered through
#                       compose.production.secrets.yml

PROD_STATE_FILE=${MYKHAYA_PROD_SERVICE_ENV_STATE:-/etc/mykhaya/prod/.service-env-state}
PROD_CONFIG_ROOT=$(dirname -- "$PROD_STATE_FILE")
PROD_SECRETS_STATE_FILE=$PROD_CONFIG_ROOT/.secrets-state
PROD_OVERLAY=compose.production.service-env.yml
PROD_SECRETS_OVERLAY=compose.production.secrets.yml
PROD_RUNBOOK=docs/operations/prod-service-config-migration.md

. "$ROOT/infrastructure/scripts/cutover-state.sh"

# prod_select_mode deploy|readonly
#   deploy    for anything that creates or replaces containers. Refuses an
#             unfinished cutover or rollback unless the matching explicit flag
#             is set: MYKHAYA_PROD_SERVICE_ENV_CUTOVER=1 (set only by
#             prod-service-env-migrate.sh) or MYKHAYA_PROD_LEGACY_ENV_ROLLBACK=1.
#             Docker Secrets: MYKHAYA_PROD_SECRETS_CUTOVER=1 or
#             MYKHAYA_PROD_SECRETS_ROLLBACK=1, set only by
#             prod-security-migrate.sh after the Owner's typed approval.
#   readonly  health, logs and backups: always works, so an interrupted
#             migration can be diagnosed and backed up.
# Sets PROD_STATE, PROD_SECRETS_STATE, PROD_CONFIG_MODE (legacy|service-env|
# secrets), PROD_ACTIVE_ROOT and PROD_ENV_SOURCE (the file holding interpolation
# and host values for that mode).
prod_select_mode() {
  case "$PROD_STATE_FILE" in
    /*) ;;
    *) die "MYKHAYA_PROD_SERVICE_ENV_STATE must be an absolute path" ;;
  esac
  if [ -n "${MYKHAYA_PROD_CONFIG_ROOT:-}" ] && [ "${MYKHAYA_PROD_CONFIG_ROOT%/}" != "$PROD_CONFIG_ROOT" ]; then
    die "MYKHAYA_PROD_CONFIG_ROOT is set to a different directory from the cutover state ($PROD_CONFIG_ROOT); unset it, the state selects the configuration"
  fi
  PROD_STATE=$(cutover_read_state "$PROD_STATE_FILE") || exit 1
  PROD_SECRETS_STATE=$(cutover_read_state "$PROD_SECRETS_STATE_FILE") || exit 1
  prod_rollback=${MYKHAYA_PROD_LEGACY_ENV_ROLLBACK:-0}
  prod_cutover=${MYKHAYA_PROD_SERVICE_ENV_CUTOVER:-0}
  prod_secrets_rollback=${MYKHAYA_PROD_SECRETS_ROLLBACK:-0}
  prod_secrets_cutover=${MYKHAYA_PROD_SECRETS_CUTOVER:-0}
  if [ "${1:-deploy}" = readonly ]; then
    case "$PROD_STATE:$PROD_SECRETS_STATE" in
      active:pending|active:active) PROD_CONFIG_MODE=secrets ;;
      pending:*|active:*) PROD_CONFIG_MODE=service-env ;;
      *) PROD_CONFIG_MODE=legacy ;;
    esac
  elif [ "$PROD_SECRETS_STATE" != legacy ] || [ "$prod_secrets_cutover" = 1 ] ||
    [ "$prod_secrets_rollback" = 1 ]; then
    [ "$PROD_STATE" = active ] ||
      die "Docker Secrets need an active service-specific configuration, but its state is $PROD_STATE; inspect both state files ($PROD_RUNBOOK)"
    [ "$prod_rollback" = 0 ] && [ "$prod_cutover" = 0 ] ||
      die "Docker Secrets are $PROD_SECRETS_STATE; roll them back with prod-security-migrate.sh rollback before changing the F-03 configuration"
    [ "$prod_secrets_cutover" = 0 ] || [ "$prod_secrets_rollback" = 0 ] ||
      die "MYKHAYA_PROD_SECRETS_CUTOVER and MYKHAYA_PROD_SECRETS_ROLLBACK are both set; choose one"
    if [ "$prod_secrets_rollback" = 1 ]; then
      [ "$PROD_SECRETS_STATE" != legacy ] || die "Docker Secrets are not active; there is nothing to roll back"
      PROD_CONFIG_MODE=service-env
    elif [ "$prod_secrets_cutover" = 1 ]; then
      [ "$PROD_SECRETS_STATE" != active ] || die "Docker Secrets are already active; no cutover is needed"
      PROD_CONFIG_MODE=secrets
    elif [ "$PROD_SECRETS_STATE" = active ]; then
      PROD_CONFIG_MODE=secrets
    else
      die "the Docker Secrets migration is $PROD_SECRETS_STATE ($PROD_SECRETS_STATE_FILE).\nInspect: MYKHAYA_PRODUCTION=1 sh infrastructure/scripts/prod-security-migrate.sh status"
    fi
  else
    [ "$prod_rollback" = 1 ] && [ "$prod_cutover" = 1 ] &&
      die "MYKHAYA_PROD_SERVICE_ENV_CUTOVER and MYKHAYA_PROD_LEGACY_ENV_ROLLBACK are both set; choose one"
    if [ "$prod_rollback" = 1 ]; then
      [ "$PROD_STATE" != legacy ] ||
        die "MYKHAYA_PROD_LEGACY_ENV_ROLLBACK=1 is set but the configuration is already legacy; unset it"
      PROD_CONFIG_MODE=legacy
    elif [ "$prod_cutover" = 1 ]; then
      [ "$PROD_STATE" != active ] ||
        die "the service-specific PROD configuration is already active; no cutover is needed"
      PROD_CONFIG_MODE=service-env
    else
      case "$PROD_STATE" in
        legacy) PROD_CONFIG_MODE=legacy ;;
        active) PROD_CONFIG_MODE=service-env ;;
        pending) die "a service-env cutover was started but has not been verified ($PROD_STATE_FILE).\nInspect: MYKHAYA_PRODUCTION=1 sh infrastructure/scripts/prod-service-env-migrate.sh --status\nResume it with the same prod-service-env-migrate.sh --apply command, or roll back deliberately ($PROD_RUNBOOK)." ;;
        rollback-pending) die "a rollback to the legacy configuration has not completed ($PROD_STATE_FILE).\nResume it with MYKHAYA_PROD_LEGACY_ENV_ROLLBACK=1 ($PROD_RUNBOOK)." ;;
      esac
    fi
  fi
  # Derived from the state on every run; never inherited from the shell.
  unset MYKHAYA_PROD_SECRETS
  PROD_ACTIVE_ROOT=$PROD_CONFIG_ROOT
  if [ "$PROD_CONFIG_MODE" != legacy ]; then
    for prod_name in COMPOSE_PROJECT_NAME COMPOSE_FILE COMPOSE_PROFILES COMPOSE_ENV_FILES DOCKER_HOST DOCKER_CONTEXT; do
      eval "prod_value=\${$prod_name:-}"
      [ -z "$prod_value" ] || die "$prod_name is set in the environment; unset it so the production project and daemon cannot change"
    done
    MYKHAYA_PROD_CONFIG_ROOT=$PROD_CONFIG_ROOT
    export MYKHAYA_PROD_CONFIG_ROOT
    if [ "$PROD_CONFIG_MODE" = secrets ]; then
      PROD_ACTIVE_ROOT="$PROD_CONFIG_ROOT/file-backed"
      MYKHAYA_PROD_SECRETS=1
      export MYKHAYA_PROD_SECRETS
    fi
    PROD_ENV_SOURCE="$PROD_ACTIVE_ROOT/compose.env"
  else
    PROD_ENV_SOURCE="$ROOT/.env"
  fi
}

# prod_compose ARGS: docker compose for the selected mode. Legacy is exactly
# the historical command. Service-env interpolates from compose.env and
# postgres.env only; the PostgreSQL passwords can come only from postgres.env,
# and the other interpolated secrets are forced blank (the overlay removes the
# keys that used them), so no shell-exported value can leak in. Docker Secrets
# interpolates from its own compose.env only, with every such secret blank.
prod_compose() {
  if [ "$PROD_CONFIG_MODE" = secrets ]; then
    (
      MYKHAYA_PROD_CONFIG_ROOT=$PROD_ACTIVE_ROOT
      export MYKHAYA_PROD_CONFIG_ROOT
      for prod_name in DB_PASSWORD MIGRATION_DB_PASSWORD POSTGRES_ADMIN_PASSWORD APNS_PRIVATE_KEY FCM_PRIVATE_KEY; do
        export "MYKHAYA_$prod_name="
      done
      exec docker compose --env-file "$PROD_ACTIVE_ROOT/compose.env" \
        -f "$ROOT/compose.yml" -f "$ROOT/compose.production.yml" -f "$ROOT/$PROD_OVERLAY" \
        -f "$ROOT/$PROD_SECRETS_OVERLAY" "$@"
    )
  elif [ "$PROD_CONFIG_MODE" = service-env ]; then
    (
      unset MYKHAYA_DB_PASSWORD MYKHAYA_MIGRATION_DB_PASSWORD MYKHAYA_POSTGRES_ADMIN_PASSWORD
      MYKHAYA_APNS_PRIVATE_KEY=
      MYKHAYA_FCM_PRIVATE_KEY=
      export MYKHAYA_APNS_PRIVATE_KEY MYKHAYA_FCM_PRIVATE_KEY
      exec docker compose \
        --env-file "$PROD_CONFIG_ROOT/compose.env" --env-file "$PROD_CONFIG_ROOT/postgres.env" \
        -f "$ROOT/compose.yml" -f "$ROOT/compose.production.yml" -f "$ROOT/$PROD_OVERLAY" "$@"
    )
  else
    docker compose -f compose.yml -f compose.production.yml "$@"
  fi
}

# prod_env_value KEY: a non-secret value from the mode's interpolation file.
prod_env_value() {
  [ -f "$PROD_ENV_SOURCE" ] || return 0
  sed -n "s/^$1=//p" "$PROD_ENV_SOURCE" | tail -n 1 | tr -d '\r'
}
