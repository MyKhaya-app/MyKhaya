"""The single write path for Driveway's sensitive vehicle identifiers.

Phase 2B (Sensitive Data Protection): dual-write only. ``vehicles.registration``
and ``vehicles.vin`` stay the authoritative, plaintext source for every read;
when ``MYKHAYA_DRIVEWAY_FIELD_ENCRYPTION_WRITE`` is on, each change is *also*
written as an AES-256-GCM envelope (``mykhaya.crypto``) into
``registration_ciphertext`` / ``vin_ciphertext``. Nothing reads the
ciphertext yet and there is no backfill.

Every code path that sets a registration or VIN goes through this module —
the Driveway router (create/update) and Home Migration import — so the
invariant is enforced in one place:

* the ciphertext column is never stale: whenever the plaintext changes, its
  ciphertext is re-encrypted (flag on) or cleared (flag off);
* clearing a value clears both columns;
* an unchanged value is never re-encrypted;
* with the flag on and no usable keyring, the write fails
  (DrivewayFieldEncryptionUnavailable) before anything is committed, rather
  than silently writing plaintext only.

Ciphertext is bound (AES-GCM associated data) to the vehicle's own ID and to
the exact column/purpose, so the row ID must exist before encryption — create
paths assign it explicitly with the project's uuid7 convention.

Never log, audit or return plaintext, ciphertext or key material from here.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from mykhaya.config import Settings
from mykhaya.crypto import FieldBinding, SensitiveDataError, encrypt_sensitive_value
from mykhaya.crypto.config import get_field_keyring
from mykhaya.ids import uuid7
from mykhaya.models import Vehicle

log = structlog.get_logger("driveway_sensitive")

REGISTRATION_PURPOSE = "vehicle.registration"
REGISTRATION_COLUMN = "vehicles.registration_ciphertext"
VIN_PURPOSE = "vehicle.vin"
VIN_COLUMN = "vehicles.vin_ciphertext"


class DrivewayFieldEncryptionUnavailable(Exception):
    """Dual-write is enabled but the value could not be encrypted (no usable
    field-encryption keyring). The caller must abort the whole write."""

    def __init__(self) -> None:
        super().__init__("Vehicle sensitive-field encryption is enabled but unavailable.")


def registration_binding(vehicle_id: uuid.UUID) -> FieldBinding:
    return FieldBinding(purpose=REGISTRATION_PURPOSE, column=REGISTRATION_COLUMN, row_id=vehicle_id)


def vin_binding(vehicle_id: uuid.UUID) -> FieldBinding:
    return FieldBinding(purpose=VIN_PURPOSE, column=VIN_COLUMN, row_id=vehicle_id)


def _ciphertext(value: str | None, binding: FieldBinding, settings: Settings) -> str | None:
    """The ciphertext that should accompany ``value``: None when there is no
    value or dual-write is off, otherwise a fresh envelope under the active key."""
    if value is None or not settings.driveway_field_encryption_write:
        return None
    try:
        return encrypt_sensitive_value(value, binding=binding, keyring=get_field_keyring())
    except SensitiveDataError as exc:
        # Class name only — never the value, the binding's row, or key details.
        log.error("driveway.field_encryption_unavailable", error=type(exc).__name__)
        raise DrivewayFieldEncryptionUnavailable() from None


def vehicle_sensitive_ciphertexts(
    vehicle_id: uuid.UUID,
    *,
    registration: str | None,
    vin: str | None,
    settings: Settings,
) -> dict[str, Any]:
    """Ciphertext column values for a brand-new row (create / import)."""
    return {
        "registration_ciphertext": _ciphertext(
            registration, registration_binding(vehicle_id), settings
        ),
        "vin_ciphertext": _ciphertext(vin, vin_binding(vehicle_id), settings),
    }


def new_vehicle_id() -> uuid.UUID:
    """Same generator as UuidTimeMixin's default, assigned up front because
    the encryption binding needs the ID before the row is flushed."""
    return uuid7()


def set_vehicle_registration(row: Vehicle, value: str | None, settings: Settings) -> None:
    """Set an existing row's registration and keep its ciphertext in step.
    A no-op when the value is unchanged (no needless re-encryption)."""
    if row.registration == value:
        return
    ciphertext = _ciphertext(value, registration_binding(row.id), settings)
    row.registration = value
    row.registration_ciphertext = ciphertext


def set_vehicle_vin(row: Vehicle, value: str | None, settings: Settings) -> None:
    """Set an existing row's VIN and keep its ciphertext in step.
    A no-op when the value is unchanged (no needless re-encryption)."""
    if row.vin == value:
        return
    ciphertext = _ciphertext(value, vin_binding(row.id), settings)
    row.vin = value
    row.vin_ciphertext = ciphertext
