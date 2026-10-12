"""The single write AND read path for Driveway's sensitive vehicle identifiers.

Phase 2B (Sensitive Data Protection) — writes: when
``MYKHAYA_DRIVEWAY_FIELD_ENCRYPTION_WRITE`` is on, each registration/VIN
change is *also* written as an AES-256-GCM envelope (``mykhaya.crypto``) into
``registration_ciphertext`` / ``vin_ciphertext`` alongside the plaintext.

Phase 2D — reads: when ``MYKHAYA_DRIVEWAY_FIELD_ENCRYPTION_READ`` is on, the
ciphertext is authoritative (see the read section at the end of this module);
otherwise reads use the plaintext columns exactly as before.

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
from mykhaya.crypto import (
    FieldBinding,
    SensitiveDataError,
    decrypt_sensitive_value,
    encrypt_sensitive_value,
)
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


# --- Phase 2D: ciphertext-first reads -------------------------------------------
#
# With MYKHAYA_DRIVEWAY_FIELD_ENCRYPTION_READ on, the ciphertext column is the
# authoritative source for a registration/VIN:
#
# * ciphertext present  -> decrypt it (keyring + the same row/column binding);
# * ciphertext NULL     -> transitional fallback to the plaintext column
#                          (logged as an event only, never the value);
# * ciphertext present but undecryptable (missing/unknown key, failed
#   authentication, malformed envelope) -> DrivewaySensitiveReadError. There
#   is deliberately NO plaintext fallback here: a ciphertext that does not
#   authenticate is an integrity failure, not a missing value.
#
# With the flag off every read returns the plaintext column, exactly as before.
#
# Every consumer of a stored vehicle's registration/VIN — API responses, Home
# Migration export and (future) provider integrations — must read through
# these functions, never vehicle.registration / vehicle.vin directly. VIN
# callers must decide visibility FIRST: get_vehicle_vin decrypts
# unconditionally, so it must only be called once the caller is entitled to
# see the VIN.


class DrivewaySensitiveReadError(Exception):
    """A stored registration/VIN ciphertext exists but could not be read.
    The message is generic; never carries a value, envelope, ID or key."""

    def __init__(self) -> None:
        super().__init__("A vehicle's protected details could not be read.")


def _logical_value(
    field: str,
    *,
    plaintext: str | None,
    ciphertext: str | None,
    binding: FieldBinding,
    settings: Settings,
) -> str | None:
    if not settings.driveway_field_encryption_read:
        return plaintext
    if ciphertext is None:
        if plaintext is not None:
            log.info("driveway.sensitive_read_plaintext_fallback", field=field)
        return plaintext
    try:
        return decrypt_sensitive_value(ciphertext, binding=binding, keyring=get_field_keyring())
    except SensitiveDataError as exc:
        # Field name and error class only — no vehicle ID, value or envelope.
        log.error("driveway.sensitive_read_failed", field=field, error=type(exc).__name__)
        raise DrivewaySensitiveReadError() from None


def logical_registration(
    vehicle_id: uuid.UUID, *, plaintext: str | None, ciphertext: str | None, settings: Settings
) -> str | None:
    """Row-agnostic form, for paths that hold column values rather than an
    ORM Vehicle (Home Migration export)."""
    return _logical_value(
        "registration",
        plaintext=plaintext,
        ciphertext=ciphertext,
        binding=registration_binding(vehicle_id),
        settings=settings,
    )


def logical_vin(
    vehicle_id: uuid.UUID, *, plaintext: str | None, ciphertext: str | None, settings: Settings
) -> str | None:
    """Row-agnostic form. Only call once the VIN may be revealed."""
    return _logical_value(
        "vin",
        plaintext=plaintext,
        ciphertext=ciphertext,
        binding=vin_binding(vehicle_id),
        settings=settings,
    )


def get_vehicle_registration(vehicle: Vehicle, settings: Settings) -> str | None:
    return logical_registration(
        vehicle.id,
        plaintext=vehicle.registration,
        ciphertext=vehicle.registration_ciphertext,
        settings=settings,
    )


def get_vehicle_vin(vehicle: Vehicle, settings: Settings) -> str | None:
    """Decrypts when the read flag is on. Callers MUST have already decided
    the viewer may see this vehicle's VIN (see routers.driveway
    ._may_see_sensitive_fields) — never call it speculatively."""
    return logical_vin(
        vehicle.id, plaintext=vehicle.vin, ciphertext=vehicle.vin_ciphertext, settings=settings
    )


def registration_for_provider(vehicle: Vehicle, settings: Settings) -> str | None:
    """The registration to send to an official-data provider (e.g. the
    planned DVSA MOT integration) for a STORED vehicle. Always the logical,
    ciphertext-first value — provider code must use this, never
    vehicle.registration. (Today's DVLA lookup takes the user's typed
    registration from the request, not a stored vehicle, so it has no caller
    yet.)"""
    return get_vehicle_registration(vehicle, settings)
