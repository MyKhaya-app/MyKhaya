"""AES-256-GCM authenticated encryption for individual sensitive fields.

Envelope (stored as text)::

    mkf1.<key_id>.<base64url-nopad(nonce[12] || ciphertext || tag[16])>

* ``mkf1`` — envelope format version. A future format (e.g. AES-GCM-SIV) gets
  a new prefix, so old and new envelopes can coexist unambiguously.
* ``key_id`` — which keyring entry encrypted this value; reads select the key
  by this ID, so rotating the active key never breaks existing rows.
* nonce — 96 random bits from ``os.urandom`` per encryption. Never reused
  deliberately; with random nonces a single key stays far below the ~2^32
  message bound at MyKhaya's scale, and rotation resets the count.

Associated data binds every ciphertext to the exact place it belongs: the
envelope version, key ID, *purpose*, *column* and *row ID*. Moving a
ciphertext to another row, another column or another purpose — or editing
the key ID in the header — makes authentication fail. The AAD is a
length-prefixed encoding, so no two distinct (purpose, column, row) tuples
can ever produce the same bytes.

These are explicit calls by design. There is no SQLAlchemy type that
encrypts/decrypts transparently: decryption must happen only in a response
builder *after* authorization has decided the caller may see the field.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
import uuid
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mykhaya.crypto.errors import (
    KeyConfigurationError,
    MalformedEnvelopeError,
    SensitiveValueDecryptionError,
)
from mykhaya.crypto.keyring import KEY_ID_PATTERN, KeyProvider

ENVELOPE_VERSION = "mkf1"
NONCE_BYTES = 12
TAG_BYTES = 16
_AAD_DOMAIN = b"mykhaya-sensitive-field"
# Lowercase dotted identifiers, e.g. purpose "vehicle.registration", column
# "vehicles.registration_ciphertext". Restricting the alphabet keeps the AAD
# unambiguous and stops callers passing user data as a binding label.
_LABEL_PATTERN = re.compile(r"^[a-z][a-z0-9_.]{0,79}$")
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class FieldBinding:
    """Where a ciphertext belongs. All three parts are authenticated."""

    purpose: str
    column: str
    row_id: uuid.UUID

    def __post_init__(self) -> None:
        if not _LABEL_PATTERN.fullmatch(self.purpose):
            raise ValueError("purpose must be a lowercase dotted identifier.")
        if not _LABEL_PATTERN.fullmatch(self.column):
            raise ValueError("column must be a lowercase dotted identifier.")
        if not isinstance(self.row_id, uuid.UUID):
            raise ValueError("row_id must be a UUID.")


def _length_prefixed(*parts: bytes) -> bytes:
    return b"".join(len(part).to_bytes(4, "big") + part for part in parts)


def _aad(binding: FieldBinding, key_id: str) -> bytes:
    return _length_prefixed(
        _AAD_DOMAIN,
        ENVELOPE_VERSION.encode(),
        key_id.encode(),
        binding.purpose.encode(),
        binding.column.encode(),
        binding.row_id.bytes,
    )


def _require_field_keyring(keyring: KeyProvider) -> None:
    if keyring.purpose != "field-encryption":
        raise KeyConfigurationError("A blind-index keyring cannot be used for field encryption.")


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode(text: str) -> bytes:
    if not _BASE64URL.fullmatch(text):
        raise MalformedEnvelopeError()
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        raise MalformedEnvelopeError() from None


@dataclass(frozen=True)
class ParsedEnvelope:
    version: str
    key_id: str
    payload: bytes


def parse_envelope(envelope: str) -> ParsedEnvelope:
    """Structural parse only — does not decrypt or authenticate."""
    if not isinstance(envelope, str):
        raise MalformedEnvelopeError()
    parts = envelope.split(".")
    if len(parts) != 3:
        raise MalformedEnvelopeError()
    version, key_id, body = parts
    if version != ENVELOPE_VERSION or not KEY_ID_PATTERN.fullmatch(key_id):
        raise MalformedEnvelopeError()
    payload = _decode(body)
    if len(payload) < NONCE_BYTES + TAG_BYTES:
        raise MalformedEnvelopeError()
    return ParsedEnvelope(version=version, key_id=key_id, payload=payload)


def envelope_key_id(envelope: str) -> str:
    return parse_envelope(envelope).key_id


def encrypt_sensitive_value(plaintext: str, *, binding: FieldBinding, keyring: KeyProvider) -> str:
    """Encrypt ``plaintext`` with the keyring's active key for ``binding``."""
    if not isinstance(plaintext, str):
        raise TypeError("plaintext must be a str.")
    _require_field_keyring(keyring)
    key_id = keyring.active_key_id()
    nonce = os.urandom(NONCE_BYTES)
    sealed = AESGCM(keyring.get_key(key_id)).encrypt(
        nonce, plaintext.encode("utf-8"), _aad(binding, key_id)
    )
    return f"{ENVELOPE_VERSION}.{key_id}.{_encode(nonce + sealed)}"


def decrypt_sensitive_value(envelope: str, *, binding: FieldBinding, keyring: KeyProvider) -> str:
    """Authenticate and decrypt one envelope.

    Raises MalformedEnvelopeError, UnknownKeyIdError or
    SensitiveValueDecryptionError. None of them carries the envelope,
    plaintext or key; ``from None`` drops the underlying library exception
    so no traceback context can echo input either.
    """
    _require_field_keyring(keyring)
    parsed = parse_envelope(envelope)
    key = keyring.get_key(parsed.key_id)
    nonce, sealed = parsed.payload[:NONCE_BYTES], parsed.payload[NONCE_BYTES:]
    try:
        plaintext = AESGCM(key).decrypt(nonce, sealed, _aad(binding, parsed.key_id))
    except InvalidTag:
        raise SensitiveValueDecryptionError(parsed.key_id) from None
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError:
        # Unreachable for envelopes this module wrote; treat as corruption.
        raise SensitiveValueDecryptionError(parsed.key_id) from None


def needs_reencryption(envelope: str, *, keyring: KeyProvider) -> bool:
    """True when ``envelope`` was not written with the keyring's active key."""
    return envelope_key_id(envelope) != keyring.active_key_id()


def reencrypt_sensitive_value(envelope: str, *, binding: FieldBinding, keyring: KeyProvider) -> str:
    """Rotation primitive: authenticate under the envelope's own key, then
    re-seal under the active key with a fresh nonce. Returns the envelope
    unchanged when it already uses the active key, so a rotation pass is
    idempotent and safe to resume."""
    if not needs_reencryption(envelope, keyring=keyring):
        decrypt_sensitive_value(envelope, binding=binding, keyring=keyring)
        return envelope
    plaintext = decrypt_sensitive_value(envelope, binding=binding, keyring=keyring)
    return encrypt_sensitive_value(plaintext, binding=binding, keyring=keyring)
