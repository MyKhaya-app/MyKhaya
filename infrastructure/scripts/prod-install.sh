#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT"
die() { printf '%s\n' "ERROR: $*" >&2; exit 1; }
[ "${MYKHAYA_PRODUCTION:-}" = 1 ] || die "set MYKHAYA_PRODUCTION=1 explicitly on the production host"
[ "$(id -u)" -ne 0 ] || die "run as the dedicated deployment user, not root"
# A first installation uses the legacy root .env. Once a service-specific
# configuration exists (any cutover state), this host is installed: use
# make prod-update, which selects the active configuration.
state=${MYKHAYA_PROD_SERVICE_ENV_STATE:-/etc/mykhaya/prod/.service-env-state}
if [ -e "$state" ] || [ -L "$state" ]; then
  die "the PROD service-specific configuration state exists ($state); prod-install is for a new host only. Use make prod-update."
fi
[ -f .env ] || die "create the production .env before installation"
command -v docker >/dev/null 2>&1 || die "Docker is required"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"
docker info >/dev/null 2>&1 || die "Docker daemon is unavailable"
sh infrastructure/scripts/prod-deploy.sh validate
docker compose -f compose.yml -f compose.production.yml up -d postgres redis
docker compose -f compose.yml -f compose.production.yml run --rm --no-deps migrate
docker compose -f compose.yml -f compose.production.yml up -d caddy web api worker scheduler
sh infrastructure/scripts/prod-health.sh
printf '%s\n' 'Production installation completed. Configure PCC bootstrap, backups, Cloudflare, and NetBird separately.'
