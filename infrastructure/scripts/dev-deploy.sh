#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT"

compose() {
  docker compose -f compose.yml -f compose.dev.yml "$@"
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
  sed -n "s/^${key}=//p" .env | tail -n 1 | tr -d '\r'
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

validate_env() {
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
  command -v git >/dev/null 2>&1 || die "Git is unavailable"
  command -v docker >/dev/null 2>&1 || die "Docker is unavailable"
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is unavailable"
  docker info >/dev/null 2>&1 || die "the Docker daemon is unavailable or inaccessible"
  PYTHON=$(find_python) || die "Python 3 is unavailable (required for configuration validation)"
  export PYTHON
  check_branch
  check_deployment_changes
  validate_env

  bind_address=$(env_value MYKHAYA_DEV_BIND_ADDRESS)
  host_port=$(env_value MYKHAYA_DEV_HOST_PORT)
  mailpit_port=$(env_value MYKHAYA_DEV_MAILPIT_PORT)
  bind_address=${bind_address:-0.0.0.0}
  host_port=${host_port:-8080}
  mailpit_port=${mailpit_port:-8025}
  case "$host_port" in *[!0-9]*|'') die "development host port must be numeric" ;; esac
  case "$mailpit_port" in *[!0-9]*|'') die "Mailpit port must be numeric" ;; esac
  check_port application "$bind_address" "$host_port" caddy 8080
  check_port Mailpit 127.0.0.1 "$mailpit_port" mailpit 8025

  compose config --quiet || die "development Compose configuration is invalid"
  say "Preflight passed"
}

set_build_metadata() {
  MYKHAYA_VERSION=$(tr -d '\r\n' < VERSION)
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
  host_port=${host_port:-8080}
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

deploy() {
  preflight
  report_new_env_variables
  set_build_metadata

  say "Building new images while the current stack remains running"
  compose build || die "image build failed; currently running containers were left in place"

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
    [ -f .env ] || die "missing .env"
    health_checks
    ;;
  *) die "usage: $0 {preflight|up|update|down|logs|health}" ;;
esac
