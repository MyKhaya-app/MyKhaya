"""Versioned key material for sensitive-field encryption and blind indexes.

Deliberately independent of ``MYKHAYA_SECRET_KEY`` (see
Sensitive Data Protection audit finding SDP-01): rotating
the session secret must only sign people out, never make household data
unreadable. Keys are never stored in PostgreSQL and never written into
backups — they are supplied to the process from a read-only file mounted
only into the services that need them (production), or from an environment
variable in development/test.

Keyring document format (one JSON object per keyring)::

    {
      "format": "mykhaya-keyring-v1",
      "purpose": "field-encryption" | "blind-index",
      "environment": "production" | "development" | "test",
      "active": "k2026a",
      "keys": {"k2026a": "<base64 of exactly 32 random bytes>"}
    }

Older keys stay in ``keys`` after a rotation so existing envelopes remain
readable; ``active`` selects the key for new writes only.

``KeyProvider`` is the seam for a later KMS/Vault-backed implementation: the
field and blind-index code only ever asks a provider for ``active_key_id()``
and ``get_key(key_id)``, so swapping the source of key bytes changes neither
the envelope format nor any caller.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from mykhaya.crypto.errors import KeyConfigurationError, UnknownKeyIdError

KEYRING_FORMAT = "mykhaya-keyring-v1"
KEY_BYTES = 32
# No dots: the envelope format uses "." as its field separator.
KEY_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,23}$")

KeyringPurpose = Literal["field-encryption", "blind-index"]
KeyringEnvironment = Literal["production", "development", "test"]
_ENVIRONMENTS: frozenset[str] = frozenset({"production", "development", "test"})


class KeyProvider(Protocol):
    """Source of versioned 256-bit keys. Implementations must never log or
    expose key bytes, and must raise UnknownKeyIdError for an unknown ID."""

    @property
    def purpose(self) -> KeyringPurpose: ...

    def active_key_id(self) -> str: ...

    def get_key(self, key_id: str) -> bytes: ...

    def key_ids(self) -> tuple[str, ...]: ...


@dataclass(frozen=True, repr=False)
class _KeyBytes:
    """Holds raw key bytes without ever rendering them in repr/str/logs."""

    value: bytes

    def __repr__(self) -> str:
        return "<redacted key>"

    __str__ = __repr__


class StaticKeyring:
    """An in-memory keyring loaded once at process start."""

    def __init__(
        self,
        *,
        purpose: KeyringPurpose,
        environment: KeyringEnvironment,
        active: str,
        keys: Mapping[str, bytes],
    ) -> None:
        if not keys:
            raise KeyConfigurationError("A keyring must contain at least one key.")
        for key_id, key in keys.items():
            _validate_key_id(key_id)
            if len(key) != KEY_BYTES:
                raise KeyConfigurationError(
                    f"Key {key_id!r} must be exactly {KEY_BYTES} bytes after base64 decoding."
                )
            if len(set(key)) < 8:
                # Catches all-zero / repeated-byte placeholders. A real random
                # 32-byte key essentially never has fewer than 8 distinct bytes.
                raise KeyConfigurationError(
                    f"Key {key_id!r} is not random key material (too few distinct bytes)."
                )
        if len({key for key in keys.values()}) != len(keys):
            raise KeyConfigurationError("Two key IDs in one keyring share the same key bytes.")
        if active not in keys:
            raise KeyConfigurationError("The active key ID is not present in the keyring.")
        self._purpose: KeyringPurpose = purpose
        self.environment: KeyringEnvironment = environment
        self._active = active
        self._keys = {key_id: _KeyBytes(key) for key_id, key in keys.items()}

    def __repr__(self) -> str:
        return (
            f"StaticKeyring(purpose={self._purpose!r}, environment={self.environment!r}, "
            f"active={self._active!r}, key_ids={list(self._keys)!r})"
        )

    @property
    def purpose(self) -> KeyringPurpose:
        return self._purpose

    def active_key_id(self) -> str:
        return self._active

    def get_key(self, key_id: str) -> bytes:
        key = self._keys.get(key_id)
        if key is None:
            raise UnknownKeyIdError(key_id)
        return key.value

    def key_ids(self) -> tuple[str, ...]:
        return tuple(self._keys)

    def shares_material_with(self, other: KeyProvider) -> bool:
        mine = {key.value for key in self._keys.values()}
        return any(other.get_key(key_id) in mine for key_id in other.key_ids())


def _validate_key_id(key_id: str) -> None:
    if not isinstance(key_id, str) or not KEY_ID_PATTERN.fullmatch(key_id):
        raise KeyConfigurationError(
            "Key IDs must be 1-24 characters of lowercase letters, digits, '-' or '_'."
        )


def _decode_key(key_id: str, encoded: object) -> bytes:
    if not isinstance(encoded, str):
        raise KeyConfigurationError(f"Key {key_id!r} must be a base64 string.")
    try:
        return base64.b64decode(encoded.strip(), validate=True)
    except (binascii.Error, ValueError):
        raise KeyConfigurationError(f"Key {key_id!r} is not valid base64.") from None


def parse_keyring(document: str, *, expected_purpose: KeyringPurpose) -> StaticKeyring:
    """Parse and fully validate a keyring JSON document.

    Error messages name the failing field or key ID, never key bytes, and
    JSON decode errors are re-raised without the original exception (whose
    message can quote the offending input).
    """
    try:
        data = json.loads(document)
    except (json.JSONDecodeError, TypeError):
        raise KeyConfigurationError(f"The {expected_purpose} keyring is not valid JSON.") from None
    if not isinstance(data, dict):
        raise KeyConfigurationError(f"The {expected_purpose} keyring must be a JSON object.")
    if data.get("format") != KEYRING_FORMAT:
        raise KeyConfigurationError(
            f"The {expected_purpose} keyring must declare format {KEYRING_FORMAT!r}."
        )
    if data.get("purpose") != expected_purpose:
        raise KeyConfigurationError(
            f"Expected a {expected_purpose!r} keyring; the document declares a different purpose."
        )
    environment = data.get("environment")
    if environment not in _ENVIRONMENTS:
        raise KeyConfigurationError(
            "The keyring must declare environment 'production', 'development' or 'test'."
        )
    raw_keys = data.get("keys")
    if not isinstance(raw_keys, dict):
        raise KeyConfigurationError("The keyring 'keys' field must be an object.")
    active = data.get("active")
    if not isinstance(active, str):
        raise KeyConfigurationError("The keyring 'active' field must be a key ID string.")
    keys: dict[str, bytes] = {}
    for key_id, encoded in raw_keys.items():
        _validate_key_id(key_id)
        keys[key_id] = _decode_key(key_id, encoded)
    return StaticKeyring(
        purpose=expected_purpose,
        environment=environment,
        active=active,
        keys=keys,
    )


def load_keyring_file(path: Path, *, expected_purpose: KeyringPurpose) -> StaticKeyring:
    try:
        document = path.read_text(encoding="utf-8")
    except OSError:
        raise KeyConfigurationError(
            f"The {expected_purpose} keyring file exists but could not be read. "
            "Check its ownership and permissions."
        ) from None
    return parse_keyring(document, expected_purpose=expected_purpose)
