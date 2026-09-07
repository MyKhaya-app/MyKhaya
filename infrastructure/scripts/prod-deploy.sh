#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT"
COMPOSE="docker compose -f compose.yml -f compose.production.yml"

die() { printf '%s\n' "ERROR: $*" >&2; exit 1; }
production() { [ "${MYKHAYA_PRODUCTION:-}" = 1 ] || die "set MYKHAYA_PRODUCTION=1 explicitly"; }

validate() {
  production
  [ -f .env ] || die "missing production .env"
  branch=$(git branch --show-current)
  if [ "$branch" != "main" ]; then
    [ -n "${MYKHAYA_RELEASE_TAG:-}" ] || die "production must use main or set MYKHAYA_RELEASE_TAG for an approved detached tag"
    git describe --exact-match --tags HEAD 2>/dev/null | grep -Fx "$MYKHAYA_RELEASE_TAG" >/dev/null ||
      die "detached HEAD is not the approved release tag $MYKHAYA_RELEASE_TAG"
  fi
  git diff --quiet || die "tracked worktree changes are not allowed"
  git diff --cached --quiet || die "staged worktree changes are not allowed"
  python3 infrastructure/scripts/validate_backend_config.py
  $COMPOSE config --quiet
  caddy_cidrs=$(sed -n 's/^MYKHAYA_CADDY_TRUSTED_PROXY_CIDRS=//p' .env | tail -n 1 | tr -d '\r')
  [ -n "$caddy_cidrs" ] || die "MYKHAYA_CADDY_TRUSTED_PROXY_CIDRS is missing"
  docker run --rm -e "MYKHAYA_CADDY_TRUSTED_PROXY_CIDRS=$caddy_cidrs" \
    -v "$PWD/infrastructure/caddy/Caddyfile.production:/etc/caddy/Caddyfile:ro" \
    caddy:2.10.0-alpine caddy validate --config /etc/caddy/Caddyfile
}

update() {
  validate
  [ -n "${MYKHAYA_RELEASE_TAG:-}" ] || die "set MYKHAYA_RELEASE_TAG to an approved release tag"
  git describe --exact-match --tags HEAD 2>/dev/null | grep -Fx "$MYKHAYA_RELEASE_TAG" >/dev/null ||
    die "HEAD is not the approved release tag $MYKHAYA_RELEASE_TAG"
  [ -f "${MYKHAYA_BACKUP_MARKER:-/var/lib/mykhaya/last-backup.ok}" ] ||
    die "verified backup marker is missing"
  printf '%s\n' 'Current image digests:'
  $COMPOSE images --quiet caddy web api worker scheduler migrate postgres redis
  previous_revision=$($COMPOSE exec -T postgres psql -U postgres -d mykhaya -Atc 'select version_num from alembic_version' 2>/dev/null || true)
  printf 'Previous migration revision: %s\n' "${previous_revision:-unknown}"
  $COMPOSE run --rm --no-deps migrate
  $COMPOSE up -d --no-build caddy web api worker scheduler
  sh infrastructure/scripts/prod-health.sh
  printf 'Deployed release: %s\n' "$MYKHAYA_RELEASE_TAG"
  git rev-parse HEAD
  printf '%s\n' 'Deployed image digests:'
  $COMPOSE images --quiet caddy web api worker scheduler migrate postgres redis
}

case "${1:-}" in
  validate) validate ;;
  update) update ;;
  *) die "usage: $0 {validate|update}" ;;
esac
