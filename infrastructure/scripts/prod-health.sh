#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT"
[ "${MYKHAYA_PRODUCTION:-}" = 1 ] || { echo 'set MYKHAYA_PRODUCTION=1 explicitly' >&2; exit 1; }
die() { printf '%b\n' "ERROR: $*" >&2; exit 1; }
# Read-only: works in every cutover state so an interrupted migration can be
# diagnosed (prod-config-mode.sh).
. "$ROOT/infrastructure/scripts/prod-config-mode.sh"
prod_select_mode readonly
command -v curl >/dev/null 2>&1 || { echo 'curl is required' >&2; exit 1; }
WEB_DOMAIN=${WEB_DOMAIN:-$(sed -n 's/^WEB_DOMAIN=//p' "$PROD_ENV_SOURCE" 2>/dev/null | tail -n 1 | tr -d '\r')}
WEB_DOMAIN=${WEB_DOMAIN:-mykhaya.app}
prod_compose ps
for service in postgres redis api web worker scheduler; do
  prod_compose ps --status running -q "$service" >/dev/null || exit 1
done
curl -fsS --max-time 10 -H "Host: $WEB_DOMAIN" http://127.0.0.1/api/v1/health/live >/dev/null
curl -fsS --max-time 10 -H "Host: $WEB_DOMAIN" http://127.0.0.1/api/v1/health/ready >/dev/null
build_status=$(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' \
  -H "Host: $WEB_DOMAIN" http://127.0.0.1/api/v1/health/build)
[ "$build_status" = 401 ] || {
  printf 'Expected authenticated /health/build to return 401, got %s\n' "$build_status" >&2
  exit 1
}
printf '\nProduction health checks passed (configuration mode: %s).\n' "$PROD_CONFIG_MODE"
