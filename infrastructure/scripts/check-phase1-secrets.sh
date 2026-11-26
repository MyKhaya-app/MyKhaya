#!/usr/bin/env bash
# MK-SEC-001 v1.2 Phase 1 secret-handling checks (CI and local).
#
# Runs against disposable containers only, with synthetic credentials:
#   A. PostgreSQL bootstrap (infrastructure/docker/init-db.sh): file-backed and
#      legacy passwords, hostile characters, real SCRAM logins over the network,
#      refusals of conflicting or malformed secrets, an existing volume never
#      re-initialised, no password in psql arguments or container logs.
#   B. Migrator and application (SEC-088, SEC-086/086a, SEC-089): keyless
#      migrations, the migrate role refusing the key, a full migration and an
#      application connection with file-backed passwords, offline SQL and
#      failed connections without credentials, no password in process
#      arguments.
#
# Expects the repository root as the working directory, a prepared .env and
# built Compose images (CI's earlier steps). It never touches the Compose
# project's own volumes: part A uses its own containers, network and volumes,
# and part B runs one-off containers. Everything it creates is removed on exit.
set -euo pipefail

PG_IMAGE=postgres:17.5-alpine3.22
HELPER_IMAGE=$PG_IMAGE
RUN_ID="mk-p1-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
NET="$RUN_ID-net"
SECRETS="$RUN_ID-secrets"
TOOLS="$RUN_ID-tools"
WORK=$(mktemp -d "${WORK_DIR:-${TMPDIR:-/tmp}}/mk-p1.XXXXXX")
PYTHON=${PYTHON:-python3}
INIT_SCRIPT=${INIT_SCRIPT:-$PWD/infrastructure/docker/init-db.sh}
PROJECT=$(docker compose config --format json | "$PYTHON" -c 'import json, sys; print(json.load(sys.stdin)["name"])')
MIGRATE_IMAGE="$PROJECT-migrate"
API_IMAGE="$PROJECT-api"
CONTAINERS=()
VOLUMES=("$SECRETS" "$TOOLS")
FAILURES=0

cleanup() {
  for c in "${CONTAINERS[@]}"; do docker rm -f "$c" >/dev/null 2>&1 || true; done
  for v in "${VOLUMES[@]}"; do docker volume rm -f "$v" >/dev/null 2>&1 || true; done
  docker network rm "$NET" >/dev/null 2>&1 || true
  # Local debugging only: keep the (synthetic) work files for inspection.
  if [ -n "${KEEP_WORK:-}" ]; then cp -r "$WORK" "$KEEP_WORK"; fi
  rm -rf "$WORK"
}
trap cleanup EXIT

pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; FAILURES=$((FAILURES + 1)); }
check() { if eval "$2"; then pass "$1"; else fail "$1"; fi; }

# --- Synthetic secrets ---------------------------------------------------------
# Hostile on purpose: quotes, backslash, URL delimiters, shell syntax, non-ASCII.
"$PYTHON" - "$WORK" <<'PY'
import sys
from pathlib import Path

work = Path(sys.argv[1])
hostile = "S p@ss:w/rd%20?#&=+;'\"\\ -é-✓ $(id) `id` ${HOME}"
values = {
    "app": "app-" + hostile,
    "migrator": "mig-" + hostile,
    "admin": "adm-" + hostile,
    "legacy_app": "legacy-app-" + hostile,
    "legacy_migrator": "legacy-mig-" + hostile,
}
for name, value in values.items():
    (work / name).write_bytes((value + "\n").encode("utf-8"))
# Every value this script uses, one per line, for the leak scans.
(work / "patterns").write_text("\n".join([*values.values(), "p@ss:w/rd"]) + "\n", encoding="utf-8")
# Malformed secrets, each with the category init-db.sh must report.
bad = {
    "two_lines": b"synthetic-first-line\nsynthetic-second-line\n",
    "with_nul": b"synthetic\x00secret\n",
    "not_utf8": b"synthetic-\xc3\x28-secret\n",
    "overlong": b"synthetic-\xc0\xaf-secret\n",
    "empty": b"\n",
    "spaces": b" synthetic-padded-secret\n",
    "large": b"a" * 4097,
}
for name, data in bad.items():
    (work / name).write_bytes(data)
# Legacy literal values go through an env file, never a command line.
(work / "legacy.env").write_text(
    f"MYKHAYA_DB_PASSWORD={values['legacy_app']}\n"
    f"MYKHAYA_MIGRATION_DB_PASSWORD={values['legacy_migrator']}\n"
    f"POSTGRES_PASSWORD={values['admin']}\n",
    encoding="utf-8",
)
(work / "conflict.env").write_text(
    f"MYKHAYA_DB_PASSWORD={values['legacy_app']}\n", encoding="utf-8"
)
(work / "migrator-conflict.env").write_text(
    f"MYKHAYA_MIGRATION_DB_PASSWORD={values['legacy_migrator']}\n", encoding="utf-8"
)
PY

docker network create "$NET" >/dev/null
docker volume create "$SECRETS" >/dev/null
docker volume create "$TOOLS" >/dev/null
for f in app migrator admin two_lines with_nul not_utf8 overlong empty spaces large; do
  docker run --rm -i -v "$SECRETS:/s" "$HELPER_IMAGE" sh -c "cat > /s/$f && chmod 644 /s/$f" <"$WORK/$f"
done
docker run --rm -v "$SECRETS:/s" "$HELPER_IMAGE" sh -c 'mkdir /s/dir && ln -s /s/app /s/link'
# A psql that records every argument vector before running the real one, and
# refuses to run if it cannot. The log is in its own tmpfs, not /tmp: with
# fs.protected_regular (the default on GitHub's runners) even root cannot reopen
# a file the postgres user created in a sticky, world-writable directory.
docker run --rm -i -v "$TOOLS:/t" "$HELPER_IMAGE" sh -c 'cat > /t/psql && chmod 755 /t/psql' <<'SH'
#!/bin/sh
printf '%s\n' "$*" >> /argv-log/psql.log || { echo "psql argument capture failed" >&2; exit 97; }
exec /usr/local/bin/psql "$@"
SH

# The condition "docker logs | grep -q" is unreliable under pipefail: grep exits at
# the first match, docker logs can then die of SIGPIPE (141), and the pipeline
# fails although the text was found. Capture first, then search.
log_has() { # container, extended regular expression
  docker logs "$1" >"$WORK/container.log" 2>&1 && grep -qE -- "$2" "$WORK/container.log"
}

leaks() { grep -F -c -f "$WORK/patterns" "$1" || true; }

# --- A. PostgreSQL bootstrap ------------------------------------------------------
pg_run() { # variable to receive the container name, name suffix, docker run arguments
  local pg_name="$RUN_ID-$2"
  printf -v "$1" '%s' "$pg_name"
  shift 2
  CONTAINERS+=("$pg_name")
  docker run -d --name "$pg_name" --network "$NET" \
    -v "$SECRETS:/run/secrets:ro" -v "$TOOLS:/opt/argv:ro" --tmpfs /argv-log:mode=0777 \
    -v "$INIT_SCRIPT:/docker-entrypoint-initdb.d/10-init.sh:ro" \
    -e PATH=/opt/argv:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    -e POSTGRES_DB=mykhaya -e POSTGRES_USER=postgres "$@" "$PG_IMAGE" >/dev/null
}

pg_ready() { # name: wait for the post-initialisation server
  local _
  for _ in $(seq 1 90); do
    if [ "$(docker inspect -f '{{.State.Running}}' "$1")" != true ]; then return 1; fi
    # The log line first: before it, pg_isready can answer for the temporary
    # server the image runs during initialisation.
    if log_has "$1" 'init process complete|Skipping initialization' &&
      docker exec "$1" pg_isready -q -U postgres -d mykhaya 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}

pg_exit_code() { # name: wait for a refused initialisation to stop the container
  local _
  for _ in $(seq 1 90); do
    if [ "$(docker inspect -f '{{.State.Running}}' "$1")" != true ]; then
      docker inspect -f '{{.State.ExitCode}}' "$1"
      return
    fi
    sleep 1
  done
  printf 'timeout'
}

login() { # server, role, secret file: a real SCRAM login from another container
  docker run --rm --network "$NET" -v "$SECRETS:/run/secrets:ro" "$PG_IMAGE" sh -c \
    'PGPASSWORD="$(cat "/run/secrets/$3")" psql -w -h "$1" -U "$2" -d mykhaya -Atc "select current_user"' \
    sh "$1" "$2" "$3" 2>&1
}

login_literal() { # server, role, value file on the host, sent through stdin
  docker run --rm -i --network "$NET" "$PG_IMAGE" sh -c \
    'PGPASSWORD="$(cat)" psql -w -h "$1" -U "$2" -d mykhaya -Atc "select current_user"' \
    sh "$1" "$2" <"$3" 2>&1
}

login_refused() { # server, role, secret file: refused by password authentication itself
  local out
  out=$(login "$@") || true
  grep -q "password authentication failed" <<<"$out" && ! grep -qx "$2" <<<"$out"
}

sql() { docker exec "$1" psql -U postgres -d mykhaya -Atc "$2"; }

echo "== A. PostgreSQL bootstrap"
pg_run FILEPG file \
  -e POSTGRES_PASSWORD_FILE=/run/secrets/admin \
  -e MYKHAYA_DB_PASSWORD_FILE=/run/secrets/app \
  -e MYKHAYA_MIGRATION_DB_PASSWORD_FILE=/run/secrets/migrator
check "file-backed bootstrap initialises" "pg_ready $FILEPG"
docker logs "$FILEPG" >"$WORK/file.log" 2>&1
check "application role logs in with its file password" \
  '[ "$(login "$FILEPG" mykhaya_app app)" = mykhaya_app ]'
check "migrator role logs in with its file password" \
  '[ "$(login "$FILEPG" mykhaya_migrator migrator)" = mykhaya_migrator ]'
check "superuser logs in with POSTGRES_PASSWORD_FILE" \
  '[ "$(login "$FILEPG" postgres admin)" = postgres ]'
check "a wrong password is refused (SCRAM, not trust)" \
  'login_refused "$FILEPG" mykhaya_app migrator'
check "roles keep their attributes" '[ "$(sql "$FILEPG" "select string_agg(format(\$\$%s:%s%s%s%s%s\$\$, rolname, rolsuper, rolcreatedb, rolcreaterole, rolinherit, rolcanlogin), \$\$,\$\$ order by rolname) from pg_roles where rolname like \$\$mykhaya_%\$\$")" = "mykhaya_app:fffft,mykhaya_migrator:fffft" ]'
check "database is owned by the migrator" \
  '[ "$(sql "$FILEPG" "select pg_get_userbyid(datdba) from pg_database where datname = \$\$mykhaya\$\$")" = mykhaya_migrator ]'
check "application role keeps its default privileges" '[ "$(sql "$FILEPG" "select string_agg(format(\$\$%s:%s:%s\$\$, defaclrole::regrole, defaclobjtype, defaclacl), \$\$;\$\$ order by defaclobjtype) from pg_default_acl")" = "mykhaya_migrator:S:{mykhaya_app=rU/mykhaya_migrator};mykhaya_migrator:r:{mykhaya_app=arwd/mykhaya_migrator}" ]'
docker exec "$FILEPG" cat /argv-log/psql.log >"$WORK/argv.log"
# Both identities: the bootstrap (postgres) and the queries above (root).
check "psql was invoked (argument capture works)" \
  'grep -q -- "--dbname mykhaya" "$WORK/argv.log" && grep -q "from pg_default_acl" "$WORK/argv.log"'
# (The image's own entrypoint passes --no-password; only values matter here.)
check "no password in any psql argument" '[ "$(leaks "$WORK/argv.log")" -eq 0 ]'
check "no password in the container log" '[ "$(leaks "$WORK/file.log")" -eq 0 ]'

echo "-- legacy literal passwords (env file, as Compose supplies them)"
pg_run LEGACYPG legacy --env-file "$WORK/legacy.env"
check "legacy bootstrap initialises" "pg_ready $LEGACYPG"
check "legacy application password logs in" \
  '[ "$(login_literal "$LEGACYPG" mykhaya_app "$WORK/legacy_app")" = mykhaya_app ]'
check "legacy migrator password logs in" \
  '[ "$(login_literal "$LEGACYPG" mykhaya_migrator "$WORK/legacy_migrator")" = mykhaya_migrator ]'
docker logs "$LEGACYPG" >"$WORK/legacy.log" 2>&1
check "no password in the legacy container log" '[ "$(leaks "$WORK/legacy.log")" -eq 0 ]'

echo "-- an existing data volume is never re-initialised"
DATA="$RUN_ID-data"; VOLUMES+=("$DATA")
docker volume create "$DATA" >/dev/null
pg_run FIRST first --env-file "$WORK/legacy.env" -v "$DATA:/var/lib/postgresql/data"
check "first start initialises the volume" "pg_ready $FIRST"
check "the first start really ran initialisation" 'log_has "$FIRST" "init process complete"'
# shellcheck disable=SC2034 # read by the condition check() evaluates.
CLUSTER=$(sql "$FIRST" "select system_identifier from pg_control_system()")
docker rm -f "$FIRST" >/dev/null
pg_run SECOND second -v "$DATA:/var/lib/postgresql/data" \
  -e POSTGRES_PASSWORD_FILE=/run/secrets/admin \
  -e MYKHAYA_DB_PASSWORD_FILE=/run/secrets/app \
  -e MYKHAYA_MIGRATION_DB_PASSWORD_FILE=/run/secrets/migrator
check "restart with file secrets starts the existing database" "pg_ready $SECOND"
check "initialisation is skipped" \
  'log_has "$SECOND" "Skipping initialization" && ! grep -qE "init process complete|running bootstrap script" "$WORK/container.log"'
# Assigned by initdb, so any re-initialisation would change it.
check "the database cluster identity is unchanged" \
  '[[ "$CLUSTER" =~ ^[0-9]+$ ]] && [ "$(sql "$SECOND" "select system_identifier from pg_control_system()")" = "$CLUSTER" ]'
check "existing passwords are unchanged" \
  '[ "$(login_literal "$SECOND" mykhaya_app "$WORK/legacy_app")" = mykhaya_app ]'
check "new file passwords were not applied" 'login_refused "$SECOND" mykhaya_app app'

echo "-- refused configurations (fail closed, nothing echoed)"
refused() { # label, expected message, then extra docker run arguments
  local label=$1 message=$2 name code
  shift 2
  pg_run name "refused-$(printf '%s' "$label" | tr -c 'a-z0-9' '-')" \
    -e POSTGRES_PASSWORD_FILE=/run/secrets/admin "$@"
  code=$(pg_exit_code "$name")
  docker logs "$name" >"$WORK/refused.log" 2>&1
  if [ "$code" != 0 ] && [ "$code" != timeout ] && grep -qF "init-db: $message" "$WORK/refused.log" &&
    [ "$(leaks "$WORK/refused.log")" -eq 0 ] && ! grep -q synthetic "$WORK/refused.log"; then
    pass "refuses $label"
  else
    fail "refuses $label (exit $code)"
    grep -E 'init-db|ERROR|FATAL' "$WORK/refused.log" | head -3 || true
  fi
}
MIG=(-e MYKHAYA_MIGRATION_DB_PASSWORD_FILE=/run/secrets/migrator)
refused "a literal and a file together" "Set MYKHAYA_DB_PASSWORD or MYKHAYA_DB_PASSWORD_FILE, not both" \
  "${MIG[@]}" --env-file "$WORK/conflict.env" -e MYKHAYA_DB_PASSWORD_FILE=/run/secrets/app
refused "a missing password" "MYKHAYA_DB_PASSWORD or MYKHAYA_DB_PASSWORD_FILE is required" "${MIG[@]}"
refused "a path outside /run/secrets" "MYKHAYA_DB_PASSWORD_FILE is outside the approved secret locations" \
  "${MIG[@]}" -e MYKHAYA_DB_PASSWORD_FILE=/etc/hostname
refused "a relative path" "MYKHAYA_DB_PASSWORD_FILE is outside the approved secret locations" \
  "${MIG[@]}" -e MYKHAYA_DB_PASSWORD_FILE=run/secrets/app
refused "a non-normalised path" "MYKHAYA_DB_PASSWORD_FILE must be a normalised path without '.' or '..'" \
  "${MIG[@]}" -e MYKHAYA_DB_PASSWORD_FILE=/run/secrets/dir/../app
refused "a symbolic link" "MYKHAYA_DB_PASSWORD_FILE path contains a symbolic link" \
  "${MIG[@]}" -e MYKHAYA_DB_PASSWORD_FILE=/run/secrets/link
refused "a missing file" "MYKHAYA_DB_PASSWORD_FILE is missing" \
  "${MIG[@]}" -e MYKHAYA_DB_PASSWORD_FILE=/run/secrets/absent
refused "a directory" "MYKHAYA_DB_PASSWORD_FILE is not a regular file" \
  "${MIG[@]}" -e MYKHAYA_DB_PASSWORD_FILE=/run/secrets/dir
refused "two lines" "MYKHAYA_DB_PASSWORD_FILE must contain a single line" \
  "${MIG[@]}" -e MYKHAYA_DB_PASSWORD_FILE=/run/secrets/two_lines
refused "a NUL byte" "MYKHAYA_DB_PASSWORD_FILE contains a NUL byte" \
  "${MIG[@]}" -e MYKHAYA_DB_PASSWORD_FILE=/run/secrets/with_nul
refused "invalid UTF-8" "MYKHAYA_DB_PASSWORD_FILE is not valid UTF-8" \
  "${MIG[@]}" -e MYKHAYA_DB_PASSWORD_FILE=/run/secrets/not_utf8
refused "overlong UTF-8" "MYKHAYA_DB_PASSWORD_FILE is not valid UTF-8" \
  "${MIG[@]}" -e MYKHAYA_DB_PASSWORD_FILE=/run/secrets/overlong
refused "an empty file" "MYKHAYA_DB_PASSWORD_FILE is empty" \
  "${MIG[@]}" -e MYKHAYA_DB_PASSWORD_FILE=/run/secrets/empty
refused "surrounding whitespace" "MYKHAYA_DB_PASSWORD_FILE must not have leading or trailing whitespace" \
  "${MIG[@]}" -e MYKHAYA_DB_PASSWORD_FILE=/run/secrets/spaces
refused "an oversized file" "MYKHAYA_DB_PASSWORD_FILE is too large" \
  "${MIG[@]}" -e MYKHAYA_DB_PASSWORD_FILE=/run/secrets/large
refused "a migrator literal and file together" \
  "Set MYKHAYA_MIGRATION_DB_PASSWORD or MYKHAYA_MIGRATION_DB_PASSWORD_FILE, not both" \
  --env-file "$WORK/migrator-conflict.env" "${MIG[@]}" -e MYKHAYA_DB_PASSWORD_FILE=/run/secrets/app

# --- B. Migrator and application ---------------------------------------------------
echo "== B. Migrator and application (images: $MIGRATE_IMAGE, $API_IMAGE)"
check "migrate and api images are built" \
  'docker image inspect "$MIGRATE_IMAGE" >/dev/null 2>&1 && docker image inspect "$API_IMAGE" >/dev/null 2>&1'

app_run() { # image, docker run options, --, command: a one-off container on the test network
  local image=$1 options=()
  shift
  while [ "$1" != -- ]; do options+=("$1"); shift; done
  shift
  docker run --rm --network "$NET" -v "$SECRETS:/run/secrets:ro" "${options[@]}" "$image" "$@"
}
MIGRATOR_FILE_ENV=(
  -e MYKHAYA_PROCESS_ROLE=migrate
  -e "MYKHAYA_DATABASE_URL=postgresql+asyncpg://mykhaya_migrator@$FILEPG:5432/mykhaya"
  -e MYKHAYA_DATABASE_PASSWORD_FILE=/run/secrets/migrator
)

app_run "$MIGRATE_IMAGE" "${MIGRATOR_FILE_ENV[@]}" -- sh -c '
  if env | grep -q "^MYKHAYA_SECRET_KEY"; then echo "key present"; exit 1; fi
  alembic upgrade head >/tmp/up.log 2>&1 &
  pid=$!
  # Every process argument vector while the migration runs.
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    for f in /proc/[0-9]*/cmdline; do tr "\000" " " <"$f" 2>/dev/null; echo; done
    sleep 0.3
  done >/tmp/argv.log
  wait "$pid" && alembic downgrade base && alembic upgrade head && alembic current
  cat /tmp/up.log /tmp/argv.log
' >"$WORK/migrate-file.log" 2>&1 && rc=0 || rc=$?
check "keyless migrate role: upgrade, downgrade, upgrade with a file-backed hostile password" \
  '[ "$rc" -eq 0 ] && grep -q "(head)" "$WORK/migrate-file.log" && grep -q "alembic upgrade head" "$WORK/migrate-file.log"'
check "no password in migrator output or any process argument" '[ "$(leaks "$WORK/migrate-file.log")" -eq 0 ]'

# Synthetic keys are generated here and handed to docker by name only
# (-e NAME), so no value is ever a command-line argument.
MYKHAYA_SECRET_KEY="synthetic-refused-$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
export MYKHAYA_SECRET_KEY
app_run "$MIGRATE_IMAGE" "${MIGRATOR_FILE_ENV[@]}" -e MYKHAYA_SECRET_KEY \
  -- alembic current >"$WORK/migrate-key.log" 2>&1 && rc=0 || rc=$?
check "migrate role refuses the application key without echoing it" \
  '[ "$rc" -ne 0 ] && grep -q "MYKHAYA_SECRET_KEY (K-01)" "$WORK/migrate-key.log" && ! grep -q synthetic-refused "$WORK/migrate-key.log"'
MYKHAYA_SECRET_KEY="synthetic-application-$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"

app_run "$MIGRATE_IMAGE" -e "MYKHAYA_DATABASE_URL=postgresql+asyncpg://mykhaya_migrator:synthetic-url-secret@$FILEPG:5432/mykhaya" \
  -- alembic upgrade base:0015_colour_palette --sql >"$WORK/offline.sql" 2>&1 && rc=0 || rc=$?
# (Offline SQL stops at 0015: revision 0016 reads table data, which offline
# mode cannot do. Every revision runs online above.)
check "offline SQL renders without credentials" \
  '[ "$rc" -eq 0 ] && grep -q "CREATE TABLE" "$WORK/offline.sql" && ! grep -q synthetic-url-secret "$WORK/offline.sql"'

app_run "$MIGRATE_IMAGE" -e "MYKHAYA_DATABASE_URL=postgresql+asyncpg://mykhaya_migrator:synthetic-wrong-secret@$FILEPG:5432/mykhaya" \
  -- alembic current >"$WORK/wrong.log" 2>&1 && rc=0 || rc=$?
check "a refused connection reports no credential" \
  '[ "$rc" -ne 0 ] && grep -qi "password authentication failed" "$WORK/wrong.log" && ! grep -q synthetic-wrong-secret "$WORK/wrong.log"'

PROBE='import asyncio, os
from sqlalchemy import text
from mykhaya.config import get_settings
settings = get_settings()
from mykhaya.db import engine
async def main():
    async with engine.connect() as connection:
        print("connected as", (await connection.execute(text("select current_user"))).scalar())
asyncio.run(main())
secret = open("/run/secrets/app", encoding="utf-8").read().rstrip("\n")
texts = (repr(settings), settings.model_dump_json(), str(engine.url), repr(engine.url), *os.environ.values())
print("password exposed:", any(secret in t for t in texts))'
# shellcheck disable=SC2034 # rc is read by the condition check() evaluates.
app_run "$API_IMAGE" -e MYKHAYA_PROCESS_ROLE=api -e MYKHAYA_ENVIRONMENT=test \
  -e MYKHAYA_SECRET_KEY \
  -e "MYKHAYA_DATABASE_URL=postgresql+asyncpg://mykhaya_app@$FILEPG:5432/mykhaya" \
  -e MYKHAYA_DATABASE_PASSWORD_FILE=/run/secrets/app -e "PROBE=$PROBE" \
  -- python -c "$PROBE" >"$WORK/api.log" 2>&1 && rc=0 || rc=$?
check "api role connects with a file-backed hostile password" \
  '[ "$rc" -eq 0 ] && grep -q "connected as mykhaya_app" "$WORK/api.log" && grep -q "password exposed: False" "$WORK/api.log"'
check "no password in api output" '[ "$(leaks "$WORK/api.log")" -eq 0 ]'

docker logs "$FILEPG" >"$WORK/file-final.log" 2>&1
check "no password in the database server log after migrations" '[ "$(leaks "$WORK/file-final.log")" -eq 0 ]'

echo
if [ "$FAILURES" -ne 0 ]; then
  echo "Phase 1 secret checks: $FAILURES failure(s)"
  exit 1
fi
echo "Phase 1 secret checks: all passed"
