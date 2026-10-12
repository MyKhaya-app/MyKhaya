"""Operator-run backfill of missing Driveway ciphertext (Phase 2C).

Fills ``registration_ciphertext`` where ``registration`` is set and the
ciphertext is NULL, and ``vin_ciphertext`` likewise — nothing else. It
encrypts the exact stored plaintext (no trimming or normalisation) with the
same keyring and AAD bindings as the normal write path
(mykhaya.driveway_sensitive), never changes plaintext, never replaces or
re-encrypts an existing ciphertext, and never touches any other column —
including ``updated_at``, so a user's open edit form is not invalidated.

Dry-run is the default and performs no writes (READ ONLY transaction)::

    docker compose exec -T api python -m mykhaya.tools.driveway_ciphertext_backfill

Writing requires ``--apply``, MYKHAYA_DRIVEWAY_FIELD_ENCRYPTION_WRITE=true
(so normal writes already keep ciphertext in step) and a usable
field-encryption keyring, checked before any row is touched::

    docker compose exec -T api python -m mykhaya.tools.driveway_ciphertext_backfill --apply

All writes happen in one transaction: any failure rolls everything back.
Each UPDATE is guarded on "ciphertext still NULL and plaintext still equal to
what was encrypted", and the eligible rows are locked for the transaction, so
a concurrent edit can never be overwritten. Re-running is a no-op.

Output is counts only — never a registration, VIN, vehicle/Home ID,
ciphertext or key material. Verification of the result is the job of
``mykhaya.tools.driveway_ciphertext_check``.

Never run automatically (no Alembic, startup, worker, scheduler or deploy hook).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from typing import Any

import structlog
from sqlalchemy import and_, func, or_, select, text, update

from mykhaya.config import Settings, get_settings
from mykhaya.crypto import SensitiveDataError, encrypt_sensitive_value
from mykhaya.crypto.config import get_field_keyring
from mykhaya.db import SessionFactory
from mykhaya.driveway_sensitive import registration_binding, vin_binding
from mykhaya.models import Vehicle

log = structlog.get_logger("driveway_ciphertext_backfill")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2


def _empty_report(mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "vehicles_scanned": 0,
        "registration_plaintext": 0,
        "registration_already_encrypted": 0,
        "registration_needs_backfill": 0,
        "registration_backfilled": 0,
        "vin_plaintext": 0,
        "vin_already_encrypted": 0,
        "vin_needs_backfill": 0,
        "vin_backfilled": 0,
    }


async def _survey(db: Any, report: dict[str, Any]) -> None:
    """Aggregate counts only — no row values leave the database here."""
    row = (
        await db.execute(
            select(
                func.count(),
                func.count(Vehicle.registration),
                func.count(Vehicle.registration).filter(
                    Vehicle.registration_ciphertext.is_not(None)
                ),
                func.count(Vehicle.registration).filter(Vehicle.registration_ciphertext.is_(None)),
                func.count(Vehicle.vin),
                func.count(Vehicle.vin).filter(Vehicle.vin_ciphertext.is_not(None)),
                func.count(Vehicle.vin).filter(Vehicle.vin_ciphertext.is_(None)),
            ).select_from(Vehicle)
        )
    ).one()
    (
        report["vehicles_scanned"],
        report["registration_plaintext"],
        report["registration_already_encrypted"],
        report["registration_needs_backfill"],
        report["vin_plaintext"],
        report["vin_already_encrypted"],
        report["vin_needs_backfill"],
    ) = (int(value) for value in row)


async def _guarded_update(
    db: Any,
    vehicle_id: uuid.UUID,
    *,
    plaintext_column: Any,
    ciphertext_column: Any,
    plaintext: str,
    ciphertext: str,
) -> int:
    result = await db.execute(
        update(Vehicle)
        .where(
            Vehicle.id == vehicle_id,
            ciphertext_column.is_(None),
            plaintext_column == plaintext,
        )
        # Only the ciphertext column changes. Pinning updated_at to its
        # current value stops the mixin's onupdate=now() from touching it.
        .values({ciphertext_column.key: ciphertext, "updated_at": Vehicle.updated_at})
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


async def run_backfill(*, apply: bool, settings: Settings) -> tuple[int, dict[str, Any]]:
    """Returns (exit_code, counts-only report). Never raises for expected
    refusals; any write-phase failure rolls the single transaction back."""
    report = _empty_report("apply" if apply else "dry-run")
    if not apply:
        async with SessionFactory() as db:
            await db.execute(text("SET TRANSACTION READ ONLY"))
            await _survey(db, report)
            await db.rollback()
        return EXIT_OK, report

    if not settings.driveway_field_encryption_write:
        report["refused"] = "driveway_field_encryption_write_disabled"
        return EXIT_REFUSED, report
    try:
        keyring = get_field_keyring()
    except SensitiveDataError as exc:
        log.error("driveway.ciphertext_backfill.keyring_unavailable", error=type(exc).__name__)
        report["refused"] = "field_encryption_keyring_unavailable"
        return EXIT_REFUSED, report

    try:
        async with SessionFactory() as db:
            await _survey(db, report)
            eligible = (
                await db.execute(
                    select(
                        Vehicle.id,
                        Vehicle.registration,
                        Vehicle.registration_ciphertext,
                        Vehicle.vin,
                        Vehicle.vin_ciphertext,
                    )
                    .where(
                        or_(
                            and_(
                                Vehicle.registration.is_not(None),
                                Vehicle.registration_ciphertext.is_(None),
                            ),
                            and_(Vehicle.vin.is_not(None), Vehicle.vin_ciphertext.is_(None)),
                        )
                    )
                    .order_by(Vehicle.id)
                    .with_for_update()
                )
            ).all()
            for row in eligible:
                if row.registration is not None and row.registration_ciphertext is None:
                    report["registration_backfilled"] += await _guarded_update(
                        db,
                        row.id,
                        plaintext_column=Vehicle.registration,
                        ciphertext_column=Vehicle.registration_ciphertext,
                        plaintext=row.registration,
                        ciphertext=encrypt_sensitive_value(
                            row.registration,
                            binding=registration_binding(row.id),
                            keyring=keyring,
                        ),
                    )
                if row.vin is not None and row.vin_ciphertext is None:
                    report["vin_backfilled"] += await _guarded_update(
                        db,
                        row.id,
                        plaintext_column=Vehicle.vin,
                        ciphertext_column=Vehicle.vin_ciphertext,
                        plaintext=row.vin,
                        ciphertext=encrypt_sensitive_value(
                            row.vin, binding=vin_binding(row.id), keyring=keyring
                        ),
                    )
            await db.commit()
    except Exception as exc:
        # The session context rolls back the single transaction; nothing was
        # committed. Error class only — never values, IDs or ciphertext.
        log.error("driveway.ciphertext_backfill.failed", error=type(exc).__name__)
        report["registration_backfilled"] = 0
        report["vin_backfilled"] = 0
        report["failed"] = type(exc).__name__
        return EXIT_FAILED, report
    log.info(
        "driveway.ciphertext_backfill.applied",
        registration_backfilled=report["registration_backfilled"],
        vin_backfilled=report["vin_backfilled"],
    )
    return EXIT_OK, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fill missing Driveway registration/VIN ciphertext (dry-run by default)."
    )
    parser.add_argument(
        "--apply", action="store_true", help="write the missing ciphertext (default: dry-run)"
    )
    args = parser.parse_args(argv)
    code, report = asyncio.run(run_backfill(apply=args.apply, settings=get_settings()))
    print(json.dumps(report, indent=2))
    if code == EXIT_REFUSED:
        reason = report.get("refused")
        if reason == "driveway_field_encryption_write_disabled":
            print(
                "refused: set MYKHAYA_DRIVEWAY_FIELD_ENCRYPTION_WRITE=true before --apply",
                file=sys.stderr,
            )
        else:
            print("refused: no usable field-encryption keyring", file=sys.stderr)
    elif code == EXIT_FAILED:
        print("failed: no changes were committed", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
