#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT"

die() { printf '%b\n' "ERROR: $*" >&2; exit 1; }
production() { [ "${MYKHAYA_PRODUCTION:-}" = 1 ] || die "set MYKHAYA_PRODUCTION=1 explicitly"; }

# Configuration mode (F-03): selected from the cutover state in
# /etc/mykhaya/prod/.service-env-state. Legacy (no state) is the historical
# root .env deployment, unchanged. See prod-config-mode.sh.
. "$ROOT/infrastructure/scripts/prod-config-mode.sh"

env_value() {
  key=$1
  sed -n "s/^${key}=//p" .env | tail -n 1 | tr -d '\r'
}

require_installation_config() {
  missing=""
  for key in \
    MYKHAYA_REGISTRATION_MODE \
    MYKHAYA_PUBLIC_WEB_URL MYKHAYA_ADMIN_URL MYKHAYA_STATUS_URL MYKHAYA_NATIVE_API_URL \
    MYKHAYA_CORS_ORIGINS MYKHAYA_TRUSTED_HOSTS MYKHAYA_TRUSTED_PROXY_CIDRS \
    WEB_DOMAIN API_DOMAIN ADMIN_DOMAIN STATUS_DOMAIN \
    MYKHAYA_CADDY_TRUSTED_PROXY_CIDRS; do
    [ -n "$(env_value "$key")" ] || missing="$missing $key"
  done
  [ -z "$missing" ] || die "production .env is missing required installation values:$missing"
}

backup_preflight() {
  # Encrypted backups are a hard production requirement: verify the tooling
  # before anything is fetched, built, migrated or restarted.
  sh infrastructure/scripts/backup-preflight.sh || die "backup preflight failed; nothing was changed"
}

check_compose_overrides_supported() {
  version=$(docker compose version --short 2>/dev/null | tr -d 'v\r')
  python3 - "$version" <<'PY' || die "Docker Compose ${version:-unknown} is too old; the service-specific PROD configuration needs 2.24.4 or later for !override"
import sys
try:
    parts = tuple(int(p) for p in sys.argv[1].split("-")[0].split(".")[:3])
except ValueError:
    raise SystemExit(1)
raise SystemExit(0 if parts >= (2, 24, 4) else 1)
PY
}

api_image() {
  # Prints only the API image name; the merged model holds secret values and
  # never leaves this pipe.
  prod_compose config --format json 2>/dev/null |
    python3 -c 'import json, sys
model = json.load(sys.stdin)
api = model["services"]["api"]
print(api.get("image") or model["name"] + "-api")' 2>/dev/null
}

validate_service_env() {
  # The PROD contract (names, permissions, separation, protected key
  # directories through the locked-down probe) and the merged model's
  # allow-list and provenance. Values never leave the validators.
  check_compose_overrides_supported
  probe_image=$(api_image) || probe_image=
  set -- --profile prod --root "$PROD_CONFIG_ROOT" --repo-root "$ROOT"
  [ -z "$probe_image" ] || set -- "$@" --probe-image "$probe_image"
  python3 infrastructure/scripts/service_env_contract.py "$@" ||
    die "PROD service configuration is invalid; nothing was built, stopped or restarted"
  prod_compose --profile tools config --format json |
    python3 infrastructure/scripts/service_env_contract.py --profile prod --check-resolved - \
      --config-root "$PROD_CONFIG_ROOT" --repo-root "$ROOT" ||
    die "merged PROD Compose model violates the service configuration contract"
}

validate() {
  production
  prod_select_mode deploy
  printf 'Configuration mode: %s (cutover state: %s)\n' "$PROD_CONFIG_MODE" "$PROD_STATE"
  if [ "$PROD_CONFIG_MODE" = legacy ]; then
    [ -f .env ] || die "missing production .env"
    require_installation_config
  fi
  backup_preflight
  branch=$(git branch --show-current)
  if [ "$branch" != "main" ]; then
    [ -n "${MYKHAYA_RELEASE_TAG:-}" ] || die "production must use main or set MYKHAYA_RELEASE_TAG for an approved detached tag"
    git describe --exact-match --tags HEAD 2>/dev/null | grep -Fx "$MYKHAYA_RELEASE_TAG" >/dev/null ||
      die "detached HEAD is not the approved release tag $MYKHAYA_RELEASE_TAG"
  fi
  git diff --quiet || die "tracked worktree changes are not allowed"
  git diff --cached --quiet || die "staged worktree changes are not allowed"
  [ "$PROD_CONFIG_MODE" = legacy ] || validate_service_env
  python3 infrastructure/scripts/validate_backend_config.py
  prod_compose config --quiet
  caddy_cidrs=$(prod_env_value MYKHAYA_CADDY_TRUSTED_PROXY_CIDRS)
  [ -n "$caddy_cidrs" ] || die "MYKHAYA_CADDY_TRUSTED_PROXY_CIDRS is missing"
  docker run --rm -e "MYKHAYA_CADDY_TRUSTED_PROXY_CIDRS=$caddy_cidrs" \
    -v "$PWD/infrastructure/caddy/Caddyfile.production:/etc/caddy/Caddyfile:ro" \
    caddy:2.10.0-alpine caddy validate --config /etc/caddy/Caddyfile
}

verify_tag_checkout() {
  # The checked-out tree must be exactly the approved tag on origin/main.
  git check-ref-format "refs/tags/$MYKHAYA_RELEASE_TAG" >/dev/null 2>&1 ||
    die "invalid release tag $MYKHAYA_RELEASE_TAG"
  git rev-parse --verify "refs/tags/$MYKHAYA_RELEASE_TAG^{commit}" >/dev/null 2>&1 ||
    die "release tag does not exist: $MYKHAYA_RELEASE_TAG"
  tag_commit=$(git rev-parse "refs/tags/$MYKHAYA_RELEASE_TAG^{commit}")
  git merge-base --is-ancestor "$tag_commit" origin/main ||
    die "release tag $MYKHAYA_RELEASE_TAG is not contained in origin/main"
  head_commit=$(git rev-parse HEAD)
  [ "$head_commit" = "$tag_commit" ] || die "HEAD does not match release tag $MYKHAYA_RELEASE_TAG"
  git describe --exact-match --tags HEAD 2>/dev/null | grep -Fx "$MYKHAYA_RELEASE_TAG" >/dev/null ||
    die "HEAD is not exactly the requested release tag $MYKHAYA_RELEASE_TAG"
}

reuse_release_images() {
  # Configuration-only deployments (the F-03 cutover and its rollback) reuse
  # the images already built for this exact tag instead of rebuilding: a
  # rebuild refreshes OS packages and unpinned Python dependencies, which
  # would be an unrelated application change. Every application image must
  # carry this tag's version and commit, and share one build time, which is
  # exported unchanged so runtime metadata stays identical.
  images=$(prod_compose config --format json | python3 -c 'import json, sys
model = json.load(sys.stdin)
for service in ("api", "worker", "scheduler", "migrate", "web"):
    definition = model["services"][service]
    print(definition.get("image") or model["name"] + "-" + service)') ||
    die "the application images could not be resolved"
  build_time=
  for image in $images; do
    labels=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.version"}} {{index .Config.Labels "org.opencontainers.image.revision"}} {{index .Config.Labels "org.opencontainers.image.created"}}' "$image" 2>/dev/null) ||
      die "image $image is not present; deploy the release normally first (images are never rebuilt or pulled for a configuration-only deployment)"
    set -- $labels
    [ "${1:-}" = "$MYKHAYA_RELEASE_TAG" ] && [ "${2:-}" = "$head_commit" ] ||
      die "image $image was not built from $MYKHAYA_RELEASE_TAG ($head_commit); deploy the release normally first"
    [ -n "${3:-}" ] || die "image $image has no build time label"
    [ -z "$build_time" ] || [ "$build_time" = "$3" ] ||
      die "the application images come from different builds; deploy the release normally first"
    build_time=$3
  done
  MYKHAYA_BUILD_TIME=$build_time
  export MYKHAYA_BUILD_TIME
  printf 'Reusing the images built for %s at %s (configuration-only deployment).\n' \
    "$MYKHAYA_RELEASE_TAG" "$MYKHAYA_BUILD_TIME"
}

begin_transition() {
  # Called after every validation and before the first container changes.
  if [ "$PROD_CONFIG_MODE" = service-env ]; then
    [ "$PROD_STATE" = active ] || cutover_write_state "$PROD_STATE_FILE" pending
  elif [ "$PROD_STATE" != legacy ]; then
    cutover_write_state "$PROD_STATE_FILE" rollback-pending
  fi
}

complete_transition() {
  # Called only after the health checks passed. A cutover becomes active only
  # once prod-service-env-migrate.sh has verified the running services.
  current=$(cutover_read_state "$PROD_STATE_FILE")
  if [ "$PROD_CONFIG_MODE" = service-env ]; then
    [ "$current" = active ] ||
      printf '%s\n' 'Cutover state remains pending until prod-service-env-migrate.sh verifies the running services.'
  elif [ "$current" = rollback-pending ]; then
    cutover_write_state "$PROD_STATE_FILE" legacy
  fi
}

update() {
  production
  [ -n "${MYKHAYA_RELEASE_TAG:-}" ] || die "set MYKHAYA_RELEASE_TAG to an approved release tag"
  # Refuse an unfinished cutover or rollback before anything is fetched.
  prod_select_mode deploy
  backup_preflight
  git status --porcelain --untracked-files=all | grep . >/dev/null && die "worktree is not clean"
  git check-ref-format "refs/tags/$MYKHAYA_RELEASE_TAG" >/dev/null 2>&1 ||
    die "invalid release tag $MYKHAYA_RELEASE_TAG"
  git fetch origin main "refs/tags/$MYKHAYA_RELEASE_TAG:refs/tags/$MYKHAYA_RELEASE_TAG"
  git rev-parse --verify "refs/tags/$MYKHAYA_RELEASE_TAG^{commit}" >/dev/null 2>&1 ||
    die "release tag does not exist: $MYKHAYA_RELEASE_TAG"
  tag_commit=$(git rev-parse "refs/tags/$MYKHAYA_RELEASE_TAG^{commit}")
  git merge-base --is-ancestor "$tag_commit" origin/main ||
    die "release tag $MYKHAYA_RELEASE_TAG is not contained in origin/main"
  git checkout --detach "refs/tags/$MYKHAYA_RELEASE_TAG"
  # Continue in the release's own copy of this script: the shell reads a
  # script as it runs, so the checkout must never change the remaining steps
  # underneath it.
  exec sh "$ROOT/infrastructure/scripts/prod-deploy.sh" continue-update
}

continue_update() {
  production
  [ -n "${MYKHAYA_RELEASE_TAG:-}" ] || die "set MYKHAYA_RELEASE_TAG to an approved release tag"
  git status --porcelain --untracked-files=all | grep . >/dev/null && die "worktree is not clean"
  verify_tag_checkout
  prod_select_mode deploy
  MYKHAYA_VERSION="$MYKHAYA_RELEASE_TAG"
  export MYKHAYA_VERSION MYKHAYA_COMMIT_SHA="$head_commit" MYKHAYA_BUILD_CHANNEL=stable
  if [ "${MYKHAYA_PROD_REUSE_IMAGES:-0}" = 1 ]; then
    reuse_release_images
  else
    MYKHAYA_BUILD_TIME="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    export MYKHAYA_BUILD_TIME
  fi
  python3 infrastructure/scripts/validate_version.py "$MYKHAYA_RELEASE_TAG"
  validate
  [ -f "${MYKHAYA_BACKUP_MARKER:-/var/lib/mykhaya/last-backup.ok}" ] ||
    die "verified backup marker is missing"
  printf '%s\n' 'Current image digests:'
  prod_compose images --quiet caddy web api worker scheduler migrate postgres redis
  previous_revision=$(prod_compose exec -T postgres psql -U postgres -d mykhaya -Atc 'select version_num from alembic_version' 2>/dev/null || true)
  printf 'Previous migration revision: %s\n' "${previous_revision:-unknown}"
  [ "${MYKHAYA_PROD_REUSE_IMAGES:-0}" = 1 ] || prod_compose build web api worker scheduler migrate
  begin_transition
  prod_compose run --rm --no-deps migrate ||
    die "migrations failed; application containers were not replaced. Inspect the migration and database state before retrying; never downgrade.\nCutover state: $(cutover_read_state "$PROD_STATE_FILE")"
  prod_compose up -d --no-build caddy web api worker scheduler ||
    die "application services failed to start.\nCutover state: $(cutover_read_state "$PROD_STATE_FILE")"
  sh infrastructure/scripts/prod-health.sh ||
    die "health checks failed; nothing was rolled back.\nCutover state: $(cutover_read_state "$PROD_STATE_FILE")"
  complete_transition
  printf 'Deployed release: %s\n' "$MYKHAYA_RELEASE_TAG"
  printf 'Deployed commit: %s\n' "$MYKHAYA_COMMIT_SHA"
  printf 'Configuration mode: %s\n' "$PROD_CONFIG_MODE"
  printf '%s\n' 'Deployed image digests:'
  prod_compose images --quiet caddy web api worker scheduler migrate postgres redis
}

case "${1:-}" in
  validate) validate ;;
  update) update ;;
  continue-update) continue_update ;;
  state)
    production
    prod_select_mode readonly
    printf 'Configuration mode: %s\nCutover state: %s\n' "$PROD_CONFIG_MODE" "$PROD_STATE"
    [ -f "$PROD_STATE_FILE" ] && sed -n '2p' "$PROD_STATE_FILE"
    true
    ;;
  *) die "usage: $0 {validate|update|state}" ;;
esac
