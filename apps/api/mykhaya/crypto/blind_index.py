"""Keyed, deterministic lookup tokens ("blind indexes") for equality search
over encrypted fields.

HMAC-SHA256 under a key from a *separate* blind-index keyring — never the
field-encryption keys and never MYKHAYA_SECRET_KEY. An unkeyed hash is not
acceptable: small value spaces such as vehicle registrations can be
enumerated offline in minutes.

Token format: ``<key_id>.<64 hex chars>``. The key ID prefix lets tokens from
an old and a new key coexist during rotation; lookups during rotation use
``blind_index_candidates`` to match either.

``scope`` limits linkability: the recommended scope for household data is
the Home ID, so the same value in two Homes yields unrelated tokens and a
database dump cannot correlate households by value.

Callers must canonicalise the value first (one documented canonical form per
field). This module deliberately does no canonicalisation of its own beyond
rejecting an empty value.

Phase 2A: library only. No database column or caller uses this yet.
"""

from __future__ import annotations

import hashlib
import hmac
import re

from mykhaya.crypto.errors import KeyConfigurationError
from mykhaya.crypto.keyring import KeyProvider

BLIND_INDEX_VERSION = b"mkbi1"
_LABEL_PATTERN = re.compile(r"^[a-z][a-z0-9_.]{0,79}$")


def _message(canonical_value: str, *, purpose: str, scope: str) -> bytes:
    if not _LABEL_PATTERN.fullmatch(purpose):
        raise ValueError("purpose must be a lowercase dotted identifier.")
    if not isinstance(canonical_value, str) or not canonical_value:
        raise ValueError("canonical_value must be a non-empty string.")
    if not isinstance(scope, str) or not scope:
        raise ValueError("scope must be a non-empty string.")
    parts = (BLIND_INDEX_VERSION, purpose.encode(), scope.encode(), canonical_value.encode())
    return b"".join(len(part).to_bytes(4, "big") + part for part in parts)


def _require_blind_index_keyring(keyring: KeyProvider) -> None:
    if keyring.purpose != "blind-index":
        raise KeyConfigurationError("Blind indexes require a dedicated blind-index keyring.")


def _token(key_id: str, key: bytes, message: bytes) -> str:
    return f"{key_id}.{hmac.new(key, message, hashlib.sha256).hexdigest()}"


def blind_index(canonical_value: str, *, purpose: str, scope: str, keyring: KeyProvider) -> str:
    """Token under the active blind-index key — use this when writing."""
    _require_blind_index_keyring(keyring)
    key_id = keyring.active_key_id()
    return _token(
        key_id, keyring.get_key(key_id), _message(canonical_value, purpose=purpose, scope=scope)
    )


def blind_index_candidates(
    canonical_value: str, *, purpose: str, scope: str, keyring: KeyProvider
) -> tuple[str, ...]:
    """Tokens under every configured key — use this when looking up during a
    rotation, so rows not yet re-indexed still match."""
    _require_blind_index_keyring(keyring)
    message = _message(canonical_value, purpose=purpose, scope=scope)
    return tuple(_token(key_id, keyring.get_key(key_id), message) for key_id in keyring.key_ids())
