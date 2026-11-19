#!/bin/sh
# Refuses local-workstation Compose targets on the persistent DEV host.
#
# `make up`, `init`, `down`, `backend-rebuild`, `migrate` and `reset` run bare
# `docker compose` with compose.yml and the repository root .env, without
# compose.dev.yml or the DEV service-specific configuration; `reset` also runs
# `docker compose down -v`, which deletes persistent volumes. On the DEV host
# they would bypass infrastructure/scripts/dev-deploy.sh, its cutover state and
# its volume protection.
#
# The DEV host is identified by its cutover state file (created by
# `dev-deploy.sh state-init` or the first service-env deployment). It never
# exists on a workstation, so local development is unaffected.
set -eu

target=${1:-this target}
state=${MYKHAYA_DEV_SERVICE_ENV_STATE:-/etc/mykhaya/dev/.service-env-state}

if [ -e "$state" ] || [ -L "$state" ]; then
  printf 'ERROR: make %s is a local-workstation command and is refused on the DEV host (%s exists).\n' \
    "$target" "$state" >&2
  printf 'Use the DEV deployment commands instead: make dev-up, dev-update, dev-down, dev-logs, dev-health.\n' >&2
  exit 1
fi
