#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT"

# Configuration mode (F-03). Legacy: the repository root .env, unchanged.
# Service-env: one file per service under an explicitly selected DEV root,
# layered through compose.dev.service-env.yml. Only an explicit
# MYKHAYA_DEV_CONFIG_ROOT selects it; nothing is inferred from the filesystem.
DEV_CONFIG_ROOT=${MYKHAYA_DEV_CONFIG_ROOT:-}
DEV_CONFIG_ROOT=${DEV_CONFIG_ROOT%/}
# Cutover state, kept outside the repository in the DEV configuration root:
#   absent | legacy    root .env deployments (before cutover, or after a rollback)
#   pending            a service-env cutover has started; legacy is refused
#   active             service-env deployed and healthy; legacy is refused
#   rollback-pending   an explicit rollback to legacy has started
# Legacy deployments are refused while the state is pending, active or
# rollback-pending unless MYKHAYA_DEV_LEGACY_ENV_ROLLBACK=1 is set deliberately,
# so a forgotten variable or an interrupted cutover can never silently fall back
# to the root .env. The state never changes credentials, volumes or data.
STATE_FILE=${MYKHAYA_DEV_SERVICE_ENV_STATE:-/etc/mykhaya/dev/.service-env-state}
LEGACY_ROLLBACK=${MYKHAYA_DEV_LEGACY_ENV_ROLLBACK:-0}
if [ -n "$DEV_CONFIG_ROOT" ]; then
  CONFIG_MODE=service-env
  ENV_SOURCE="$DEV_CONFIG_ROOT/compose.env"
  export MYKHAYA_DEV_CONFIG_ROOT="$DEV_CONFIG_ROOT"
else
  CONFIG_MODE=legacy
  ENV_SOURCE=.env
fi

compose() {
  if [ "$CONFIG_MODE" = service-env ]; then
    # Secrets that compose.yml/compose.dev.yml interpolate are forced blank:
    # the overlay removes those keys, and no shell-exported value can leak in.
    MYKHAYA_DB_PASSWORD= MYKHAYA_MIGRATION_DB_PASSWORD= MYKHAYA_POSTGRES_ADMIN_PASSWORD= \
      MYKHAYA_APNS_PRIVATE_KEY= \
      docker compose --env-file "$DEV_CONFIG_ROOT/compose.env" \
      -f compose.yml -f compose.dev.yml -f compose.dev.service-env.yml "$@"
  else
    docker compose -f compose.yml -f compose.dev.yml "$@"
  fi
}

say() {
  printf '\n==> %s\n' "$*"
}

die() {
  printf '\nERROR: %b\n' "$*" >&2
  exit 1
}

env_value() {
  key=$1
  sed -n "s/^${key}=//p" "$ENV_SOURCE" | tail -n 1 | tr -d '\r'
}

find_python() {
  if command -v python3 >/dev/null 2>&1; then
    printf '%s\n' python3
  elif command -v python >/dev/null 2>&1; then
    printf '%s\n' python
  else
    return 1
  fi
}

service_owns_port() {
  service=$1
  container_port=$2
  expected_host_port=$3
  container_id=$(compose ps --status running -q "$service" 2>/dev/null || true)
  [ -n "$container_id" ] || return 1
  docker port "$container_id" "${container_port}/tcp" 2>/dev/null |
    grep -Eq ":${expected_host_port}$"
}

check_port() {
  label=$1
  bind_address=$2
  port=$3
  service=$4
  container_port=$5
  if service_owns_port "$service" "$container_port" "$port"; then
    return 0
  fi
  "$PYTHON" - "$label" "$bind_address" "$port" <<'PY'
import errno
import socket
import sys

label, address, raw_port = sys.argv[1:]
port = int(raw_port)
family = socket.AF_INET6 if ":" in address else socket.AF_INET
sock = socket.socket(family, socket.SOCK_STREAM)
try:
    sock.bind((address, port))
except OSError as exc:
    if exc.errno in {errno.EADDRINUSE, 10048}:
        raise SystemExit(f"ERROR: {label} port {address}:{port} is already occupied")
    raise SystemExit(f"ERROR: cannot bind {label} port {address}:{port}: {exc}")
finally:
    sock.close()
PY
}

check_compose_overrides_supported() {
  version=$(docker compose version --short 2>/dev/null | tr -d 'v\r')
  "$PYTHON" - "$version" <<'PY' || die "Docker Compose ${version:-unknown} is too old; the service-specific DEV configuration needs 2.24.4 or later for !override/!reset"
import sys
try:
    parts = tuple(int(p) for p in sys.argv[1].split("-")[0].split(".")[:3])
except ValueError:
    raise SystemExit(1)
raise SystemExit(0 if parts >= (2, 24, 4) else 1)
PY
}

validate_service_env() {
  case "$DEV_CONFIG_ROOT" in
    /*) ;;
    *) die "MYKHAYA_DEV_CONFIG_ROOT must be an absolute path" ;;
  esac
  "$PYTHON" infrastructure/scripts/service_env_contract.py \
    --root "$DEV_CONFIG_ROOT" --repo-root "$REPO_ROOT" ||
    die "DEV service configuration is invalid; nothing was built, stopped or restarted"
}

check_resolved_service_env() {
  # The merged model holds secret values; it goes straight into the checker,
  # which reports variable names and mount targets only.
  # It also proves provenance: each service receives exactly the overlay's
  # restated names plus its own files, so a root .env still being loaded fails.
  compose --profile tools config --format json |
    "$PYTHON" infrastructure/scripts/service_env_contract.py --check-resolved - \
      --config-root "$DEV_CONFIG_ROOT" --repo-root "$REPO_ROOT" ||
    die "merged DEV Compose model violates the service configuration contract"
}

read_state() {
  if [ -L "$STATE_FILE" ]; then
    die "cutover state $STATE_FILE must be a regular file, not a symbolic link"
  fi
  if [ ! -e "$STATE_FILE" ]; then
    printf 'legacy\n'
    return 0
  fi
  state=$(sed -n '1p' "$STATE_FILE" | tr -d '\r')
  case "$state" in
    legacy|pending|active|rollback-pending) printf '%s\n' "$state" ;;
    *) die "cutover state $STATE_FILE is unrecognised; refusing to deploy.\nInspect it, then restore the last known state (legacy, pending, active or rollback-pending)" ;;
  esac
}

write_state() {
  new_state=$1
  state_dir=$(dirname -- "$STATE_FILE")
  [ -d "$state_dir" ] || die "cutover state directory $state_dir does not exist"
  temporary="$state_dir/.service-env-state.tmp.$$"
  # Atomic replacement: an interruption leaves either the old or the new state.
  (
    umask 027
    printf '%s\nupdated=%s commit=%s by=%s\n' "$new_state" \
      "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(git rev-parse --short HEAD 2>/dev/null || echo unknown)" \
      "$(id -un 2>/dev/null || echo unknown)" >"$temporary"
  ) || die "could not write the cutover state"
  mv -f "$temporary" "$STATE_FILE" || { rm -f "$temporary"; die "could not record the cutover state"; }
  printf 'Cutover state: %s\n' "$new_state"
}

check_config_mode() {
  # Runs before any Docker interaction so a wrong mode fails immediately.
  current_state=$(read_state)
  printf 'Configuration mode: %s (cutover state: %s)\n' "$CONFIG_MODE" "$current_state"
  if [ "$CONFIG_MODE" = service-env ]; then
    [ "$LEGACY_ROLLBACK" != "1" ] ||
      die "MYKHAYA_DEV_CONFIG_ROOT and MYKHAYA_DEV_LEGACY_ENV_ROLLBACK=1 are both set; choose one"
    # Legacy runs find the state only at this path, so it must live in the root.
    [ "$(dirname -- "$STATE_FILE")" = "$DEV_CONFIG_ROOT" ] ||
      die "the cutover state file must be inside MYKHAYA_DEV_CONFIG_ROOT ($DEV_CONFIG_ROOT)"
    return 0
  fi
  case "$current_state" in
    legacy) return 0 ;;
    pending) reason="a service-env cutover was started but has not completed" ;;
    active) reason="the service-specific DEV configuration is active" ;;
    rollback-pending) reason="a rollback to the legacy configuration has not completed" ;;
  esac
  [ "$LEGACY_ROLLBACK" = "1" ] ||
    die "$reason ($STATE_FILE).\nTo continue with service-env: set MYKHAYA_DEV_CONFIG_ROOT=$(dirname -- "$STATE_FILE") and rerun.\nTo roll back deliberately: unset MYKHAYA_DEV_CONFIG_ROOT and rerun with MYKHAYA_DEV_LEGACY_ENV_ROLLBACK=1."
}

begin_transition() {
  # Called after every validation and before the first container recreation.
  current_state=$(read_state)
  if [ "$CONFIG_MODE" = service-env ]; then
    [ "$current_state" = active ] || write_state pending
  elif [ "$current_state" != legacy ]; then
    write_state rollback-pending
  fi
}

complete_transition() {
  # Called only after the deployment's health and readiness checks passed.
  current_state=$(read_state)
  if [ "$CONFIG_MODE" = service-env ]; then
    [ "$current_state" = active ] || write_state active
  elif [ "$current_state" = rollback-pending ]; then
    write_state legacy
  fi
}

validate_env() {
  if [ "$CONFIG_MODE" = service-env ]; then
    validate_service_env
    return 0
  fi
  check_config_mode >/dev/null
  [ -f .env ] || die "missing .env; run: cp .env.dev.example .env"

  required_variables="
MYKHAYA_SECRET_KEY
MYKHAYA_POSTGRES_ADMIN_PASSWORD
MYKHAYA_MIGRATION_DB_PASSWORD
MYKHAYA_DB_PASSWORD
MYKHAYA_REDIS_URL
MYKHAYA_ADMIN_ALLOWED_NETWORKS
MYKHAYA_ADMIN_MFA_REQUIRED
"
  missing=""
  for key in $required_variables; do
    value=$(env_value "$key")
    if [ -z "$value" ]; then
      missing="$missing $key"
    fi
  done
  [ -z "$missing" ] || die "missing required variables in .env:$missing"

  for key in MYKHAYA_SECRET_KEY MYKHAYA_POSTGRES_ADMIN_PASSWORD MYKHAYA_MIGRATION_DB_PASSWORD MYKHAYA_DB_PASSWORD; do
    value=$(env_value "$key")
    case "$value" in
      *CHANGE_ME*|*replace-with*|*changeme*|*example-secret*)
        die "$key still contains a documented placeholder"
        ;;
    esac
  done

  "$PYTHON" - .env <<'PY'
import json
import sys
from pathlib import Path

json_keys = {
    "MYKHAYA_CORS_ORIGINS",
    "MYKHAYA_TRUSTED_HOSTS",
    "MYKHAYA_TRUSTED_PROXY_CIDRS",
    "MYKHAYA_ADMIN_ALLOWED_NETWORKS",
}
values = {}
for number, raw in enumerate(Path(sys.argv[1]).read_text(encoding="utf-8-sig").splitlines(), 1):
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    values[key] = (value, number)

errors = []
for key in sorted(json_keys):
    if key not in values:
        continue
    value, number = values[key]
    try:
        parsed = json.loads(value)
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise ValueError("must be a JSON array of strings")
    except (json.JSONDecodeError, ValueError) as exc:
        errors.append(f"{key} on line {number}: {exc}")

if errors:
    raise SystemExit("ERROR: invalid JSON environment values:\n  " + "\n  ".join(errors))
PY
}

check_branch() {
  branch=$(git branch --show-current)
  if [ "$branch" != "dev" ]; then
    if [ "${MYKHAYA_DEV_ALLOW_NON_DEV_BRANCH:-0}" = "1" ]; then
      printf 'WARNING: deploying non-dev branch %s for an explicit rollback\n' "${branch:-detached HEAD}" >&2
    else
      die "wrong Git branch '${branch:-detached HEAD}'; persistent development deployments must use dev"
    fi
  fi
}

check_deployment_changes() {
  [ "${MYKHAYA_DEV_ALLOW_DEPLOYMENT_CHANGES:-0}" = "1" ] && return 0
  changes=$(git status --porcelain -- Makefile compose.yml compose.dev.yml .env.dev.example \
    compose.dev.service-env.yml '.env.dev.*.example' \
    infrastructure/caddy/Caddyfile.dev infrastructure/scripts 2>/dev/null || true)
  [ -z "$changes" ] || die "uncommitted tracked deployment changes detected:\n$changes"
}

check_update_tree() {
  dirty=$(git status --porcelain --untracked-files=all | awk '
    substr($0, 1, 3) == "?? " {
      path = substr($0, 4)
      if (path == ".env" || (path ~ /^\.env\./ && path !~ /\.example$/)) next
    }
    { print }
  ')
  [ -z "$dirty" ] || die "working tree is not clean (only untracked/ignored local .env secret files are allowed):\n$dirty"
}

report_new_env_variables() {
  # Service-env mode is validated against the exact per-service contract instead.
  [ "$CONFIG_MODE" = legacy ] || return 0
  missing=""
  for key in $(sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' .env.dev.example); do
    if ! grep -q "^${key}=" .env; then
      missing="$missing $key"
    fi
  done
  if [ -n "$missing" ]; then
    printf 'WARNING: .env does not contain these settings from .env.dev.example:%s\n' "$missing" >&2
    printf 'Defaults may apply. Review and add any site-specific values before the next update.\n' >&2
  fi
}

preflight() {
  say "Running development deployment preflight"
  check_config_mode
  command -v git >/dev/null 2>&1 || die "Git is unavailable"
  command -v docker >/dev/null 2>&1 || die "Docker is unavailable"
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is unavailable"
  docker info >/dev/null 2>&1 || die "the Docker daemon is unavailable or inaccessible"
  PYTHON=$(find_python) || die "Python 3 is unavailable (required for configuration validation)"
  export PYTHON
  check_branch
  check_deployment_changes
  [ "$CONFIG_MODE" = legacy ] || check_compose_overrides_supported
  validate_env

  bind_address=$(env_value MYKHAYA_DEV_BIND_ADDRESS)
  host_port=$(env_value MYKHAYA_DEV_HOST_PORT)
  mailpit_port=$(env_value MYKHAYA_DEV_MAILPIT_PORT)
  bind_address=${bind_address:-0.0.0.0}
  host_port=${host_port:-8089}
  mailpit_port=${mailpit_port:-8025}
  case "$host_port" in *[!0-9]*|'') die "development host port must be numeric" ;; esac
  case "$mailpit_port" in *[!0-9]*|'') die "Mailpit port must be numeric" ;; esac
  check_port application "$bind_address" "$host_port" caddy 8080
  check_port Mailpit 127.0.0.1 "$mailpit_port" mailpit 8025

  compose config --quiet || die "development Compose configuration is invalid"
  [ "$CONFIG_MODE" = legacy ] || check_resolved_service_env
  say "Preflight passed"
}

set_build_metadata() {
  MYKHAYA_VERSION=dev
  MYKHAYA_COMMIT_SHA=$(git rev-parse HEAD)
  MYKHAYA_BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  MYKHAYA_BUILD_CHANNEL=development
  export MYKHAYA_VERSION MYKHAYA_COMMIT_SHA MYKHAYA_BUILD_TIME MYKHAYA_BUILD_CHANNEL
}

wait_healthy() {
  service=$1
  attempts=${2:-45}
  count=0
  while [ "$count" -lt "$attempts" ]; do
    container_id=$(compose ps -q "$service" 2>/dev/null || true)
    if [ -n "$container_id" ]; then
      state=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null || true)
      case "$state" in
        healthy|running) return 0 ;;
        unhealthy|exited|dead) compose logs --tail=100 "$service" >&2 || true; die "$service became $state" ;;
      esac
    fi
    count=$((count + 1))
    sleep 2
  done
  compose logs --tail=100 "$service" >&2 || true
  die "$service did not become healthy in time"
}

probe_url() {
  url=$1
  if command -v curl >/dev/null 2>&1; then
    curl -fsS --max-time 5 -H 'Host: localhost' "$url" >/dev/null
  elif command -v wget >/dev/null 2>&1; then
    wget -q -T 5 -O /dev/null --header='Host: localhost' "$url"
  else
    die "curl or wget is required for health checks"
  fi
}

health_checks() {
  host_port=$(env_value MYKHAYA_DEV_HOST_PORT)
  host_port=${host_port:-8089}
  base_url="http://127.0.0.1:${host_port}/api/v1/health"
  say "Checking liveness and readiness"
  count=0
  while [ "$count" -lt 30 ]; do
    if probe_url "$base_url/live" && probe_url "$base_url/ready"; then
      printf 'Liveness: ready (%s/live)\n' "$base_url"
      printf 'Readiness: ready (%s/ready)\n' "$base_url"
      return 0
    fi
    count=$((count + 1))
    sleep 2
  done
  compose logs --tail=100 caddy web api >&2 || true
  die "liveness/readiness checks failed; the previous data volumes were not deleted"
}

check_network_drift() {
  if ! compose config --format json | "$PYTHON" infrastructure/scripts/check_dev_networks.py; then
    die "network drift detected; no application services were stopped. Run '$SCRIPT_DIR/dev-deploy.sh migrate-networks' during a planned application-tier maintenance window"
  fi
}

migrate_networks() {
  preflight
  # It recreates the application tier outside the normal deployment sequence,
  # so it must never run in the middle of a cutover or rollback.
  case "$CONFIG_MODE:$(read_state)" in
    service-env:active|legacy:legacy) ;;
    *) die "network migration is only allowed in a settled state (legacy, or service-env active); finish or roll back the cutover first" ;;
  esac
  if compose config --format json | "$PYTHON" infrastructure/scripts/check_dev_networks.py; then
    say "Development networks already match; no migration required"
    return 0
  fi

  say "Stopping only the application/proxy tier for declared network migration"
  compose stop caddy web api worker scheduler
  compose rm --force caddy web api worker scheduler
  docker network rm mykhaya_edge mykhaya_app
  compose up -d --no-build --no-deps api worker scheduler
  wait_healthy api
  compose up -d --no-build --no-deps web
  wait_healthy web
  compose up -d --no-build --no-deps caddy
  wait_healthy caddy
  check_network_drift
  say "Development network migration completed; data services and volumes were preserved"
}

deploy() {
  preflight
  check_network_drift
  report_new_env_variables
  set_build_metadata

  say "Building new images while the current stack remains running"
  compose build || die "image build failed; currently running containers were left in place"

  say "Validating merged backend runtime configuration"
  if ! "$PYTHON" infrastructure/scripts/validate_backend_config.py; then
    die "backend runtime configuration validation failed; currently running containers were left in place"
  fi

  # Everything that can be validated has been; containers are replaced from here.
  begin_transition

  say "Starting private data services"
  compose up -d --no-build postgres redis || die "private data services failed to start"
  wait_healthy postgres
  wait_healthy redis

  say "Running database migrations"
  if ! compose run --rm --no-deps migrate; then
    die "migrations failed; new app containers were not started. Existing containers remain, but inspect the migration and database state before retrying or rolling back."
  fi

  say "Starting updated application services"
  compose up -d --no-build --no-deps api worker scheduler || \
    die "API, worker, or scheduler failed to start"
  wait_healthy api
  compose up -d --no-build --no-deps web || die "web service failed to start"
  wait_healthy web
  # Caddy reads its bind-mounted configuration at process start. Recreate it
  # after an update so a changed CSP policy cannot remain stale in memory while
  # the web image has already been replaced.
  compose up -d --force-recreate --no-build --no-deps caddy mailpit || \
    die "Caddy or Mailpit failed to start"
  wait_healthy caddy

  compose ps
  health_checks
  complete_transition
  say "Development deployment succeeded"
  printf 'Product: https://dev.mykhaya.app\n'
  printf 'Control Centre: https://admin.dev.mykhaya.app\n'
  printf 'Status: https://status.dev.mykhaya.app\n'
}

update() {
  command -v git >/dev/null 2>&1 || die "Git is unavailable"
  check_branch
  check_update_tree
  preflight
  previous_commit=$(git rev-parse HEAD)
  say "Fetching origin/dev"
  git fetch origin dev || die "fetching origin/dev failed; no deployment was attempted"
  git merge --ff-only origin/dev || die "dev cannot be fast-forwarded; no deployment was attempted"
  current_commit=$(git rev-parse HEAD)
  exec "$REPO_ROOT/infrastructure/scripts/dev-deploy.sh" continue-update \
    "$previous_commit" "$current_commit"
}

continue_update() {
  previous_commit=$1
  current_commit=$2
  printf 'Updated source: %s -> %s\n' "$previous_commit" "$current_commit"
  printf 'Rollback reference for this update: %s\n' "$previous_commit"
  report_new_env_variables
  deploy
}

case "${1:-}" in
  preflight) preflight ;;
  up) deploy ;;
  update) update ;;
  continue-update)
    [ "$#" -eq 3 ] || die "internal update continuation requires old and new commits"
    continue_update "$2" "$3"
    ;;
  down)
    say "Stopping the development stack (persistent volumes are retained)"
    compose stop
    ;;
  logs) compose logs -f --tail=200 caddy web api worker scheduler postgres redis mailpit ;;
  health)
    [ -f "$ENV_SOURCE" ] || die "missing $ENV_SOURCE"
    health_checks
    ;;
  config-check)
    # Configuration only: no images, containers, ports or Git changes.
    [ "$CONFIG_MODE" = service-env ] || die "config-check validates the service-specific layout; set MYKHAYA_DEV_CONFIG_ROOT"
    PYTHON=$(find_python) || die "Python 3 is unavailable (required for configuration validation)"
    export PYTHON
    command -v docker >/dev/null 2>&1 || die "Docker is unavailable"
    check_compose_overrides_supported
    validate_service_env
    check_resolved_service_env
    say "DEV service configuration check passed"
    ;;
  migrate-networks) migrate_networks ;;
  state)
    printf 'Configuration mode: %s\nCutover state: %s\n' "$CONFIG_MODE" "$(read_state)"
    [ -f "$STATE_FILE" ] && sed -n '2p' "$STATE_FILE"
    true
    ;;
  state-init)
    # Records the pre-cutover state explicitly so DEV-host guards apply before
    # the first service-env deployment. Never overwrites an existing state.
    [ ! -e "$STATE_FILE" ] && [ ! -L "$STATE_FILE" ] || die "cutover state already exists: $(read_state)"
    write_state legacy
    ;;
  *) die "usage: $0 {preflight|config-check|up|update|down|logs|health|migrate-networks|state|state-init}" ;;
esac
