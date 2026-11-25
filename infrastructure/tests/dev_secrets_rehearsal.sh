#!/bin/bash
# check evaluates its conditions, so variables and functions look unused.
# shellcheck disable=SC2034,SC2024,SC2033,SC2016
# The inside of check-dev-secrets-migration.sh. Only ever runs in its disposable
# nested Docker daemon, as root; the deployment steps run as a "deploy" account
# with Docker access. Every credential is synthetic and generated here.
set -uo pipefail
[ -f /.dockerenv ] && [ -d /srv/mykhaya ] && ! docker volume inspect mykhaya_postgres_data >/dev/null 2>&1 ||
  { echo "refusing to run outside the disposable rehearsal container" >&2; exit 1; }

REPO=/srv/mykhaya
ROOT=/etc/mykhaya/dev
WORK=/tmp/rehearsal
FAILURES=0
CHECKS=0
pass() { CHECKS=$((CHECKS + 1)); printf 'PASS  %s\n' "$1"; }
fail() {
  CHECKS=$((CHECKS + 1)); FAILURES=$((FAILURES + 1)); printf 'FAIL  %s\n' "$1"
  [ ! -s "$WORK/out" ] || tail -n "${2:-12}" "$WORK/out" | sed 's/^/      /'
}
# A step everything after it depends on: later checks would pass vacuously.
must() { check "$@"; [ "$FAILURES" -eq 0 ] || { echo "stopping: a required step failed"; exit 1; }; }
# Not "docker logs | grep -q": under pipefail that fails at random when grep exits
# first (SIGPIPE). Capture, then search.
log_has() { docker logs "$1" >"$WORK/container.log" 2>&1 && grep -q -- "$2" "$WORK/container.log"; }
check() { if eval "$2"; then pass "$1"; else fail "$1"; fi; }

mkdir -p "$WORK" && chmod 777 "$WORK"
addgroup -g 5000 deploy && adduser -D -u 5000 -G deploy -s /bin/bash deploy
sock_group=$(stat -c %G /var/run/docker.sock)
[ "$sock_group" != UNKNOWN ] || { addgroup -g "$(stat -c %g /var/run/docker.sock)" dockersock; sock_group=dockersock; }
addgroup deploy "$sock_group"
echo 'deploy ALL=(ALL) NOPASSWD: ALL' >/etc/sudoers.d/deploy

# Images are preloaded, so builds are skipped; FAIL_ON makes one deployment step
# fail, to rehearse interrupted cutovers. Everything else is the real CLI.
cat >/usr/local/sbin/docker <<'SH'
#!/bin/sh
case " $* " in *" compose "*" build "*) exit 0 ;; esac
if [ -n "${FAIL_ON:-}" ]; then case "$*" in *"$FAIL_ON"*) echo "simulated failure" >&2; exit 1 ;; esac; fi
exec /usr/local/bin/docker "$@"
SH
chmod 755 /usr/local/sbin/docker

run() { # VAR=value words, then a command, as the deployment account
  sudo -u deploy env PATH=/usr/local/sbin:/usr/local/bin:/usr/bin:/bin HOME=/home/deploy "$@" >"$WORK/out" 2>&1
}
deploy() { run sh -c "cd $REPO && exec \"\$@\"" sh "$@"; }
tool() { # action, with optional leading VAR=value words; the phrase comes from $PHRASE
  local vars=()
  while [[ "$1" == *=* ]]; do vars+=("$1"); shift; done
  printf '%s\n' "${PHRASE:-}" | sudo -u deploy env PATH=/usr/local/sbin:/usr/local/bin:/usr/bin:/bin HOME=/home/deploy \
    "${vars[@]}" sh -c "cd $REPO && exec sh infrastructure/scripts/dev-secrets-cutover.sh $1" >"$WORK/out" 2>&1
}
says() { grep -qF -- "$1" "$WORK/out"; }
cid() { docker ps -q --filter label=com.docker.compose.project=mykhaya --filter "label=com.docker.compose.service=$1"; }
py() { docker exec -i "$(cid "$1")" python - ; }
state() { sed -n 1p "$ROOT/$1" 2>/dev/null || echo absent; }
ready() { curl -fsS -H 'Host: localhost' http://127.0.0.1:8089/api/v1/health/ready >/dev/null 2>&1; }
ATTEST="MYKHAYA_DEV_ATTEST=backup-restored keys-escrowed"

# --- Synthetic credentials --------------------------------------------------------
install -d -o root -g 10001 -m 0750 /etc/mykhaya/keys/field /etc/mykhaya/keys/apple
docker run --rm -i --entrypoint python mykhaya-api - >"$WORK/generated.json" <<'PY'
import base64, json, secrets
from cryptography.hazmat.primitives import serialization as s
from cryptography.hazmat.primitives.asymmetric import ec, rsa

def pem(key):
    return key.private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption()).decode()

def ring(purpose):
    return json.dumps({"format": "mykhaya-keyring-v1", "purpose": purpose, "environment": "development",
                       "active": "d1", "keys": {"d1": base64.b64encode(secrets.token_bytes(32)).decode()}})

token = secrets.token_urlsafe
print(json.dumps({
    "apple": pem(ec.generate_private_key(ec.SECP256R1())),
    "apns": pem(ec.generate_private_key(ec.SECP256R1())),
    "fcm": pem(rsa.generate_private_key(65537, 2048)),
    "field": ring("field-encryption"), "blind": ring("blind-index"),
    "vapid": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="),
    "tokens": [token(32) for _ in range(16)],
}))
PY
python3 - "$WORK" <<'PY'
import json, sys
from pathlib import Path
work = Path(sys.argv[1])
g = json.loads((work / "generated.json").read_text())
Path("/etc/mykhaya/keys/field/field-encryption-keys.json").write_text(g["field"])
Path("/etc/mykhaya/keys/field/blind-index-keys.json").write_text(g["blind"])
Path("/etc/mykhaya/keys/apple/apple.p8").write_text(g["apple"])
t = g["tokens"]
escaped = lambda pem: pem.strip().replace("\n", "\\n")
env = {
    "SECRET_KEY": t[0], "POSTGRES_ADMIN_PASSWORD": t[1], "MIGRATION_DB_PASSWORD": t[2], "DB_PASSWORD": t[3],
    "REDIS_URL": "redis://redis:6379/0", "ADMIN_ALLOWED_NETWORKS": '["100.64.0.10/32"]',
    "ADMIN_MFA_REQUIRED": "true", "DEV_BIND_ADDRESS": "127.0.0.1", "DEV_HOST_PORT": "8089",
    "FIELD_KEYS_HOST_DIR": "/etc/mykhaya/keys/field", "APPLE_KEY_HOST_DIR": "/etc/mykhaya/keys/apple",
    "SENSITIVE_FIELD_KEYS_REQUIRED": "true", "MONITORING_ENABLED": "true",
    "SMTP_HOST": "mailpit", "SMTP_PORT": "1025", "SMTP_USERNAME": "",
    # Hostile on purpose; single quotes keep it literal in a dotenv file.
    "SMTP_PASSWORD": "'" + t[4] + ' p@ss:w/rd%20?#&=+;"\\ $(id) é' + "'",
    "EMAIL_DELIVERY_CONFIGURED": "true", "EMAIL_FROM": "MyKhaya <synthetic@dev.mykhaya.app>",
    "VAPID_PUBLIC_KEY": "synthetic-public", "VAPID_PRIVATE_KEY": g["vapid"],
    "VAPID_SUBJECT": "mailto:synthetic@dev.mykhaya.app", "PUSH_DELIVERY_CONFIGURED": "true",
    "APNS_DELIVERY_CONFIGURED": "true", "APNS_TEAM_ID": "SYNTHETIC1", "APNS_KEY_ID": "SYNTHETIC2",
    "APNS_BUNDLE_ID": "app.mykhaya.mobile", "APNS_PRIVATE_KEY": '"' + g["apns"].strip() + '"',
    "FCM_DELIVERY_CONFIGURED": "true", "FCM_PROJECT_ID": "mykhaya-dev-faf55",
    "FCM_CLIENT_EMAIL": "synthetic@example.invalid", "FCM_PRIVATE_KEY": escaped(g["fcm"]),
    "APPLE_SIGN_IN_ENABLED": "true", "APPLE_CLIENT_ID": "synthetic", "APPLE_SERVICE_ID": "synthetic",
    "APPLE_TEAM_ID": "SYNTHETIC1", "APPLE_KEY_ID": "SYNTHETIC3",
    "APPLE_PRIVATE_KEY_FILE": "/run/secrets/mykhaya-apple/apple.p8",
    "GOOGLE_SIGN_IN_ENABLED": "true", "GOOGLE_CLIENT_ID": "synthetic", "GOOGLE_CLIENT_SECRET": t[5],
    "STRIPE_BILLING_CONFIGURED": "true", "STRIPE_SECRET_KEY": "sk_" + "test_" + t[6],
    "STRIPE_WEBHOOK_SECRET": "whsec_" + t[7], "STRIPE_FAMILY_MONTHLY_PRICE_ID": "price_m",
    "STRIPE_FAMILY_ANNUAL_PRICE_ID": "price_a",
    "DVLA_ENVIRONMENT": "uat", "DVLA_UAT_ENDPOINT": "https://uat.example.invalid", "DVLA_UAT_API_KEY": t[8],
    "DVSA_ENABLED": "true", "DVSA_ENVIRONMENT": "development", "DVSA_CLIENT_ID": t[9], "DVSA_CLIENT_SECRET": t[10],
    "DVSA_API_KEY": t[11], "DVSA_TOKEN_URL": "https://login.microsoftonline.com/synthetic/oauth2/v2.0/token",
    "MONITORING_WATCHDOG_URL": "https://watchdog.example.invalid/" + t[12],
    "BACKUP_DIR": "/srv/backups", "BACKUP_AGE_RECIPIENTS_FILE": "/etc/mykhaya/backup-recipients.txt",
}
Path("/srv/mykhaya/.env").write_text("".join(f"MYKHAYA_{k}={v}\n" for k, v in env.items()))
PY
chown root:10001 /etc/mykhaya/keys/*/* && chmod 755 /etc/mykhaya/keys && chmod 0440 /etc/mykhaya/keys/*/*
install -d -o deploy -g deploy -m 0700 /srv/backups
age-keygen -o "$WORK/identity.txt" 2>/dev/null && age-keygen -y "$WORK/identity.txt" >/etc/mykhaya/backup-recipients.txt
chmod 755 /etc/mykhaya && chmod 644 /etc/mykhaya/backup-recipients.txt
chown -R deploy:deploy "$REPO" && chmod 600 "$REPO/.env"
sudo -u deploy git -C "$REPO" init -q -b dev
sudo -u deploy git -C "$REPO" add -A
sudo -u deploy git -C "$REPO" -c user.email=t@example.invalid -c user.name=t commit -q -m rehearsal

echo "== 1. Legacy DEV configuration"
deploy docker compose -f compose.yml -f compose.dev.yml up --no-start --no-build
deploy sh infrastructure/scripts/dev-deploy.sh up
must "legacy deployment succeeds" 'says "Development deployment succeeded"'
py api >"$WORK/envelope" <<'PY'
import asyncio
from mykhaya.config import get_settings
from mykhaya.crypto import encrypt_sensitive_value
from mykhaya.crypto.config import get_field_keyring
from mykhaya.db import SessionFactory
from mykhaya.driveway_sensitive import vin_binding
from mykhaya.secrets_crypto import encrypt_secret
from sqlalchemy import text
import uuid

async def seed():
    s = get_settings()
    async with SessionFactory() as db:
        await db.execute(text("insert into platform_settings (id, key, value, created_at, updated_at) values "
            "(gen_random_uuid(), 'bookstack_sync', cast(:v as json), now(), now())"),
            {"v": __import__("json").dumps({"value": {"token_secret_encrypted": encrypt_secret(s, "doc-secret", info=b"mykhaya-bookstack-token-v1")}})})
        await db.commit()
asyncio.run(seed())
print(encrypt_sensitive_value("SYNTHETICVIN", binding=vin_binding(uuid.UUID(int=7)), keyring=get_field_keyring()))
PY
must "encrypted test data written" '[ -s "$WORK/envelope" ]'
deploy env MYKHAYA_DEV_SECRETS=1 sh infrastructure/scripts/dev-deploy.sh up
check "Docker Secrets refused without F-03" 'says "needs MYKHAYA_DEV_CONFIG_ROOT"'
tool "$ATTEST" cutover
check "cutover refused before F-03" 'says "not active"'

echo "== 2. F-03 per-service configuration"
install -d -o deploy -g deploy -m 0750 "$ROOT"
deploy sh infrastructure/scripts/dev-deploy.sh state-init
deploy python3 infrastructure/scripts/service_env_contract.py --split-legacy-env .env --out "$ROOT"
check "legacy configuration splits" 'says "Wrote 7 files"'
deploy env MYKHAYA_DEV_CONFIG_ROOT=$ROOT sh infrastructure/scripts/dev-deploy.sh config-check
check "F-03 configuration validates" 'says "configuration check passed"'
deploy env MYKHAYA_DEV_CONFIG_ROOT=$ROOT sh infrastructure/scripts/dev-deploy.sh up
must "F-03 cutover succeeds" '[ "$(state .service-env-state)" = active ] && ready'
docker compose version
F03_ENV=$(cat "$ROOT"/*.env | sha256sum)
KEYS=$(cat /etc/mykhaya/keys/*/* | sha256sum)

echo "== 3. Backup tooling and prerequisites"
tool check
check "check refuses without a recent backup" 'says "no backup from the last 24 hours"'
deploy sh infrastructure/scripts/backup.sh
check "mode-aware backup succeeds in F-03 mode" 'ls /srv/backups/*.manifest >/dev/null 2>&1 && grep -q encryption=age /srv/backups/*.manifest'
tool check
must "all prerequisites pass" 'says "All automatic prerequisites passed"'
packages() { docker exec "$(cid postgres)" psql -q -v ON_ERROR_STOP=1 -U postgres -d mykhaya -Atc "$1"; }
add_packages() { # count, status, completed_at expression
  packages "insert into home_migration_packages (id, migration_id, package_checksum, storage_key, source_home_id,
    summary, status, created_by, created_at, completed_at) select gen_random_uuid(), gen_random_uuid(), 'synthetic',
    gen_random_uuid()::text, gen_random_uuid(), '{}', '$2', gen_random_uuid(), now(), $3 from generate_series(1, $1)"
}
add_packages 18 expired null && add_packages 1 discarded null && add_packages 1 completed 'now()'
must "finished synthetic packages written" '[ "$(packages "select count(*) from home_migration_packages")" = 20 ]'
ALL_PACKAGES="select md5(string_agg(p::text, chr(10) order by id)) from home_migration_packages p"
before=$(packages "$ALL_PACKAGES")
tool check
check "expired, discarded and completed packages do not block" 'says "All automatic prerequisites passed"'
check "the check changes no package" '[ -n "$before" ] && [ "$(packages "$ALL_PACKAGES")" = "$before" ]'
for row in uploaded:null READY_TO_IMPORT:null importing:null failed:null unknown:null completed:null "expired:now()"; do
  add_packages 1 "${row%%:*}" "${row#*:}"
  tool check
  check "a package in state $row blocks" 'says "1 Home Migration packages are unresolved"'
  packages "delete from home_migration_packages where id = (
    select id from home_migration_packages order by created_at desc limit 1)"
done
packages "delete from home_migration_packages"
tool COMPOSE_PROJECT_NAME=other check
check "a different Compose project is refused" 'says "COMPOSE_PROJECT_NAME is set"'
tool cutover
check "cutover refuses without attestation" 'says "MYKHAYA_DEV_ATTEST"'
tool "$ATTEST" cutover
check "cutover refuses without provisioned secrets" 'says "provision the file-backed configuration first"'
deploy env MYKHAYA_DEV_CONFIG_ROOT=$ROOT MYKHAYA_DEV_SECRETS=1 sh infrastructure/scripts/dev-deploy.sh up
check "the deploy script alone cannot start the cutover" 'says "start the Docker Secrets cutover with"'

echo "== 4. Provisioning"
tool provision
must "provisioning succeeds" 'says "Provisioned" && says "ownership, modes and per-service grants validate"'
check "secret files are root-owned 0440 with the right groups" \
  '[ "$(stat -c "%U:%g:%a" $ROOT/file-backed/secrets/app/* | sort -u)" = root:10001:440 ] && [ "$(stat -c "%U:%g:%a" $ROOT/file-backed/secrets/postgres/* | sort -u)" = root:70:440 ]'
check "the deployment account cannot read a secret" '! sudo -u deploy cat $ROOT/file-backed/secrets/app/secret_key >/dev/null 2>&1'
check "no credential remains in the file-backed env files" \
  '! grep -qE "^(MYKHAYA_SECRET_KEY|MYKHAYA_[A-Z_]*PASSWORD|MYKHAYA_[A-Z_]*(PRIVATE_KEY|API_KEY|CLIENT_SECRET|WEBHOOK_SECRET))=" $ROOT/file-backed/*.env && ! grep -qE "://[^/@]*:[^/@]*@" $ROOT/file-backed/*.env'
tool provision
check "provisioning never overwrites" 'says "never overwritten"'
f=$ROOT/file-backed/secrets/app/stripe_secret_key
chmod 0444 $f; tool verify
check "a world-readable secret is refused" 'says "does not validate"'
chmod 0440 $f; cp -p $f "$WORK/saved"; echo changed >$f; tool verify
check "a changed secret is detected" 'says "stripe_secret_key: differs from the F-03 credential"'
cp -p "$WORK/saved" $f
mv $f $f.real; ln -s $f.real $f; tool verify
check "a symbolic link is refused" 'says "not a regular file"'
rm $f; mv $f.real $f; touch $ROOT/file-backed/secrets/app/extra; tool verify
check "an unknown secret file is refused" 'says "does not validate"'
rm $ROOT/file-backed/secrets/app/extra; tool verify
check "the restored files verify" 'says "grants validate"'

echo "== 5. Failed cutovers and rollback"
before=$(cid api)
PHRASE="no" tool "$ATTEST" cutover
check "an unapproved cutover changes nothing" 'says "not approved" && [ "$(state .secrets-state)" = absent ] && [ "$(cid api)" = "$before" ]'
PHRASE="MIGRATE DEV" tool "$ATTEST" FAIL_ON="run --rm --no-deps migrate" cutover
check "a failed migration leaves pending and the old application running" \
  '[ "$(state .secrets-state)" = pending ] && [ "$(cid api)" = "$before" ] && ready'
deploy env MYKHAYA_DEV_CONFIG_ROOT=$ROOT sh infrastructure/scripts/dev-deploy.sh up
check "an implicit return to F-03 is refused while pending" 'says "Docker Secrets are pending"'
deploy env MYKHAYA_DEV_LEGACY_ENV_ROLLBACK=1 sh infrastructure/scripts/dev-deploy.sh up
check "a legacy rollback is refused while pending" 'says "roll them back to the F-03 configuration first"'
deploy sh infrastructure/scripts/backup.sh
check "backup works during an interrupted cutover" 'says ".sql.gz.age"'
PHRASE="ROLL BACK DEV" tool rollback
check "rollback after a failed migration" 'says "Rollback complete" && [ "$(state .secrets-state)" = legacy ] && ready'
PHRASE="MIGRATE DEV" tool "$ATTEST" FAIL_ON="up -d --no-build --no-deps web" cutover
check "a failure after the application started leaves pending" '[ "$(state .secrets-state)" = pending ]'
PHRASE="MIGRATE DEV" tool "$ATTEST" cutover
must "rerunning the cutover resumes and completes" 'says "Automatic acceptance passed" && [ "$(state .secrets-state)" = active ]'

echo "== 6. File-backed secrets active"
check "readiness" 'ready'
for s in api worker scheduler; do
  check "$s runs with its role" '[ "$(docker exec "$(cid $s)" printenv MYKHAYA_PROCESS_ROLE)" = $s ]'
done
check "secrets are mounted per service" \
  '[ "$(docker exec "$(cid worker)" sh -c "ls /run/secrets" | tr "\n" " ")" = "apns_private_key app_db_password fcm_private_key mykhaya secret_key smtp_password vapid_private_key " ]'
check "the worker cannot see Stripe or Apple" '! docker exec "$(cid worker)" ls /run/secrets/stripe_secret_key /run/secrets/mykhaya-apple >/dev/null 2>&1'
check "secret mounts are read-only" '! docker exec "$(cid api)" sh -c "echo x >/run/secrets/secret_key" 2>/dev/null'
py api >"$WORK/out" 2>&1 <<'PY'
from mykhaya.config import get_settings
from mykhaya.notifications.push import fcm_indicated
s = get_settings()
assert s.fcm_private_key is None and not s.apns_private_key
assert fcm_indicated(s) and s.dvla_configured and s.dvsa_configured
assert s.google_client_secret and s.stripe_secret_key and s.stripe_webhook_secret
assert s.apple_private_key and s.vapid_private_key and s.smtp_password
assert s.smtp_password.get_secret_value().endswith(' p@ss:w/rd%20?#&=+;"\\ $(id) é')
print("OK")
PY
check "api: providers configured, FCM indicated without the key" 'says OK'
py scheduler >"$WORK/out" 2>&1 <<'PY'
from mykhaya.config import get_settings
s = get_settings()
assert s.dvla_configured and s.dvsa_configured and s.stripe_secret_key and s.stripe_webhook_secret_present
assert s.dvla_uat_api_key is None and s.dvsa_client_secret is None and s.stripe_webhook_secret is None
assert s.monitoring_watchdog_url
print("OK")
PY
check "scheduler: monitoring from presence flags, no provider credentials" 'says OK'
py worker >"$WORK/out" 2>&1 <<'PY'
from mykhaya.config import get_settings
from mykhaya.notifications.push import _build_apns_bearer, resolve_apns_config, resolve_fcm_config
from cryptography.hazmat.primitives.serialization import load_pem_private_key
s = get_settings()
assert resolve_fcm_config(s).configured and resolve_apns_config(s).configured
assert _build_apns_bearer(resolve_apns_config(s))
load_pem_private_key(s.fcm_private_key.get_secret_value().encode(), None)
print("OK")
PY
check "worker: APNs and FCM keys load and sign" 'says OK'
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
docker exec "$(cid scheduler)" python -m mykhaya.monitoring.probe http://api:8000/api/v1/health/ready --expect-json status=ready >"$WORK/out" 2>&1
check "scheduler monitoring probe reaches the api" '[ $? -eq 0 ]'
docker exec "$(cid api)" cat /proc/1/environ | tr '\000' '\n' >"$WORK/environ"
check "api process environment holds no secret file value" \
  'grep -q ^MYKHAYA_PROCESS_ROLE=api "$WORK/environ" && ! grep -qFf <(cat $ROOT/file-backed/secrets/app/{secret_key,app_db_password,stripe_secret_key,smtp_password}) "$WORK/environ"'
check "postgres skipped initialisation" 'log_has "$(cid postgres)" "Skipping initialization"'
docker run --rm --network none -e MYKHAYA_PROCESS_ROLE=migrate -e MYKHAYA_SECRET_KEY="$(openssl rand -hex 32)" \
  -e MYKHAYA_DATABASE_URL=postgresql+asyncpg://mykhaya_migrator:x@postgres/mykhaya mykhaya-migrate alembic current >"$WORK/out" 2>&1
check "the migrate role refuses the application key" 'says "must not receive MYKHAYA_SECRET_KEY (K-01)"'
deploy env MYKHAYA_DEV_CONFIG_ROOT=$ROOT MYKHAYA_DEV_SECRETS=1 sh infrastructure/scripts/dev-deploy.sh up
check "a routine deployment stays active" 'says "Development deployment succeeded" && [ "$(state .secrets-state)" = active ]'
deploy env MYKHAYA_DEV_CONFIG_ROOT=$ROOT sh infrastructure/scripts/dev-deploy.sh up
check "forgetting the mode is refused" 'says "Docker Secrets are active"'
deploy sh infrastructure/scripts/backup.sh
check "backup works with secrets active" 'says ".sql.gz.age"'
latest=$(ls /srv/backups/*.sql.gz.age | tail -n 1)
deploy sh infrastructure/scripts/billing-readiness.sh
check "billing readiness runs with secrets active" 'says PASS && ! says "Traceback"'
tool accept
check "acceptance repeats cleanly" 'says "Automatic acceptance passed" && says "none found"'
docker run -d --name leak --label com.docker.compose.project=mykhaya --label com.docker.compose.service=leak \
  -e "X=$(cat $ROOT/file-backed/secrets/app/secret_key)" postgres:17.5-alpine3.22 sleep 600 >/dev/null
sudo python3 -I -B $REPO/infrastructure/scripts/dev_secrets_migration.py scan --root $ROOT >"$WORK/out" 2>&1
check "the exposure scan catches a leaked secret" 'says "leak: secret_key appears in Docker metadata"'
docker rm -f leak >/dev/null

echo "== 7. Rollback from active, restore and second cutover"
PHRASE="ROLL BACK DEV" tool rollback
must "rollback from active" 'says "Rollback complete" && ready && [ "$(state .secrets-state)" = legacy ]'
check "rollback restores the F-03 environment" '[ -z "$(docker exec "$(cid api)" printenv MYKHAYA_PROCESS_ROLE)" ]'
py api <"$WORK/decrypt.py" >"$WORK/out" 2>&1
check "encrypted data decrypts after rollback" 'says OK'
cp "$WORK/identity.txt" /home/deploy/identity.txt && chown deploy /home/deploy/identity.txt
deploy env MYKHAYA_BACKUP_AGE_IDENTITY=/home/deploy/identity.txt sh infrastructure/scripts/restore.sh "$latest"
must "the backup taken with secrets active restores" '! says ERROR && ! says error'
check "restored objects keep their owner" '[ "$(docker exec "$(cid postgres)" psql -U postgres -d mykhaya -Atc "select tableowner from pg_tables where tablename = \$\$alembic_version\$\$")" = mykhaya_migrator ]'
PHRASE="MIGRATE DEV" tool "$ATTEST" cutover
must "a second cutover succeeds" 'says "Automatic acceptance passed"'
check "F-03 files never changed" '[ "$F03_ENV" = "$(cat "$ROOT"/*.env | sha256sum)" ]'
check "key files never changed" '[ "$KEYS" = "$(cat /etc/mykhaya/keys/*/* | sha256sum)" ]'
check "no probe or stray volumes remain" 'volumes=$(docker volume ls -q) && ! grep -q config-probe <<<"$volumes"'
grep -qFf <(cat $ROOT/file-backed/secrets/app/{secret_key,app_db_password,migration_db_password}) <(docker logs "$(cid postgres)" 2>&1)
check "no password in the PostgreSQL log" '[ $? -ne 0 ]'
deploy env MYKHAYA_DEV_CONFIG_ROOT=$ROOT MYKHAYA_DEV_SECRETS=1 FAIL_ON="volume inspect mykhaya_postgres_data" sh infrastructure/scripts/dev-deploy.sh up
check "a missing database volume is refused, never created" 'says "refusing to initialise a new database"'

echo
if [ "$FAILURES" -eq 0 ]; then echo "DEV secrets migration rehearsal: all $CHECKS checks passed"; else
  echo "DEV secrets migration rehearsal: $FAILURES of $CHECKS checks failed"; exit 1
fi
