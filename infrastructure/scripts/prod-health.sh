#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT"
COMPOSE="docker compose -f compose.yml -f compose.production.yml"
[ "${MYKHAYA_PRODUCTION:-}" = 1 ] || { echo 'set MYKHAYA_PRODUCTION=1 explicitly' >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo 'curl is required' >&2; exit 1; }
$COMPOSE ps
for service in postgres redis api web worker scheduler; do
  $COMPOSE ps --status running -q "$service" >/dev/null || exit 1
done
curl -fsS --max-time 10 --resolve mykhaya.app:443:127.0.0.1 https://mykhaya.app/api/v1/health/live -k >/dev/null
curl -fsS --max-time 10 --resolve mykhaya.app:443:127.0.0.1 https://mykhaya.app/api/v1/health/ready -k >/dev/null
curl -fsS --max-time 10 --resolve mykhaya.app:443:127.0.0.1 https://mykhaya.app/api/v1/health/build -k
printf '\nProduction health checks passed.\n'
