"""Read-only check that stored secrets still decrypt with MYKHAYA_SECRET_KEY.

Covers every value encrypted by ``mykhaya.secrets_crypto``: consumer MFA, Home
join codes, administrator TOTP, SMTP, push and Stripe settings, and the
documentation-sync token. Prints **counts only**, never a value, row ID or
ciphertext, and never writes (PostgreSQL READ ONLY transaction, rolled back).

Run it before and after a configuration change that must preserve the
application key; the two outputs must be identical::

    docker compose exec -T api python -m mykhaya.tools.encrypted_secrets_check

Exit status is 0 only when everything present decrypts. Rows that were already
unreadable (for example after a past key rotation) count as failures in both
runs, so compare the outputs rather than the status.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter

from sqlalchemy import select, text
from sqlalchemy.orm import InstrumentedAttribute

from mykhaya import docs_sync, secrets_crypto
from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.models import (
    Group,
    PlatformAdministrator,
    PlatformPushSettings,
    PlatformSmtpSettings,
    PlatformStripeSettings,
    UserMfaMethodRecord,
)

_PLATFORM = secrets_crypto._HKDF_INFO
_STRIPE = secrets_crypto._STRIPE_HKDF_INFO

ENCRYPTED_COLUMNS: tuple[tuple[str, InstrumentedAttribute[str | None], bytes], ...] = (
    ("user_mfa", UserMfaMethodRecord.encrypted_secret, secrets_crypto._USER_MFA_TOTP_HKDF_INFO),
    ("home_join_code", Group.join_code_encrypted, secrets_crypto._HOME_JOIN_CODE_HKDF_INFO),
    ("administrator_totp", PlatformAdministrator.totp_secret_encrypted, _PLATFORM),
    ("smtp_password", PlatformSmtpSettings.encrypted_password, _PLATFORM),
    ("vapid_private_key", PlatformPushSettings.encrypted_vapid_private_key, _PLATFORM),
    ("stripe_test_key", PlatformStripeSettings.encrypted_test_secret_key, _STRIPE),
    ("stripe_test_webhook", PlatformStripeSettings.encrypted_test_webhook_secret, _STRIPE),
    ("stripe_live_key", PlatformStripeSettings.encrypted_live_secret_key, _STRIPE),
    ("stripe_live_webhook", PlatformStripeSettings.encrypted_live_webhook_secret, _STRIPE),
)


async def check_encrypted_secrets() -> dict[str, int]:
    settings = get_settings()
    counts: Counter[str] = Counter()

    def record(label: str, ciphertext: str, info: bytes) -> None:
        try:
            secrets_crypto.decrypt_secret(settings, ciphertext, info=info)
        except (secrets_crypto.SecretDecryptionError, UnicodeError):
            counts[f"{label}_failed"] += 1
        else:
            counts[f"{label}_readable"] += 1

    labels = [label for label, _, _ in ENCRYPTED_COLUMNS] + ["docs_sync_token"]
    async with SessionFactory() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        for label, column, info in ENCRYPTED_COLUMNS:
            for ciphertext in await db.scalars(select(column).where(column.is_not(None))):
                if ciphertext:
                    record(label, ciphertext, info)
        token = (await docs_sync.load(db, docs_sync.CONFIG_KEY)).get("token_secret_encrypted")
        if token:
            record("docs_sync_token", str(token), docs_sync._SECRET_INFO)
        await db.rollback()
    return {
        f"{label}_{kind}": int(counts[f"{label}_{kind}"])
        for label in labels
        for kind in ("readable", "failed")
    }


def main() -> int:
    result = asyncio.run(check_encrypted_secrets())
    print(json.dumps(result, sort_keys=True))
    return 0 if not any(v for k, v in result.items() if k.endswith("_failed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
