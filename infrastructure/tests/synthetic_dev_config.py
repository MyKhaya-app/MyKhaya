"""Write a complete, valid, entirely synthetic DEV configuration root.

Used by the Stage 3A tests and local runtime verification. Every value is
fabricated; nothing is read from a real .env. Run directly to create a root:

    python infrastructure/tests/synthetic_dev_config.py OUTPUT_DIR
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SECRET_KEY = "synthetic-f03-dev-session-secret-0123456789abcdef"
ADMIN_PASSWORD = "synthetic-postgres-admin-password"
MIGRATION_PASSWORD = "synthetic-migration-password"
RUNTIME_PASSWORD = "synthetic-runtime-password"


def files(field_keys_dir: Path, apple_dir: Path) -> dict[str, str]:
    app_url = f"postgresql+asyncpg://mykhaya_app:{RUNTIME_PASSWORD}@postgres:5432/mykhaya"
    smtp = (
        "MYKHAYA_SMTP_HOST=mailpit\nMYKHAYA_SMTP_PORT=1025\nMYKHAYA_SMTP_USERNAME=\n"
        "MYKHAYA_SMTP_CONNECTION_SECURITY=none\nMYKHAYA_EMAIL_DELIVERY_CONFIGURED=true\n"
        "MYKHAYA_EMAIL_FROM=MyKhaya Synthetic <synthetic@dev.mykhaya.app>\n"
    )
    core = f"MYKHAYA_DATABASE_URL={app_url}\nMYKHAYA_REDIS_URL=redis://redis:6379/0\n" \
           f"MYKHAYA_SECRET_KEY={SECRET_KEY}\n"
    return {
        "compose.env": (
            "MYKHAYA_DEV_BIND_ADDRESS=127.0.0.1\nMYKHAYA_DEV_HOST_PORT=8089\n"
            "MYKHAYA_DEV_MAILPIT_PORT=8025\nMYKHAYA_DEV_PROXY_TRUSTED_CIDRS=100.64.0.0/10\n"
            'MYKHAYA_TRUSTED_PROXY_CIDRS=["10.77.0.250/32","10.77.1.250/32"]\n'
            'MYKHAYA_ADMIN_ALLOWED_NETWORKS=["100.64.0.10/32"]\n'
            "MYKHAYA_EMAIL_DELIVERY_CONFIGURED=true\n"
            f"MYKHAYA_FIELD_KEYS_HOST_DIR={field_keys_dir.as_posix()}\n"
            f"MYKHAYA_APPLE_KEY_HOST_DIR={apple_dir.as_posix()}\n"
        ),
        "common.env": (
            "MYKHAYA_MONITORING_ENABLED=true\nMYKHAYA_SENSITIVE_FIELD_KEYS_REQUIRED=false\n"
            "MYKHAYA_DRIVEWAY_FIELD_ENCRYPTION_WRITE=false\n"
            "MYKHAYA_DRIVEWAY_FIELD_ENCRYPTION_READ=false\n"
        ),
        "api.env": core + smtp + (
            "MYKHAYA_PUSH_DELIVERY_CONFIGURED=false\nMYKHAYA_FCM_DELIVERY_CONFIGURED=false\n"
            "MYKHAYA_APPLE_SIGN_IN_ENABLED=false\nMYKHAYA_GOOGLE_SIGN_IN_ENABLED=false\n"
            "MYKHAYA_STRIPE_BILLING_CONFIGURED=false\nMYKHAYA_DVLA_ENVIRONMENT=\n"
            "MYKHAYA_DVSA_ENABLED=false\nMYKHAYA_EMAIL_VERIFICATION_ENABLED=true\n"
        ),
        "worker.env": core + smtp + (
            "MYKHAYA_PUSH_DELIVERY_CONFIGURED=false\nMYKHAYA_FCM_DELIVERY_CONFIGURED=false\n"
            "MYKHAYA_APNS_DELIVERY_CONFIGURED=false\nMYKHAYA_APNS_BUNDLE_ID=app.mykhaya.mobile\n"
        ),
        "scheduler.env": core + smtp + (
            "MYKHAYA_MONITORING_WATCHDOG_URL=\n"
            "MYKHAYA_APPLE_SIGN_IN_ENABLED=false\nMYKHAYA_GOOGLE_SIGN_IN_ENABLED=false\n"
        ),
        "migrate.env": (
            "MYKHAYA_DATABASE_URL=postgresql+asyncpg://mykhaya_migrator:"
            f"{MIGRATION_PASSWORD}@postgres:5432/mykhaya\nMYKHAYA_SECRET_KEY={SECRET_KEY}\n"
        ),
        "postgres.env": (
            f"POSTGRES_PASSWORD={ADMIN_PASSWORD}\nMYKHAYA_MIGRATION_DB_PASSWORD={MIGRATION_PASSWORD}\n"
            f"MYKHAYA_DB_PASSWORD={RUNTIME_PASSWORD}\n"
        ),
    }


def write_synthetic_root(base: Path) -> Path:
    """Create base/config, base/secrets/{field-keys,apple}; return the config root."""
    root, field_keys, apple = base / "config", base / "secrets" / "field-keys", base / "secrets" / "apple"
    for directory in (root, field_keys, apple):
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
    for name, content in files(field_keys, apple).items():
        path = root / name
        path.write_text(content, encoding="utf-8", newline="\n")
        os.chmod(path, 0o600 if name not in {"compose.env", "common.env"} else 0o640)
    return root


if __name__ == "__main__":
    print(write_synthetic_root(Path(sys.argv[1])))
