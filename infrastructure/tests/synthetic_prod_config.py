"""Synthetic PROD inputs for the F-03 production migration tests.

Every value is fabricated and recognisably synthetic; nothing is read from a
real .env, and no value is a real credential. The legacy production .env built
here exercises every provider group the PROD contract places (SMTP, Web Push,
APNs, FCM, Apple, Google, Stripe, DVLA, DVSA, monitoring), so the splitter and
the parity checks see a realistic shape.

    python infrastructure/tests/synthetic_prod_config.py OUTPUT_DIR
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SECRET_KEY = "synthetic-f03-prod-session-secret-0123456789abcdef"
ADMIN_PASSWORD = "synthetic-prod-postgres-admin-password"
MIGRATION_PASSWORD = "synthetic-prod-migration-password"
RUNTIME_PASSWORD = "synthetic-prod-runtime-password"
SECRET_VALUES = (SECRET_KEY, ADMIN_PASSWORD, MIGRATION_PASSWORD, RUNTIME_PASSWORD,
                 "synthetic-prod-smtp-password", "synthetic-prod-vapid-private",
                 "synthetic-prod-fcm-private", "synthetic-prod-google-secret",
                 "sk_live_synthetic", "whsec_synthetic0000000000",
                 "synthetic-prod-dvla-key", "synthetic-prod-dvsa-secret",
                 "synthetic-prod-dvsa-api-key", "synthetic-prod-apns-line-two")


def legacy_env(field_keys_dir: Path, apple_dir: Path, *, extra: str = "") -> str:
    """A legacy production root .env, shaped like .env.production.example."""
    return (
        "# Synthetic legacy PROD .env (tests only)\n"
        "MYKHAYA_ENVIRONMENT=production\n"
        "MYKHAYA_REGISTRATION_MODE=open\n"
        f"MYKHAYA_SECRET_KEY={SECRET_KEY}\n"
        f"MYKHAYA_POSTGRES_ADMIN_PASSWORD={ADMIN_PASSWORD}\n"
        f"MYKHAYA_MIGRATION_DB_PASSWORD={MIGRATION_PASSWORD}\n"
        f"MYKHAYA_DB_PASSWORD={RUNTIME_PASSWORD}\n"
        "MYKHAYA_REDIS_URL=redis://redis:6379/0\n"
        "MYKHAYA_PUBLIC_WEB_URL=https://synthetic.example.invalid\n"
        "MYKHAYA_ADMIN_URL=https://admin.synthetic.example.invalid\n"
        "MYKHAYA_STATUS_URL=https://status.synthetic.example.invalid\n"
        "MYKHAYA_NATIVE_API_URL=https://api.synthetic.example.invalid\n"
        'MYKHAYA_CORS_ORIGINS=["https://synthetic.example.invalid","https://admin.synthetic.example.invalid"]\n'
        'MYKHAYA_TRUSTED_HOSTS=["synthetic.example.invalid","api.synthetic.example.invalid",'
        '"admin.synthetic.example.invalid","status.synthetic.example.invalid","api","localhost",'
        '"127.0.0.1"]\n'
        'MYKHAYA_TRUSTED_PROXY_CIDRS=["100.64.0.0/10"]\n'
        "MYKHAYA_CADDY_TRUSTED_PROXY_CIDRS=100.64.0.0/10\n"
        'MYKHAYA_ADMIN_ALLOWED_NETWORKS=["192.0.2.10/32"]\n'
        "MYKHAYA_COOKIE_SECURE=true\n"
        "MYKHAYA_ADMIN_MFA_REQUIRED=true\n"
        "MYKHAYA_ADMIN_BOOTSTRAP_ENABLED=false\n"
        "MYKHAYA_DEFAULT_TIMEZONE=Europe/London\n"
        "MYKHAYA_DEFAULT_LOCALE=en-GB\n"
        "MYKHAYA_WEEK_START=monday\n"
        "MYKHAYA_APPLE_SIGN_IN_ENABLED=false\n"
        "MYKHAYA_APPLE_SERVICE_ID=\n"
        "MYKHAYA_APPLE_REDIRECT_URI=https://synthetic.example.invalid/api/v1/auth/apple/callback\n"
        "MYKHAYA_NATIVE_APPLE_RETURN_URI=app.mykhaya.mobile.prod://auth/callback\n"
        "MYKHAYA_GOOGLE_SIGN_IN_ENABLED=false\n"
        "MYKHAYA_GOOGLE_CLIENT_SECRET=synthetic-prod-google-secret\n"
        "MYKHAYA_GOOGLE_REDIRECT_URI=https://synthetic.example.invalid/api/v1/auth/google/callback\n"
        "MYKHAYA_EMAIL_DELIVERY_CONFIGURED=false\n"
        "MYKHAYA_EMAIL_VERIFICATION_ENABLED=true\n"
        "MYKHAYA_EMAIL_FROM=MyKhaya Synthetic <hello@synthetic.example.invalid>\n"
        "MYKHAYA_SMTP_HOST=smtp.synthetic.example.invalid\n"
        "MYKHAYA_SMTP_PORT=587\n"
        "MYKHAYA_SMTP_CONNECTION_SECURITY=starttls\n"
        "MYKHAYA_SMTP_USERNAME=synthetic-user\n"
        "MYKHAYA_SMTP_PASSWORD=synthetic-prod-smtp-password\n"
        "MYKHAYA_PUSH_DELIVERY_CONFIGURED=false\n"
        "MYKHAYA_VAPID_PRIVATE_KEY=synthetic-prod-vapid-private\n"
        "MYKHAYA_FCM_DELIVERY_CONFIGURED=false\n"
        "MYKHAYA_FCM_PROJECT_ID=mykhaya-prod\n"
        "MYKHAYA_FCM_CLIENT_EMAIL=synthetic@example.invalid\n"
        "MYKHAYA_FCM_PRIVATE_KEY=synthetic-prod-fcm-private\n"
        "MYKHAYA_APNS_DELIVERY_CONFIGURED=false\n"
        "MYKHAYA_APNS_TEAM_ID=SYNTHTEAM1\n"
        "MYKHAYA_APNS_KEY_ID=SYNTHKEY01\n"
        "MYKHAYA_APNS_BUNDLE_ID=app.mykhaya.mobile.prod\n"
        # Quoted multiline PEM-shaped value, as Compose reads it.
        'MYKHAYA_APNS_PRIVATE_KEY="-----BEGIN SYNTHETIC-----\n'
        "synthetic-prod-apns-line-two\n"
        '-----END SYNTHETIC-----"\n'
        "MYKHAYA_STRIPE_BILLING_CONFIGURED=false\n"
        "MYKHAYA_STRIPE_SECRET_KEY=sk_live_synthetic\n"
        "MYKHAYA_STRIPE_WEBHOOK_SECRET=whsec_synthetic0000000000\n"
        "MYKHAYA_STRIPE_BILLING_ACQUISITION_ENABLED=false\n"
        "MYKHAYA_STRIPE_ULTIMATE_ACQUISITION_ENABLED=false\n"
        "MYKHAYA_DVLA_ENVIRONMENT=production\n"
        "MYKHAYA_DVLA_PRODUCTION_ENDPOINT=https://dvla.synthetic.example.invalid/v1/vehicles\n"
        "MYKHAYA_DVLA_PRODUCTION_API_KEY=synthetic-prod-dvla-key\n"
        "MYKHAYA_DVLA_UAT_ENDPOINT=\n"
        "MYKHAYA_DVLA_UAT_API_KEY=\n"
        "MYKHAYA_DVSA_ENABLED=true\n"
        "MYKHAYA_DVSA_ENVIRONMENT=production\n"
        # Production Settings accept only Microsoft Entra ID token URLs.
        "MYKHAYA_DVSA_TOKEN_URL=https://login.microsoftonline.com/synthetic-tenant/oauth2/v2.0/token\n"
        "MYKHAYA_DVSA_CLIENT_ID=synthetic-dvsa-client\n"
        "MYKHAYA_DVSA_CLIENT_SECRET=synthetic-prod-dvsa-secret\n"
        "MYKHAYA_DVSA_API_KEY=synthetic-prod-dvsa-api-key\n"
        "MYKHAYA_MONITORING_ENABLED=true\n"
        "MYKHAYA_BACKUP_DIR=/var/lib/mykhaya/backups\n"
        "MYKHAYA_BACKUP_AGE_RECIPIENTS_FILE=/etc/mykhaya/backup-recipients.txt\n"
        f"MYKHAYA_FIELD_KEYS_HOST_DIR={field_keys_dir.as_posix()}\n"
        f"MYKHAYA_APPLE_KEY_HOST_DIR={apple_dir.as_posix()}\n"
        "MYKHAYA_SENSITIVE_FIELD_KEYS_REQUIRED=false\n"
        "MYKHAYA_DRIVEWAY_FIELD_ENCRYPTION_WRITE=false\n"
        "MYKHAYA_DRIVEWAY_FIELD_ENCRYPTION_READ=false\n"
        "MYKHAYA_HOME_MIGRATION_PACKAGE_TTL_HOURS=24\n"
        "MYKHAYA_PRODUCTION=1\n"
        "WEB_DOMAIN=synthetic.example.invalid\n"
        "API_DOMAIN=api.synthetic.example.invalid\n"
        "ADMIN_DOMAIN=admin.synthetic.example.invalid\n"
        "STATUS_DOMAIN=status.synthetic.example.invalid\n"
        + extra
    )


def write_layout(base: Path, *, provisioned: bool = True) -> tuple[Path, Path, Path, Path]:
    """Create base/{repo-env,prod,secrets/field-keys,secrets/apple}.

    Returns (legacy .env path, PROD config root, field-keys dir, apple dir).
    The config root is created empty (0700): the migration writes into it.
    """
    root = base / "prod"
    field_keys, apple = base / "secrets" / "field-keys", base / "secrets" / "apple"
    for directory in (root, field_keys, apple):
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
    if provisioned:
        for directory in (field_keys, apple):
            placeholder = directory / "synthetic-placeholder.txt"
            placeholder.write_text("synthetic placeholder, not key material\n", encoding="utf-8")
            os.chmod(placeholder, 0o600)
    env = base / "legacy.env"
    env.write_text(legacy_env(field_keys, apple), encoding="utf-8", newline="\n")
    os.chmod(env, 0o600)
    return env, root, field_keys, apple


if __name__ == "__main__":
    print(write_layout(Path(sys.argv[1])))
