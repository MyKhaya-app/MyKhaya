#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT"
[ "$(git branch --show-current)" = feature/multi-node-platform ] || { echo 'ERROR: Lab seed requires feature/multi-node-platform' >&2; exit 1; }
[ -f .env.lab ] || { echo 'ERROR: missing .env.lab' >&2; exit 1; }
[ "$(sed -n 's/^MYKHAYA_ENVIRONMENT=//p' .env.lab | tail -n 1 | tr -d '\r')" = lab ] || { echo 'ERROR: Lab seed refuses non-Lab environment' >&2; exit 1; }
docker compose --project-name mykhaya-lab --env-file .env.lab -f compose.yml -f compose.lab.yml run --rm --no-deps api python -m mykhaya.lab_seed
