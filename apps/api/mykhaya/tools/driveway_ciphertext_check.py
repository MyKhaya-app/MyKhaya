"""Read-only verification of Driveway dual-write ciphertext (Phase 2B).

For every vehicle that has a ciphertext column populated, decrypts it with
the application's own keyring and binding and compares it with the
authoritative plaintext. Prints **counts only** — never a registration, VIN,
ciphertext, key ID detail beyond the active ID, vehicle ID or Home ID — and
never writes (PostgreSQL READ ONLY transaction, never committed).

Usage (inside the running api container, which has the keyring mounted)::

    docker compose exec -T api python -m mykhaya.tools.driveway_ciphertext_check

Exit status is 0 only when every populated ciphertext decrypts and matches,
so the tool can gate rollout steps (and, later, Phase 2C/2D).
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter

from sqlalchemy import select, text

from mykhaya.crypto import SensitiveDataError, decrypt_sensitive_value
from mykhaya.crypto.config import get_field_keyring
from mykhaya.db import SessionFactory
from mykhaya.driveway_sensitive import registration_binding, vin_binding
from mykhaya.models import Vehicle

BATCH_SIZE = 500


async def check_vehicle_ciphertexts() -> dict[str, int]:
    keyring = get_field_keyring()
    counts: Counter[str] = Counter()
    async with SessionFactory() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        last_id = None
        while True:
            query = (
                select(
                    Vehicle.id,
                    Vehicle.registration,
                    Vehicle.registration_ciphertext,
                    Vehicle.vin,
                    Vehicle.vin_ciphertext,
                )
                .order_by(Vehicle.id)
                .limit(BATCH_SIZE)
            )
            if last_id is not None:
                query = query.where(Vehicle.id > last_id)
            rows = (await db.execute(query)).all()
            if not rows:
                break
            for row in rows:
                counts["vehicles_total"] += 1
                for field, plaintext, envelope, binding in (
                    (
                        "registration",
                        row.registration,
                        row.registration_ciphertext,
                        registration_binding(row.id),
                    ),
                    ("vin", row.vin, row.vin_ciphertext, vin_binding(row.id)),
                ):
                    if plaintext is not None:
                        counts[f"{field}_plaintext"] += 1
                    if envelope is None:
                        if plaintext is not None:
                            counts[f"{field}_without_ciphertext"] += 1
                        continue
                    counts[f"{field}_ciphertext"] += 1
                    try:
                        decrypted = decrypt_sensitive_value(
                            envelope, binding=binding, keyring=keyring
                        )
                    except SensitiveDataError:
                        counts[f"{field}_decrypt_failed"] += 1
                        continue
                    if decrypted == plaintext:
                        counts[f"{field}_verified"] += 1
                    else:
                        counts[f"{field}_mismatch"] += 1
            last_id = rows[-1].id
        await db.rollback()
    keys = [
        "vehicles_total",
        *(
            f"{field}_{kind}"
            for field in ("registration", "vin")
            for kind in (
                "plaintext",
                "ciphertext",
                "verified",
                "mismatch",
                "decrypt_failed",
                "without_ciphertext",
            )
        ),
    ]
    return {key: int(counts[key]) for key in keys}


def healthy(result: dict[str, int]) -> bool:
    return all(
        result[f"{field}_{kind}"] == 0
        for field in ("registration", "vin")
        for kind in ("mismatch", "decrypt_failed")
    )


def main() -> int:
    try:
        result = asyncio.run(check_vehicle_ciphertexts())
    except SensitiveDataError as exc:
        print(f"error: no usable field-encryption keyring ({type(exc).__name__})", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if healthy(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
