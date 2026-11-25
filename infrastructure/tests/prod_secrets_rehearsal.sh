#!/bin/bash
# check evaluates its conditions, so variables and functions look unused.
# shellcheck disable=SC2034,SC2024,SC2033,SC2016,SC2015
# The inside of check-prod-secrets-migration.sh. Only ever runs in its disposable
# nested Docker daemon, as root; the operator steps run as a "deploy" account
# with Docker access. Every credential is synthetic and generated here. It
# proves the tooling, never the production host.
set -uo pipefail
[ -f /.dockerenv ] && [ -d /srv/mykhaya ] && ! docker volume inspect mykhaya_postgres_data >/dev/null 2>&1 ||
  { echo "refusing to run outside the disposable rehearsal container" >&2; exit 1; }

REPO=/srv/mykhaya
ROOT=/etc/mykhaya/prod
WORK=/tmp/rehearsal
FAILURES=0
CHECKS=0
pass() { CHECKS=$((CHECKS + 1)); printf 'PASS  %s\n' "$1"; }
fail() {
  CHECKS=$((CHECKS + 1)); FAILURES=$((FAILURES + 1)); printf 'FAIL  %s\n' "$1"
  [ ! -s "$WORK/out" ] || tail -n 25 "$WORK/out" | sed 's/^/      /'
}
check() { if eval "$2"; then pass "$1"; else fail "$1"; fi; }
# A step everything after it depends on: later checks would pass vacuously.
must() { check "$@"; [ "$FAILURES" -eq 0 ] || { echo "stopping: a required step failed"; exit 1; }; }

mkdir -p "$WORK" && chmod 777 "$WORK"
addgroup -g 5000 deploy && adduser -D -u 5000 -G deploy -s /bin/bash deploy
sock_group=$(stat -c %G /var/run/docker.sock)
[ "$sock_group" != UNKNOWN ] || { addgroup -g "$(stat -c %g /var/run/docker.sock)" dockersock; sock_group=dockersock; }
addgroup deploy "$sock_group"
echo 'deploy ALL=(ALL) NOPASSWD: ALL' >/etc/sudoers.d/deploy
# FAIL_ON makes one Docker step fail, to rehearse interruptions.
cat >/usr/local/sbin/docker <<'SH'
#!/bin/sh
if [ -n "${FAIL_ON:-}" ]; then case "$*" in *"$FAIL_ON"*) echo "simulated failure" >&2; exit 1 ;; esac; fi
exec /usr/local/bin/docker "$@"
SH
chmod 755 /usr/local/sbin/docker

TAG=v$(python3 - <<'PY'
import tomllib
print(tomllib.load(open("/srv/mykhaya/apps/api/pyproject.toml", "rb"))["project"]["version"])
PY
)
HOST=$(hostname)
BUILT=2026-01-02T03:04:05Z
as_deploy() { # VAR=value words, then a command, in the checkout
  sudo -u deploy env PATH=/usr/local/sbin:/usr/local/bin:/usr/bin:/bin HOME=/home/deploy \
    MYKHAYA_PRODUCTION=1 MYKHAYA_RELEASE_TAG="$TAG" sh -c "cd $REPO && exec env \"\$@\"" sh "$@" >"$WORK/out" 2>&1
}
# sec [VAR=value...] ACTION [options]; typed approvals come from $PHRASES.
sec() {
  local vars=()
  while [[ "$1" == *=* && "$1" != -* ]]; do vars+=("$1"); shift; done
  printf '%b' "${PHRASES:-}" | as_deploy "${vars[@]}" sh infrastructure/scripts/prod-security-migrate.sh "$@" --expect-host "$HOST"
}
F03="MIGRATE PROD F-03\n"
SECRETS="MIGRATE PROD SECRETS\n"
says() { grep -qF -- "$1" "$WORK/out"; }
cid() { docker ps -q --no-trunc --filter label=com.docker.compose.project=mykhaya --filter "label=com.docker.compose.service=$1"; }
ids() { for s in "$@"; do cid "$s"; done; }
py() { docker exec -i "$(cid "$1")" python - ; }
sql() { docker exec "$(cid postgres)" psql -q -v ON_ERROR_STOP=1 -U postgres -d mykhaya -Atc "$1"; }
state() { sed -n 1p "$ROOT/$1" 2>/dev/null || echo absent; }
ready() { curl -fsS --max-time 10 -H 'Host: synthetic.example.invalid' http://127.0.0.1/api/v1/health/ready >/dev/null 2>&1; }
volumes() { docker volume ls -q | grep '^mykhaya_' | sort | xargs docker volume inspect --format '{{.Name}} {{.CreatedAt}}'; }

# --- Synthetic production ---------------------------------------------------------
install -d -o root -g 10001 -m 0750 /etc/mykhaya/keys/field /etc/mykhaya/keys/apple
chmod 755 /etc/mykhaya /etc/mykhaya/keys
docker run --rm -i --entrypoint python mykhaya-api - >"$WORK/generated.json" <<'PY'
import base64, json, secrets
from cryptography.hazmat.primitives import serialization as s
from cryptography.hazmat.primitives.asymmetric import ec, rsa

def pem(key):
    return key.private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption()).decode()

def ring(purpose):
    return json.dumps({"format": "mykhaya-keyring-v1", "purpose": purpose, "environment": "production",
                       "active": "p1", "keys": {"p1": base64.b64encode(secrets.token_bytes(32)).decode()}})

print(json.dumps({
    "apple": pem(ec.generate_private_key(ec.SECP256R1())), "apns": pem(ec.generate_private_key(ec.SECP256R1())),
    "fcm": pem(rsa.generate_private_key(65537, 2048)),
    "field": ring("field-encryption"), "blind": ring("blind-index"),
    "vapid": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="),
    "tokens": [secrets.token_urlsafe(32) for _ in range(16)],
}))
PY
python3 - "$WORK" $REPO <<'PY'
import json, sys
from pathlib import Path
work, repo = Path(sys.argv[1]), Path(sys.argv[2])
sys.path[:0] = [str(repo / "infrastructure/tests"), str(repo / "infrastructure/scripts")]
import service_env_contract as contract, synthetic_prod_config as synthetic
g = json.loads((work / "generated.json").read_text())
keys = Path("/etc/mykhaya/keys")
(keys / "field/field-encryption-keys.json").write_text(g["field"])
(keys / "field/blind-index-keys.json").write_text(g["blind"])
(keys / "apple/apple.p8").write_text(g["apple"])
env, problems = contract.parse_env_text(synthetic.legacy_env(keys / "field", keys / "apple"), ".env")
assert not problems
t = g["tokens"]
env.update({"MYKHAYA_" + k: v for k, v in {
    "SECRET_KEY": t[0], "POSTGRES_ADMIN_PASSWORD": t[1], "MIGRATION_DB_PASSWORD": t[2], "DB_PASSWORD": t[3],
    "SMTP_PASSWORD": t[4] + ' p@ss:w/rd%20?#&=+;"\\ $(id) é', "EMAIL_DELIVERY_CONFIGURED": "true",
    "VAPID_PUBLIC_KEY": "synthetic-public", "VAPID_PRIVATE_KEY": g["vapid"],
    "VAPID_SUBJECT": "mailto:synthetic@synthetic.example.invalid", "PUSH_DELIVERY_CONFIGURED": "true",
    "APNS_DELIVERY_CONFIGURED": "true", "APNS_PRIVATE_KEY": g["apns"].strip(),
    "FCM_DELIVERY_CONFIGURED": "true", "FCM_PRIVATE_KEY": g["fcm"].strip().replace("\n", "\\n"),
    "APPLE_SIGN_IN_ENABLED": "true", "APPLE_CLIENT_ID": "synthetic", "APPLE_SERVICE_ID": "synthetic",
    "APPLE_TEAM_ID": "SYNTHETIC1", "APPLE_KEY_ID": "SYNTHETIC3",
    "APPLE_PRIVATE_KEY_FILE": "/run/secrets/mykhaya-apple/apple.p8",
    "GOOGLE_SIGN_IN_ENABLED": "true", "GOOGLE_CLIENT_ID": "synthetic", "GOOGLE_CLIENT_SECRET": t[5],
    "STRIPE_BILLING_CONFIGURED": "true", "STRIPE_SECRET_KEY": "sk_" + "live_" + t[6],
    "STRIPE_WEBHOOK_SECRET": "whsec_" + t[7], "STRIPE_FAMILY_MONTHLY_PRICE_ID": "price_m",
    "STRIPE_FAMILY_ANNUAL_PRICE_ID": "price_a",
    "DVLA_PRODUCTION_API_KEY": t[8], "DVSA_CLIENT_ID": t[9], "DVSA_CLIENT_SECRET": t[10], "DVSA_API_KEY": t[11],
    "MONITORING_WATCHDOG_URL": "https://watchdog.example.invalid/" + t[12],
    "SENSITIVE_FIELD_KEYS_REQUIRED": "true", "BACKUP_DIR": "/srv/backups",
    "FIELD_ENCRYPTION_KEYS_FILE": "/run/secrets/mykhaya/field-encryption-keys.json",
    "BLIND_INDEX_KEYS_FILE": "/run/secrets/mykhaya/blind-index-keys.json",
}.items()})
(repo / ".env").write_text("".join(f"{k}={contract.format_env_value(v)}\n" for k, v in env.items()))
PY
chown root:10001 /etc/mykhaya/keys/*/* && chmod 0440 /etc/mykhaya/keys/*/*
install -d -o deploy -g deploy -m 0700 /srv/backups /var/lib/mykhaya
age-keygen -o "$WORK/identity.txt" 2>/dev/null && age-keygen -y "$WORK/identity.txt" >/etc/mykhaya/backup-recipients.txt
chmod 644 /etc/mykhaya/backup-recipients.txt
chown -R deploy:deploy "$REPO" && chmod 600 "$REPO/.env"
dgit() { sudo -u deploy git -C "$REPO" -c user.email=t@example.invalid -c user.name=t "$@"; }
dgit init -q -b main && dgit add -A && dgit commit -q -m release && dgit tag "$TAG"
install -d -o deploy -g deploy /srv/origin.git && sudo -u deploy git clone -q --bare "$REPO" /srv/origin.git
dgit remote add origin /srv/origin.git && dgit fetch -q origin && dgit checkout -q --detach "$TAG"
HEAD=$(dgit rev-parse HEAD)
for s in api worker scheduler migrate web; do
  docker build -q -t "mykhaya-$s" - >/dev/null 2>&1 <<EOF
FROM mykhaya-$s
ENV MYKHAYA_VERSION=$TAG MYKHAYA_COMMIT_SHA=$HEAD MYKHAYA_BUILD_TIME=$BUILT MYKHAYA_BUILD_CHANNEL=stable
LABEL org.opencontainers.image.version=$TAG org.opencontainers.image.revision=$HEAD org.opencontainers.image.created=$BUILT
EOF
done
# Volumes whose Compose labels do not match, with content: one from outside
# Compose, one whose recorded definition differs (newer Compose offers to
# delete and recreate such a volume).
docker volume create mykhaya_prod_home_migration_data >/dev/null
docker volume create --label com.docker.compose.project=mykhaya --label com.docker.compose.volume=legal_evidence_data \
  --label com.docker.compose.config-hash=0000 mykhaya_legal_evidence_data >/dev/null
docker run --rm -v mykhaya_legal_evidence_data:/v postgres:17.5-alpine3.22 sh -c 'echo kept >/v/marker'

echo "== 1. Legacy production"
date -u +%Y-%m-%dT%H:%M:%SZ >/var/lib/mykhaya/last-backup.ok && chown deploy /var/lib/mykhaya/last-backup.ok
as_deploy MYKHAYA_VERSION="$TAG" MYKHAYA_COMMIT_SHA="$HEAD" MYKHAYA_BUILD_TIME=$BUILT MYKHAYA_BUILD_CHANNEL=stable \
  docker compose -f compose.yml -f compose.production.yml up -d --no-build --wait postgres redis
as_deploy MYKHAYA_PROD_REUSE_IMAGES=1 sh infrastructure/scripts/prod-deploy.sh update
must "legacy production deploys" 'says "Deployed release: $TAG" && ready'
py api >"$WORK/envelope" <<'PY'
import asyncio, json, uuid
from mykhaya.config import get_settings
from mykhaya.crypto import encrypt_sensitive_value
from mykhaya.crypto.config import get_field_keyring
from mykhaya.db import SessionFactory
from mykhaya.driveway_sensitive import vin_binding
from mykhaya.secrets_crypto import encrypt_secret
from sqlalchemy import text

async def seed():
    async with SessionFactory() as db:
        await db.execute(text("insert into platform_settings (id, key, value, created_at, updated_at) values "
            "(gen_random_uuid(), 'bookstack_sync', cast(:v as json), now(), now())"),
            {"v": json.dumps({"value": {"token_secret_encrypted": encrypt_secret(
                get_settings(), "doc-secret", info=b"mykhaya-bookstack-token-v1")}})})
        await db.commit()
asyncio.run(seed())
print(encrypt_sensitive_value("SYNTHETICVIN", binding=vin_binding(uuid.UUID(int=7)), keyring=get_field_keyring()))
PY
must "encrypted test data written" '[ -s "$WORK/envelope" ]'
VOLUMES=$(volumes)
ENV_SUM=$(sha256sum <"$REPO/.env")
KEYS=$(cat /etc/mykhaya/keys/*/* | sha256sum)
DB=$(sql "select system_identifier from pg_control_system()")
LEGACY_IDS=$(ids postgres redis web caddy api worker scheduler)

echo "== 2. Preflight refusals"
sec status
check "status reports the legacy stage without a root" 'says "Stage: legacy"'
sec check
check "a missing configuration root is refused" 'says "configuration root does not exist"'
install -d -o deploy -g deploy -m 0750 "$ROOT"
as_deploy sh infrastructure/scripts/prod-security-migrate.sh check --expect-host another-host
check "another host is refused" 'says "does not match --expect-host"'
install -d /etc/mykhaya/dev; sec check; rmdir /etc/mykhaya/dev
check "a host with DEV configuration is refused" 'says "this is not the PROD host"'
sec MYKHAYA_PRODUCTION= check
check "production must be explicit" 'says "set MYKHAYA_PRODUCTION=1"'
sec MYKHAYA_RELEASE_TAG=v0.0.1 check
check "another release is refused" 'says "FAIL] release"'
sudo -u deploy touch $REPO/stray; sec check; rm $REPO/stray
check "a dirty checkout is refused" 'says "uncommitted or untracked changes"'
sec check
check "a stale or unmatched backup is refused" 'says "no backup manifest matches"'
as_deploy sh infrastructure/scripts/backup.sh
must "production backup in legacy mode" 'says .sql.gz.age'
MANIFEST=$(basename "$(ls /srv/backups/*.manifest | tail -n 1)")
LEGACY_DUMP=$(ls /srv/backups/*.sql.gz.age | tail -n 1)
sec check
must "check passes from legacy" 'says "Automatic checks for the next stage passed (now: legacy)"'
check "label mismatches are reported and left alone" '[ "$(volumes)" = "$VOLUMES" ]'
add_packages() { # count, status, completed_at expression
  sql "insert into home_migration_packages (id, migration_id, package_checksum, storage_key, source_home_id,
    summary, status, created_by, created_at, completed_at) select gen_random_uuid(), gen_random_uuid(), 'synthetic',
    gen_random_uuid()::text, gen_random_uuid(), '{}', '$2', gen_random_uuid(), now(), $3 from generate_series(1, $1)"
}
drop_newest() { sql "delete from home_migration_packages where id = (select id from home_migration_packages order by created_at desc limit 1)"; }
add_packages 18 expired null; add_packages 1 discarded null; add_packages 1 completed 'now()'
PACKAGES='select md5(string_agg(p::text, chr(10) order by id)) from home_migration_packages p'
PACKAGES_SUM=$(sql "$PACKAGES")
sec check
check "expired, discarded and completed packages do not block" 'says "next stage passed"'
add_packages 1 importing null; sec check --accept-unresolved-packages 1
check "an importing package blocks, with no override" 'says "uploaded or importing"'
drop_newest
add_packages 1 failed null; sec check
check "a retryable package blocks" 'says "1 Home Migration package(s) are unresolved"'
sec check --accept-unresolved-packages 2
check "the override must state the exact number" 'says "1 Home Migration package(s) are unresolved"'
drop_newest
add_packages 1 unknown null; sec check
check "an unknown package state blocks" 'says "1 Home Migration package(s) are unresolved"'
drop_newest
sec backup-config
must "configuration backup" 'says "Encrypted configuration backup:"'
CONFIG=$(sed -n 's#^Encrypted configuration backup: .*/##p' "$WORK/out")
confirm() { printf -- '--confirm-offhost-backup\n%s\n--confirm-offhost-config-backup\n%s\n--confirm-key-escrow\n--confirm-restore-rehearsal\n2026-01-01\n' "$MANIFEST" "$CONFIG"; }
apply() { local a; mapfile -t a < <(confirm); local vars=(); while [[ "${1:-}" == *=* ]]; do vars+=("$1"); shift; done; sec "${vars[@]}" apply "${a[@]}"; }
PHRASES=$F03 sec apply
check "apply without restore evidence is refused" 'says "--confirm-restore-rehearsal must be the date"'
PHRASES=$F03 sec apply --confirm-restore-rehearsal 2026-01-01
check "apply without the confirmations is refused" 'says "REFUSED"'
sec provision
check "provisioning before F-03 is refused" 'says "provisioning needs F-03 active"'
PHRASES="no\n" apply
check "an unapproved apply changes nothing" 'says "Not approved" && [ "$(state .service-env-state)" = absent ] && [ "$(ids postgres redis web caddy api worker scheduler)" = "$LEGACY_IDS" ]'

echo "== 3. Stage 1: F-03"
PHRASES=$F03 apply FAIL_ON="run --rm --no-deps -T migrate"
check "an interrupted F-03 leaves pending and the old application running" '[ "$(state .service-env-state)" = pending ] && ready'
sec status
check "status explains the interruption" 'says "Stage: f03-pending"'
as_deploy MYKHAYA_PROD_REUSE_IMAGES=1 sh infrastructure/scripts/prod-deploy.sh update
check "an ordinary update is refused while pending" 'says "has not been verified"'
PHRASES=$F03 apply
must "F-03 resumes, then stops at the unapproved second stage" '[ "$(state .service-env-state)" = active ] && [ "$(state .secrets-state)" = absent ] && says "Not approved" && ready'
check "data, web and proxy containers were not recreated" '[ "$(ids postgres redis web caddy)" = "$(head -n 4 <<<"$LEGACY_IDS")" ]'
F03_ENV=$(cat $ROOT/*.env | sha256sum)
check "the unapproved second stage had only provisioned files" '[ -d $ROOT/file-backed ]'

echo "== 4. F-03 active: provisioning and verification"
mv $ROOT/file-backed $WORK/first-provision
sec check
must "check passes from F-03" 'says "now: f03-active"'
sec provision
must "provisioning succeeds" 'says "Provisioned" && says "equals the F-03 values and validates"'
check "provisioning is reproducible" 'diff -r $ROOT/file-backed $WORK/first-provision >/dev/null'
rm -rf $WORK/first-provision
check "secret files are root-owned 0440 with the right groups" \
  '[ "$(stat -c "%U:%g:%a" $ROOT/file-backed/secrets/app/* | sort -u)" = root:10001:440 ] && [ "$(stat -c "%U:%g:%a" $ROOT/file-backed/secrets/postgres/* | sort -u)" = root:70:440 ]'
check "the deployment account cannot read a secret" '! sudo -u deploy cat $ROOT/file-backed/secrets/app/secret_key >/dev/null 2>&1'
check "no credential remains in the file-backed env files" \
  '! grep -qE "^(MYKHAYA_SECRET_KEY|MYKHAYA_[A-Z_]*PASSWORD|MYKHAYA_[A-Z_]*(PRIVATE_KEY|API_KEY|CLIENT_SECRET|WEBHOOK_SECRET))=" $ROOT/file-backed/*.env && ! grep -qE "://[^/@]*:[^/@]*@" $ROOT/file-backed/*.env'
sec provision
check "provisioning never overwrites" 'says "never overwritten"'
f=$ROOT/file-backed/secrets/app/stripe_secret_key
chmod 0444 $f; sec verify
check "a world-readable secret is refused" 'says "has mode 0444"'
chmod 0440 $f; cp -p $f "$WORK/saved"; echo changed >$f; sec verify
check "a changed secret is detected" 'says "stripe_secret_key: differs from the F-03 credential"'
cp -p "$WORK/saved" $f; sec verify
must "the restored files verify" 'says "equals the F-03 values and validates"'
cp -p $ROOT/api.env "$WORK/api.env"; echo 'MYKHAYA_SESSION_MINUTES=99' >>$ROOT/api.env; sec check
check "drift between the F-03 files and the running stack is refused" 'says "FAILED"'
cp -p "$WORK/api.env" $ROOT/api.env; rm "$WORK/api.env"
PHRASES=$SECRETS apply
check "a configuration backup without the F-03 files is refused" 'says "does not hold the F-03 service files"'
sec backup-config
CONFIG=$(sed -n 's#^Encrypted configuration backup: .*/##p' "$WORK/out")
# Valid in every way except that it is not the F-03 value.
v=$(cat $f); printf '%s
' "${v%?}~" >$f; unset v; PHRASES=$SECRETS apply
check "apply refuses credentials that are not equivalent" 'says "do not equal the F-03 values" && [ "$(state .secrets-state)" = absent ]'
cp -p "$WORK/saved" $f; rm "$WORK/saved"; sec verify
must "the original credential verifies again" 'says "equals the F-03 values and validates"'
as_deploy MYKHAYA_PROD_SECRETS_CUTOVER=1 MYKHAYA_PROD_SERVICE_ENV_CUTOVER=1 sh infrastructure/scripts/prod-deploy.sh update
check "contradictory deployment flags are refused" 'says "ERROR"  && [ "$(state .secrets-state)" = absent ]'
as_deploy sh infrastructure/scripts/prod-security-migrate.sh rollback-check --expect-host "$HOST"
check "rollback-check from F-03 offers legacy" 'says "Rollback possible from f03-active"'

echo "== 5. Stage 2: interruptions, resume and rollback"
F03_IDS=$(ids postgres redis web caddy api worker scheduler)
PHRASES="MIGRATE DEV\n" apply
check "the wrong phrase changes nothing" 'says "Not approved" && [ "$(state .secrets-state)" = absent ]'
PHRASES=$SECRETS apply FAIL_ON="up -d --no-build --no-deps --wait postgres"
check "failure before any container replacement: pending, nothing replaced" \
  '[ "$(state .secrets-state)" = pending ] && [ "$(ids postgres redis web caddy api worker scheduler)" = "$F03_IDS" ] && ready'
sec accept
check "accept refuses an unverified migration" 'says "nothing has completed to accept"'
as_deploy MYKHAYA_PROD_REUSE_IMAGES=1 sh infrastructure/scripts/prod-deploy.sh update
check "an ordinary update is refused while pending" 'says "Docker Secrets migration is pending"'
as_deploy MYKHAYA_PROD_LEGACY_ENV_ROLLBACK=1 MYKHAYA_PROD_REUSE_IMAGES=1 sh infrastructure/scripts/prod-deploy.sh update
check "a direct legacy rollback is refused while pending" 'says "roll them back with prod-security-migrate.sh rollback"'
as_deploy sh infrastructure/scripts/prod-service-env-migrate.sh --apply --expect-host "$HOST"
check "the F-03 tool refuses once Docker Secrets started" 'says "use prod-security-migrate.sh"'
as_deploy sh infrastructure/scripts/backup.sh
check "backup works during an interrupted migration" 'says .sql.gz.age'
MANIFEST=$(basename "$(ls /srv/backups/*.manifest | tail -n 1)")
PHRASES=$SECRETS apply FAIL_ON="run --rm --no-deps -T migrate"
check "failure after PostgreSQL, before the application: still pending, application still running" \
  '[ "$(state .secrets-state)" = pending ] && [ "$(ids api)" = "$(sed -n 5p <<<"$F03_IDS")" ] && ready'
# As a lost database connection can: the restart policy restarts it once.
kill -9 "$(docker inspect --format "{{.State.Pid}}" "$(cid scheduler)")"; sleep 8
must "a service restarted during the interruption" '[ "$(docker inspect --format "{{.RestartCount}}" "$(cid scheduler)")" -ge 1 ]'
PHRASES="ROLL BACK PROD SECRETS\n" sec rollback
must "rollback from pending" 'says "Rolled back to the F-03 configuration" && [ "$(state .secrets-state)" = legacy ] && ready'
PHRASES=$SECRETS apply FAIL_ON="ps --status running"
check "failure after container replacement leaves pending" '[ "$(state .secrets-state)" = pending ] && [ "$(docker exec "$(cid api)" printenv MYKHAYA_PROCESS_ROLE)" = api ]'
docker stop -t 2 "$(cid worker)" >/dev/null
PHRASES=$SECRETS apply
must "the migration resumes, even with a stopped service, and completes" 'says "Docker Secrets are active and verified" && [ "$(state .secrets-state)" = active ]'
check "only postgres, api, worker and scheduler were replaced" '[ "$(ids redis web caddy)" = "$(sed -n 2,4p <<<"$F03_IDS")" ]'

echo "== 6. Docker Secrets active"
sec accept
must "independent acceptance" 'says "Automatic acceptance passed" && says "none found"'
sec check
check "check on a finished migration repeats acceptance" 'says "Automatic acceptance passed"'
for s in api worker scheduler; do
  check "$s runs with its role" '[ "$(docker exec "$(cid $s)" printenv MYKHAYA_PROCESS_ROLE)" = $s ]'
done
check "secrets are mounted per service" \
  '[ "$(docker exec "$(cid worker)" sh -c "ls /run/secrets" | tr "\n" " ")" = "apns_private_key app_db_password fcm_private_key mykhaya secret_key smtp_password vapid_private_key " ]'
py api >"$WORK/out" 2>&1 <<'PY'
from mykhaya.config import get_settings
from mykhaya.notifications.push import fcm_indicated
s = get_settings()
assert s.environment == "production" and s.fcm_private_key is None and not s.apns_private_key
assert fcm_indicated(s) and s.dvla_configured and s.dvsa_configured
assert s.google_client_secret and s.stripe_secret_key and s.stripe_webhook_secret
assert s.apple_private_key and s.vapid_private_key
assert s.smtp_password.get_secret_value().endswith(' p@ss:w/rd%20?#&=+;"\\ $(id) é')
print("OK")
PY
check "api: providers configured, FCM indicated without the key" 'says OK'
py scheduler >"$WORK/out" 2>&1 <<'PY'
from mykhaya.config import get_settings
s = get_settings()
assert s.dvla_configured and s.dvsa_configured and s.stripe_secret_key and s.stripe_webhook_secret_present
assert s.dvla_production_api_key is None and s.dvsa_client_secret is None and s.stripe_webhook_secret is None
assert s.monitoring_watchdog_url
print("OK")
PY
check "scheduler: presence flags, no provider credentials" 'says OK'
py worker >"$WORK/out" 2>&1 <<'PY'
from mykhaya.config import get_settings
from mykhaya.notifications.push import _build_apns_bearer, resolve_apns_config, resolve_fcm_config
s = get_settings()
assert resolve_fcm_config(s).configured and resolve_apns_config(s).configured
assert _build_apns_bearer(resolve_apns_config(s))
print("OK")
PY
check "worker: APNs and FCM keys load" 'says OK'
{ echo "ENVELOPE = '$(tail -n 1 "$WORK/envelope")'"; cat <<'PY'
import uuid
from mykhaya.crypto import decrypt_sensitive_value
from mykhaya.crypto.config import get_field_keyring
from mykhaya.driveway_sensitive import vin_binding
assert decrypt_sensitive_value(ENVELOPE, binding=vin_binding(uuid.UUID(int=7)), keyring=get_field_keyring()) == "SYNTHETICVIN"
print("OK")
PY
} >"$WORK/decrypt.py"
py api <"$WORK/decrypt.py" >"$WORK/out" 2>&1
check "field-encrypted data from before the migration decrypts" 'says OK'
docker exec "$(cid api)" python -m mykhaya.tools.encrypted_secrets_check >"$WORK/out" 2>&1
check "application-key encrypted data decrypts" 'says "\"docs_sync_token_readable\": 1" && says "\"docs_sync_token_failed\": 0"'
check "same database cluster, not re-initialised" '[ "$(sql "select system_identifier from pg_control_system()")" = "$DB" ]'
check "every volume is the original" '[ "$(volumes)" = "$VOLUMES" ]'
check "the mislabelled volume kept its content" '[ "$(docker run --rm -v mykhaya_legal_evidence_data:/v postgres:17.5-alpine3.22 cat /v/marker)" = kept ]'
check "Home Migration packages are unchanged" '[ "$(sql "$PACKAGES")" = "$PACKAGES_SUM" ]'
cat $ROOT/file-backed/secrets/app/{secret_key,app_db_password,migration_db_password,stripe_secret_key,smtp_password,dvsa_api_key} \
  $ROOT/file-backed/secrets/postgres/* >"$WORK/needles"
docker ps -aq | xargs docker inspect >"$WORK/inspect"
check "no credential in any container metadata, running or stopped" '! grep -qFf "$WORK/needles" "$WORK/inspect"'
docker exec "$(cid api)" cat /proc/1/environ | tr '\000' '\n' >"$WORK/environ"
check "no credential in the api process environment" 'grep -q ^MYKHAYA_PROCESS_ROLE=api "$WORK/environ" && ! grep -qFf "$WORK/needles" "$WORK/environ"'
check "no credential in any report, baseline or state file" '! grep -rqFf "$WORK/needles" /var/lib/mykhaya/migration-reports $ROOT/.secrets-snapshot.json $ROOT/.cutover-snapshot.json $ROOT/.secrets-state'
rm "$WORK/needles" "$WORK/inspect" "$WORK/environ"
as_deploy MYKHAYA_PROD_SECRETS=0 sh infrastructure/scripts/prod-deploy.sh state
check "the protected state selects the mode, not the shell" 'says "Configuration mode: secrets"'
as_deploy MYKHAYA_PROD_REUSE_IMAGES=1 sh infrastructure/scripts/prod-deploy.sh update
check "a routine update stays on Docker Secrets" 'says "Configuration mode: secrets" && says "Deployed release" && [ "$(state .secrets-state)" = active ]'
as_deploy sh infrastructure/scripts/backup.sh
check "backup works with secrets active" 'says .sql.gz.age'
MANIFEST=$(basename "$(ls /srv/backups/*.manifest | tail -n 1)")
DUMP=$(ls /srv/backups/*.sql.gz.age | tail -n 1)
as_deploy sh infrastructure/scripts/billing-readiness.sh
check "billing readiness runs with secrets active" '! says "Traceback" && says "PASS"'
docker run -d --name leak --label com.docker.compose.project=mykhaya --label com.docker.compose.service=leak \
  -e "X=$(cat $ROOT/file-backed/secrets/app/secret_key)" postgres:17.5-alpine3.22 sleep 600 >/dev/null
sec accept
check "acceptance catches a leaked secret" 'says "leak: secret_key appears in Docker metadata"'
docker rm -f leak >/dev/null

echo "== 7. Isolated restore and migration"
R=/srv/restore
cp -a $REPO $R && chown -R deploy:deploy $R
for s in api migrate; do docker tag mykhaya-$s restore-$s; done
iso() { sudo -u deploy env PATH=/usr/local/bin:/usr/bin:/bin HOME=/home/deploy COMPOSE_PROJECT_NAME=restore sh -c "cd $R && exec env \"\$@\"" sh "$@" >"$WORK/out" 2>&1; }
isql() { docker exec "$(docker ps -q --filter label=com.docker.compose.project=restore --filter label=com.docker.compose.service=postgres)" psql -U postgres -d mykhaya -Atc "$1"; }
iso docker compose -f compose.yml up -d --no-build --wait postgres
cp "$WORK/identity.txt" /home/deploy/identity.txt && chown deploy /home/deploy/identity.txt
for dump in "$LEGACY_DUMP" "$DUMP"; do
  kind=$([ "$dump" = "$DUMP" ] && echo "Docker Secrets" || echo legacy)
  iso COMPOSE_FILE=compose.yml MYKHAYA_BACKUP_AGE_IDENTITY=/home/deploy/identity.txt sh infrastructure/scripts/restore.sh "$dump"
  must "a $kind PROD backup restores with ownership and grants verified" 'says "ownership and grants verified"'
  check "restored tables belong to the migration role" '[ "$(isql "select count(*) from pg_tables where schemaname = \$\$public\$\$ and tableowner <> \$\$mykhaya_migrator\$\$")" = 0 ]'
  iso docker compose -f compose.yml run --rm --no-deps -T migrate sh -c "alembic downgrade -1 && alembic upgrade head"
  check "the next Alembic migration works on the $kind restore" '[ $? -eq 0 ] && says "Running upgrade"'
  check "the runtime role can use the restored data" 'isql "set role mykhaya_app; select count(*) from users" >/dev/null 2>&1'
done
isql "alter table users owner to postgres" >/dev/null
iso COMPOSE_FILE=compose.yml MYKHAYA_BACKUP_AGE_IDENTITY=/home/deploy/identity.txt sh infrastructure/scripts/restore.sh "$DUMP"
check "a restore corrects ownership left by an earlier --no-owner restore" 'says "ownership and grants verified"'
isql "alter role mykhaya_app rename to renamed_app" >/dev/null
iso COMPOSE_FILE=compose.yml MYKHAYA_BACKUP_AGE_IDENTITY=/home/deploy/identity.txt sh infrastructure/scripts/restore.sh "$DUMP"
check "a target without the MyKhaya roles is refused before any change" 'says "Nothing was changed" && [ "$(isql "select count(*) from alembic_version")" = 1 ]'
iso docker compose -f compose.yml stop

echo "== 8. Deliberate rollback to legacy, and one-command migration"
PHRASES="no\n" sec rollback
check "an unapproved rollback changes nothing" 'says "Not approved" && [ "$(state .secrets-state)" = active ]'
PHRASES="ROLL BACK PROD SECRETS\n" sec FAIL_ON="run --rm --no-deps -T migrate" rollback
check "an interrupted rollback is rollback-pending" '[ "$(state .secrets-state)" = rollback-pending ]'
mv $ROOT/.secrets-snapshot.json $WORK/ && sec rollback-check
check "a missing baseline does not strand a rollback" 'says "baseline recorded before the cutover is missing" && says "Rollback possible"'
mv $WORK/.secrets-snapshot.json $ROOT/
PHRASES="ROLL BACK PROD SECRETS\n" sec rollback
must "the rollback resumes" 'says "Rolled back to the F-03" && ready && [ "$(state .secrets-state)" = legacy ]'
check "F-03 files never changed" '[ "$F03_ENV" = "$(cat $ROOT/*.env | sha256sum)" ]'
py api <"$WORK/decrypt.py" >"$WORK/out" 2>&1
check "encrypted data decrypts after rollback" 'says OK'
PHRASES="ROLL BACK PROD TO LEGACY\n" sec rollback
must "F-03 rolls back to legacy" 'says "Rolled back to the legacy configuration" && ready && [ "$(state .service-env-state)" = legacy ]'
sec backup-config
CONFIG=$(sed -n 's#^Encrypted configuration backup: .*/##p' "$WORK/out")
( while :; do ready || date +%s >>"$WORK/down"; sleep 1; done ) & poller=$!
PHRASES="$F03$SECRETS" apply
kill $poller
echo "API unavailable for about $(wc -l <"$WORK/down") one-second probes over both stages"
must "one apply goes from legacy to Docker Secrets with two approvals" 'says "Docker Secrets are active and verified" && ready'
sec accept
check "final acceptance" 'says "Automatic acceptance passed"'
check "the legacy .env and the keys never changed" '[ "$ENV_SUM" = "$(sha256sum <$REPO/.env)" ] && [ "$KEYS" = "$(cat /etc/mykhaya/keys/*/* | sha256sum)" ]'
check "every volume is still the original" '[ "$(volumes | grep -v probe)" = "$VOLUMES" ]'
check "same database cluster at the end" '[ "$(sql "select system_identifier from pg_control_system()")" = "$DB" ]'

echo
if [ "$FAILURES" -eq 0 ]; then echo "PROD security migration rehearsal: all $CHECKS checks passed"; else
  echo "PROD security migration rehearsal: $FAILURES of $CHECKS checks failed"; exit 1
fi
