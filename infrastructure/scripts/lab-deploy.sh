#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT"

PROJECT=mykhaya-lab
ENV_FILE=.env.lab
compose() { docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" -f compose.yml -f compose.lab.yml "$@"; }
say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %b\n' "$*" >&2; exit 1; }
env_value() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1 | tr -d '\r'; }

require_lab() {
  [ "$(git branch --show-current)" = feature/multi-node-platform ] || die "Lab must run from feature/multi-node-platform"
  [ -f "$ENV_FILE" ] || die "missing .env.lab; copy .env.lab.example and fill Lab-only values"
  [ "$(env_value MYKHAYA_ENVIRONMENT)" = lab ] || die "MYKHAYA_ENVIRONMENT must be lab"
  [ "$(env_value MYKHAYA_NODE_ID)" = mk-lab-01 ] || die "MYKHAYA_NODE_ID must be mk-lab-01"
  [ "$(env_value MYKHAYA_REGION)" = uk ] || die "MYKHAYA_REGION must be uk"
  [ "$(env_value MYKHAYA_COOKIE_DOMAIN)" = "" ] || die "Lab cookies must remain host-only"
  [ "$(env_value MYKHAYA_COOKIE_SECURE)" = true ] || die "Lab cookies must be Secure"
  [ "$(env_value MYKHAYA_ADMIN_MFA_REQUIRED)" = true ] || die "Lab admin MFA must remain enabled"
  [ "$(env_value MYKHAYA_PUBLIC_WEB_URL)" = https://lab.mykhaya.app ] || die "Lab public URL is incorrect"
  [ "$(env_value MYKHAYA_ADMIN_URL)" = https://admin.lab.mykhaya.app ] || die "Lab admin URL is incorrect"
  [ "$(env_value MYKHAYA_STATUS_URL)" = https://status.lab.mykhaya.app ] || die "Lab status URL is incorrect"
  [ "$(env_value MYKHAYA_NATIVE_API_URL)" = https://api.lab.mykhaya.app ] || die "Lab API URL is incorrect"
  case "$(env_value MYKHAYA_REDIS_URL)" in redis://redis:6379/*) ;; *) die "Lab Redis URL must target the Lab redis service" ;; esac
  case "$(env_value MYKHAYA_STRIPE_SECRET_KEY)" in sk_test_*) ;; *) die "Lab requires a Stripe test-mode secret key" ;; esac
  case "$(env_value MYKHAYA_STRIPE_PUBLISHABLE_KEY)" in pk_test_*) ;; *) die "Lab requires a Stripe test-mode publishable key" ;; esac
  case "$(env_value MYKHAYA_STRIPE_WEBHOOK_SECRET)" in whsec_*) ;; *) die "Lab requires a Stripe test-mode webhook secret" ;; esac
  for key in MYKHAYA_STRIPE_SECRET_KEY MYKHAYA_STRIPE_PUBLISHABLE_KEY MYKHAYA_STRIPE_WEBHOOK_SECRET MYKHAYA_STRIPE_FAMILY_MONTHLY_PRICE_ID MYKHAYA_STRIPE_FAMILY_ANNUAL_PRICE_ID; do
    case "$(env_value "$key")" in *CHANGE_ME*|*change_me*|*replace-with*) die "$key is still a placeholder" ;; esac
  done
  for key in MYKHAYA_SECRET_KEY MYKHAYA_POSTGRES_ADMIN_PASSWORD MYKHAYA_MIGRATION_DB_PASSWORD MYKHAYA_DB_PASSWORD MYKHAYA_LAB_FIXTURE_PASSWORD; do
    value=$(env_value "$key")
    [ -n "$value" ] || die "$key is required"
    case "$value" in *CHANGE_ME*|*change_me*|*replace-with*|*example-secret*) die "$key is still a placeholder" ;; esac
  done
  if grep -Eiq 'dev\.mykhaya\.app|(^|[/:])mykhaya\.app([/:]|$)' "$ENV_FILE"; then die ".env.lab contains a development or production hostname"; fi
  if grep -Eiq 'redis://(dev|production|prod)|postgresql[^ ]*@(dev|production|prod)' "$ENV_FILE"; then die ".env.lab contains a protected-environment endpoint"; fi
  if [ -f .env ]; then
    for key in MYKHAYA_SECRET_KEY MYKHAYA_POSTGRES_ADMIN_PASSWORD MYKHAYA_MIGRATION_DB_PASSWORD MYKHAYA_DB_PASSWORD; do
      [ "$(env_value "$key")" != "$(sed -n "s/^$key=//p" .env | tail -n 1 | tr -d '\r')" ] || die "$key is shared with .env"
    done
  fi
}

preflight() {
  require_lab
  command -v docker >/dev/null 2>&1 || die "Docker is unavailable"
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is unavailable"
  merged=$(compose config) || die "Lab Compose configuration is invalid"
  case "$merged" in *mykhaya_lab*) ;; *) die "merged Compose config does not target mykhaya_lab" ;; esac
  case "$merged" in *"mykhaya:"*) die "merged Compose config contains a non-Lab database target" ;; esac
  case "$merged" in *dev.mykhaya.app*|*mykhaya.com*) die "merged Compose config contains a protected hostname" ;; esac
  say "Lab preflight passed for project $PROJECT"
}

health() {
  require_lab
  port=$(env_value MYKHAYA_LAB_HTTPS_PORT); port=${port:-8444}
  curl -kfsS --max-time 8 --resolve "lab.mykhaya.app:$port:127.0.0.1" "https://lab.mykhaya.app:$port/api/v1/health/live" >/dev/null || die "Lab liveness check failed"
  curl -kfsS --max-time 8 --resolve "lab.mykhaya.app:$port:127.0.0.1" "https://lab.mykhaya.app:$port/api/v1/health/ready" >/dev/null || die "Lab readiness check failed"
  say "Lab health checks passed"
}

deploy() {
  preflight
  compose build
  compose up -d --wait postgres redis
  compose run --rm --no-deps migrate
  compose up -d api worker scheduler web caddy mailpit
  health
  compose ps
}

reset() {
  require_lab
  printf 'This destroys ALL data in the isolated %s Lab, including its database and Redis state. Type RESET LAB to continue: ' "$PROJECT"
  read answer
  [ "$answer" = 'RESET LAB' ] || die "Lab reset cancelled"
  compose down --volumes --remove-orphans
  deploy
}

case "${1:-}" in
  preflight) preflight ;;
  up|update|rebuild) deploy ;;
  health) health ;;
  logs) require_lab; compose logs -f --tail=200 caddy web api worker scheduler postgres redis mailpit ;;
  down) require_lab; compose stop ;;
  reset) reset ;;
  *) die "usage: $0 {preflight|up|update|rebuild|health|logs|down|reset}" ;;
esac
