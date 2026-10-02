#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT"
[ "${MYKHAYA_PRODUCTION:-}" = 1 ] || { echo 'set MYKHAYA_PRODUCTION=1 explicitly' >&2; exit 1; }
docker compose -f compose.yml -f compose.production.yml logs -f --tail=200 caddy web api worker scheduler postgres redis
