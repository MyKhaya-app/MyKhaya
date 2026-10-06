#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT"
COMPOSE="docker compose -f compose.yml -f compose.production.yml"
[ "${MYKHAYA_PRODUCTION:-}" = 1 ] || { echo 'set MYKHAYA_PRODUCTION=1 explicitly' >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo 'curl is required' >&2; exit 1; }
WEB_DOMAIN=${WEB_DOMAIN:-$(sed -n 's/^WEB_DOMAIN=//p' .env 2>/dev/null | tail -n 1 | tr -d '\r')}
WEB_DOMAIN=${WEB_DOMAIN:-mykhaya.app}
$COMPOSE ps
for service in postgres redis api web worker scheduler; do
  $COMPOSE ps --status running -q "$service" >/dev/null || exit 1
done
curl -fsS --max-time 10 -H "Host: $WEB_DOMAIN" http://127.0.0.1/api/v1/health/live >/dev/null
curl -fsS --max-time 10 -H "Host: $WEB_DOMAIN" http://127.0.0.1/api/v1/health/ready >/dev/null
curl -fsS --max-time 10 -H "Host: $WEB_DOMAIN" http://127.0.0.1/api/v1/health/build
printf '\nProduction health checks passed.\n'
