#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT"
[ "${MYKHAYA_PRODUCTION:-}" = 1 ] || { echo 'set MYKHAYA_PRODUCTION=1 explicitly' >&2; exit 1; }
die() { printf '%b\n' "ERROR: $*" >&2; exit 1; }
. "$ROOT/infrastructure/scripts/prod-config-mode.sh"
prod_select_mode readonly
prod_compose logs -f --tail=200 caddy web api worker scheduler postgres redis
