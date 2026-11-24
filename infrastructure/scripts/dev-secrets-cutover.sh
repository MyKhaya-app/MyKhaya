#!/bin/sh
# DEV Docker Secrets cutover (MK-SEC-001 v1.2). Run by the Owner, on the DEV
# host, from the deployment checkout, as the deployment account (never root;
# single steps use sudo). See docs/operations/dev-docker-secrets-migration.md.
#
#   status     what state DEV is in (read-only)
#   check      every prerequisite (starts only the isolated, read-only probe
#              containers that config-check uses)
#   provision  create file-backed/ from the F-03 files (sudo; changes no service)
#   verify     prove the provisioned files equal the F-03 values (sudo)
#   cutover    check, verify, record a baseline, ask for approval, deploy, accept
#   accept     compare with the baseline and scan for exposed secrets (sudo)
#   rollback   ask for approval, return to the F-03 configuration, compare
#
# Nothing here generates, rotates, prints or hashes a credential, or removes a
# volume. cutover needs MYKHAYA_DEV_ATTEST="backup-restored keys-escrowed": the
# Owner's statement that a DEV backup has been restored successfully and that
# MYKHAYA_SECRET_KEY, the field keyrings and the backup identity are escrowed.
set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT"
ROOT=${MYKHAYA_DEV_CONFIG_ROOT:-/etc/mykhaya/dev}
ROOT=${ROOT%/}
STATE_FILE=${MYKHAYA_DEV_SERVICE_ENV_STATE:-$ROOT/.service-env-state}
BASELINE=$ROOT/.secrets-baseline
DATA_VOLUMES="postgres:mykhaya_postgres_data redis:mykhaya_redis_data api:mykhaya_dev_home_migration_data"
CUTOVER_PHRASE="MIGRATE DEV"
ROLLBACK_PHRASE="ROLL BACK DEV"
BACKUP_MAX_AGE_MINUTES=1440

say() { printf '\n==> %s\n' "$*"; }
ok() { printf 'ok    %s\n' "$*"; }
die() { printf '\nERROR: %b\n' "$*" >&2; exit 1; }
. "$SCRIPT_DIR/cutover-state.sh"

deploy_script() { # leading VAR=value words, then the action
  env MYKHAYA_DEV_CONFIG_ROOT="$ROOT" MYKHAYA_DEV_SERVICE_ENV_STATE="$STATE_FILE" "$@"
}
DEPLOY="$SCRIPT_DIR/dev-deploy.sh"

container() { # service: exactly one running DEV container
  found=$(docker ps -q --no-trunc --filter label=com.docker.compose.project=mykhaya \
    --filter "label=com.docker.compose.service=$1" \
    --filter label=com.docker.compose.oneoff=False --filter status=running) || die "Docker is unavailable"
  [ "$(printf '%s' "$found" | grep -c .)" = 1 ] || die "expected exactly one running $1 container"
  printf '%s\n' "$found"
}

env_class() { # container, name: absent, blank or set (the value never leaves Docker)
  docker inspect --format "{{\$s := \"absent\"}}{{range .Config.Env}}{{if eq (index (split . \"=\") 0) \"$2\"}}{{if eq . \"$2=\"}}{{\$s = \"blank\"}}{{else}}{{\$s = \"set\"}}{{end}}{{end}}{{end}}{{\$s}}" "$1"
}

env_is() { # container, NAME=value for a non-secret value
  [ "$(docker inspect --format "{{range .Config.Env}}{{if eq . \"$2\"}}yes{{end}}{{end}}" "$1")" = yes ]
}

overlay_is() { # container, file names in order
  actual=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$1" |
    tr ',' '\n' | sed 's#.*/##' | tr '\n' ' ')
  [ "$actual" = "$2 " ]
}

check_host() {
  [ "$(id -u)" != 0 ] || die "run as the deployment account, not root"
  for name in COMPOSE_PROJECT_NAME COMPOSE_FILE COMPOSE_ENV_FILES DOCKER_HOST DOCKER_CONTEXT \
    MYKHAYA_DEV_LEGACY_ENV_ROLLBACK MYKHAYA_PRODUCTION; do
    eval "value=\${$name-}"
    [ -z "$value" ] || die "$name is set; unset it first"
  done
  case "$ROOT" in
    /*) ;;
    *) die "MYKHAYA_DEV_CONFIG_ROOT must be an absolute path" ;;
  esac
  case "$ROOT/" in
    */prod/* | */production/*) die "the configuration root is a production path" ;;
  esac
  [ "$(dirname -- "$STATE_FILE")" = "$ROOT" ] || die "the cutover state must be inside the configuration root"
  [ ! -L "$ROOT" ] || die "the configuration root must not be a symbolic link"
}

f03_state() { cutover_read_state "$STATE_FILE"; }
secrets_state() { cutover_read_state "$ROOT/.secrets-state"; }

status() {
  f03=$(f03_state) || exit 1
  secrets=$(secrets_state) || exit 1
  printf 'F-03 state: %s\n' "$f03"
  printf 'Docker Secrets state: %s\n' "$([ "$secrets" = legacy ] && echo not-started || echo "$secrets")"
  if [ -d "$ROOT/file-backed" ]; then echo "file-backed root: present"; else echo "file-backed root: absent"; fi
  case "$f03:$secrets" in
    legacy:legacy) echo "Next: complete the F-03 cutover first (docs/operations/dev-service-config-migration.md)." ;;
    active:legacy) echo "Next: check, then provision, verify and cutover." ;;
    active:pending) echo "Next: fix the cause and rerun cutover, or rollback." ;;
    active:active) echo "Next: accept." ;;
    active:rollback-pending) echo "Next: rerun rollback." ;;
    *) echo "Unsafe combination: resolve the F-03 state first." ;;
  esac
}

# The state this run starts from decides which containers are expected.
# PostgreSQL is not judged by its label: Compose versions differ on whether an
# unchanged environment supplied by another env_file recreates a container.
check_running() { # expected overlay list
  container postgres >/dev/null
  for service in api worker scheduler; do
    overlay_is "$(container "$service")" "$1" ||
      die "$service does not run the expected configuration; deploy the current state first"
  done
  head=$(git rev-parse HEAD)
  env_is "$(container api)" "MYKHAYA_COMMIT_SHA=$head" ||
    die "the running api is not this commit. Deploy it with the current configuration first, so the code change and the secrets change stay separate"
  ok "running containers use the expected configuration and this commit"
}

check_volumes() {
  for pair in $DATA_VOLUMES; do
    service=${pair%%:*} volume=${pair#*:}
    docker volume inspect "$volume" >/dev/null 2>&1 || die "the volume for $service does not exist"
    [ "$(docker inspect --format "{{range .Mounts}}{{if eq .Name \"$volume\"}}yes{{end}}{{end}}" "$(container "$service")")" = yes ] ||
      die "$service does not use its expected persistent volume"
  done
  ok "persistent volumes exist and are in use"
}

setting() { sed -n "s/^$1=//p" "$ROOT/compose.env" | tail -n 1 | tr -d '\r'; }

check_backup() {
  directory=${MYKHAYA_BACKUP_DIR:-$(setting MYKHAYA_BACKUP_DIR)}
  directory=${directory:-./backups}
  [ -d "$directory" ] && [ -r "$directory" ] || die "the backup directory cannot be read (set MYKHAYA_BACKUP_DIR)"
  manifest=$(find "$directory" -maxdepth 1 -type f -name 'mykhaya-*.manifest' \
    -mmin "-$BACKUP_MAX_AGE_MINUTES" | sort | tail -n 1)
  [ -n "$manifest" ] || die "no backup from the last 24 hours; run: make backup"
  grep -qx 'encryption=age' "$manifest" || die "the latest backup is not encrypted"
  for kind in database files; do
    name=$(sed -n "s/^$kind=//p" "$manifest")
    expected=$(sed -n "s/^${kind}_sha256=//p" "$manifest")
    case "$name" in "" | */*) die "the latest backup manifest is not valid" ;; esac
    [ -f "$directory/$name" ] && [ "$(head -c 21 "$directory/$name")" = "age-encryption.org/v1" ] ||
      die "the latest $kind backup is missing or not age-encrypted"
    [ "$(sha256sum "$directory/$name" | cut -d' ' -f1)" = "$expected" ] ||
      die "the latest $kind backup does not match its manifest"
  done
  ok "an encrypted backup from the last 24 hours matches its manifest"
}

check_attested() {
  for statement in backup-restored keys-escrowed; do
    case " ${MYKHAYA_DEV_ATTEST:-} " in
      *" $statement "*) ;;
      *) die "set MYKHAYA_DEV_ATTEST=\"backup-restored keys-escrowed\" once both are true" ;;
    esac
  done
  ok "Owner attested a restored backup and escrowed keys"
}

check_packages() {
  open=$(docker exec "$(container postgres)" psql -U postgres -d mykhaya -Atc \
    "select count(*) from home_migration_packages where completed_at is null") || die "PostgreSQL could not be queried"
  [ "$open" = 0 ] || [ "${MYKHAYA_DEV_ACCEPT_OPEN_PACKAGES:-0}" = 1 ] ||
    die "$open Home Migration packages are in progress; finish them, or set MYKHAYA_DEV_ACCEPT_OPEN_PACKAGES=1"
  ok "Home Migration packages checked"
}

check_git() {
  [ "$(git branch --show-current)" = dev ] || die "the checkout is not on dev"
  [ -z "$(git status --porcelain)" ] || die "the working tree is not clean"
  ok "clean dev checkout"
}

check() {
  check_host
  say "Checking the DEV state"
  f03=$(f03_state) || exit 1
  secrets=$(secrets_state) || exit 1
  [ "$f03" = active ] || die "F-03 is $f03, not active. Complete the F-03 cutover first"
  case "$secrets" in
    legacy) expected="compose.yml compose.dev.yml compose.dev.service-env.yml" ;;
    pending) expected= ;;
    active) die "Docker Secrets are already active; use accept" ;;
    *) die "a rollback has not completed; run rollback" ;;
  esac
  ok "F-03 active, Docker Secrets $([ "$secrets" = legacy ] && echo "not started" || echo pending)"
  check_git
  deploy_script MYKHAYA_DEV_SECRETS=0 sh "$DEPLOY" config-check >/dev/null ||
    die "the F-03 configuration does not validate"
  ok "F-03 configuration and key directories validate"
  [ -z "$expected" ] || check_running "$expected"
  check_volumes
  check_backup
  check_packages
}

# Non-secret facts that the cutover must not change.
fingerprint() {
  postgres=$(container postgres)
  printf 'system_identifier=%s\n' "$(docker exec "$postgres" psql -U postgres -Atc \
    'select system_identifier from pg_control_system()')" || return 1
  printf 'revision=%s\n' "$(docker exec "$postgres" psql -U postgres -d mykhaya -Atc \
    'select version_num from alembic_version')" || return 1
  for pair in $DATA_VOLUMES; do
    printf 'volume %s=%s\n' "${pair#*:}" "$(docker volume inspect --format '{{.CreatedAt}}' "${pair#*:}")"
  done
  api=$(container api)
  # Counts only. A non-zero status means unreadable rows, which are part of the
  # comparison; no output at all means the check could not run.
  readable=$(docker exec "$api" python -m mykhaya.tools.encrypted_secrets_check 2>/dev/null) || true
  [ -n "$readable" ] || die "the encrypted-secret check could not run"
  printf 'encrypted_secrets=%s\n' "$readable"
  vehicles=0
  fields=$(docker exec "$api" python -m mykhaya.tools.driveway_ciphertext_check 2>/dev/null) || vehicles=$?
  [ "$vehicles" = 2 ] && fields=no-keyring
  [ -n "$fields" ] || die "the field-encryption check could not run"
  # Registrations and VINs can be added between the runs; failures must not be.
  printf 'field_failures=%s\n' "$(printf '%s' "$fields" | tr -d '\n ' |
    grep -oE '"(registration|vin)_(mismatch|decrypt_failed)":[0-9]+|no-keyring' | tr '\n' ' ')"
}

compare_baseline() {
  [ -f "$BASELINE" ] && [ ! -L "$BASELINE" ] || die "the baseline recorded before cutover is missing"
  now=$(fingerprint) || exit 1
  if [ "$now" != "$(cat "$BASELINE")" ]; then
    printf '%s\n' "$now" | diff - "$BASELINE" | sed -n 's/^[<>] \([a-z_]*\).*/changed: \1/p' | sort -u >&2
    die "DEV no longer matches the baseline. If no user changed an encrypted setting meanwhile, roll back"
  fi
  ok "database identity, schema, volumes and encrypted data match the baseline"
}

approve() { # phrase
  printf '\nType %s to continue: ' "$1"
  read -r answer || answer=
  [ "$answer" = "$1" ] || die "not approved; nothing was changed"
}

as_root() {
  sudo python3 -I -B "$SCRIPT_DIR/dev_secrets_migration.py" "$1" --root "$ROOT" --repo-root "$REPO_ROOT"
}

verify() {
  as_root verify
  deploy_script MYKHAYA_DEV_SECRETS=1 sh "$DEPLOY" config-check >/dev/null ||
    die "the file-backed configuration does not validate"
  ok "file-backed configuration, ownership, modes and per-service grants validate"
}

accept() {
  check_host
  [ "$(secrets_state)" = active ] || die "Docker Secrets are not active"
  say "Accepting the cutover"
  overlays="compose.yml compose.dev.yml compose.dev.service-env.yml compose.dev.secrets.yml"
  check_running "$overlays"
  check_volumes
  for service in api worker scheduler; do
    id=$(container "$service")
    env_is "$id" "MYKHAYA_PROCESS_ROLE=$service" || die "$service does not have its process role"
    for name in SECRET_KEY SMTP_PASSWORD VAPID_PRIVATE_KEY APNS_PRIVATE_KEY FCM_PRIVATE_KEY \
      APPLE_PRIVATE_KEY GOOGLE_CLIENT_SECRET STRIPE_SECRET_KEY STRIPE_WEBHOOK_SECRET \
      DVLA_UAT_API_KEY DVLA_PRODUCTION_API_KEY DVSA_CLIENT_ID DVSA_CLIENT_SECRET DVSA_API_KEY \
      MONITORING_WATCHDOG_URL FIELD_ENCRYPTION_KEYS BLIND_INDEX_KEYS DB_PASSWORD \
      MIGRATION_DB_PASSWORD POSTGRES_ADMIN_PASSWORD; do
      case "$(env_class "$id" "MYKHAYA_$name")" in
        absent | blank) ;;
        *) die "$service still has MYKHAYA_$name in its environment" ;;
      esac
    done
  done
  id=$(container postgres)
  for name in POSTGRES_PASSWORD MYKHAYA_DB_PASSWORD MYKHAYA_MIGRATION_DB_PASSWORD; do
    [ "$(env_class "$id" "$name")" = absent ] || die "postgres still has $name in its environment"
  done
  ok "process roles set; no credential in any container environment"
  for service in api worker scheduler; do
    [ "$(docker inspect --format '{{.State.Status}}:{{.RestartCount}}' "$(container "$service")")" = running:0 ] ||
      die "$service has restarted since the cutover"
  done
  ok "application services have not restarted"
  compare_baseline
  as_root scan
  say "Automatic acceptance passed"
  echo "Now complete the manual provider checks in docs/operations/dev-docker-secrets-migration.md."
}

cutover() {
  check_host
  check_attested
  check
  [ -d "$ROOT/file-backed" ] || die "provision the file-backed configuration first"
  say "Verifying the provisioned secrets"
  verify
  if [ "$(secrets_state)" = legacy ]; then
    fingerprint >"$BASELINE.tmp" || die "the baseline could not be recorded"
    mv -f "$BASELINE.tmp" "$BASELINE"
    ok "baseline recorded"
  else
    [ -f "$BASELINE" ] || die "resuming needs the original baseline, which is missing"
    ok "resuming; the original baseline is kept"
  fi
  echo
  echo "This replaces postgres (same volume), then api, worker and scheduler together, and"
  echo "restarts web, caddy and mailpit. Expect a short interruption. Redis is unchanged."
  approve "$CUTOVER_PHRASE"
  deploy_script MYKHAYA_DEV_SECRETS=1 MYKHAYA_DEV_SECRETS_APPROVED=1 sh "$DEPLOY" up ||
    die "the deployment did not complete. State: $(secrets_state). Fix the cause and rerun cutover, or run rollback"
  accept
}

rollback() {
  check_host
  f03=$(f03_state) || exit 1
  secrets=$(secrets_state) || exit 1
  [ "$f03" = active ] || die "F-03 is $f03; resolve it first"
  [ "$secrets" != legacy ] || die "Docker Secrets are not active; there is nothing to roll back"
  check_volumes_exist
  deploy_script MYKHAYA_DEV_SECRETS=0 MYKHAYA_DEV_SECRETS_ROLLBACK=1 sh "$DEPLOY" config-check >/dev/null ||
    die "the F-03 configuration does not validate"
  echo "This returns DEV to the F-03 configuration: same volumes, same credentials, no migration."
  approve "$ROLLBACK_PHRASE"
  deploy_script MYKHAYA_DEV_SECRETS=0 MYKHAYA_DEV_SECRETS_ROLLBACK=1 sh "$DEPLOY" up ||
    die "the rollback did not complete. State: $(secrets_state). Fix the cause and rerun rollback"
  check_running "compose.yml compose.dev.yml compose.dev.service-env.yml"
  check_volumes
  compare_baseline
  say "Rollback complete; the file-backed files were left in place"
}

# Before a rollback the containers may be stopped, so only existence is checked.
check_volumes_exist() {
  for pair in $DATA_VOLUMES; do
    docker volume inspect "${pair#*:}" >/dev/null 2>&1 || die "a persistent volume is missing"
  done
}

case "${1:-}" in
  status) check_host; status ;;
  check) check; say "All automatic prerequisites passed" ;;
  provision) check_host; [ "$(f03_state)" = active ] || die "F-03 is not active"
    [ "$(secrets_state)" = legacy ] || die "Docker Secrets have already started"
    as_root provision; verify ;;
  verify) check_host; verify ;;
  cutover) cutover ;;
  accept) accept ;;
  rollback) rollback ;;
  *) die "usage: $0 {status|check|provision|verify|cutover|accept|rollback}" ;;
esac
