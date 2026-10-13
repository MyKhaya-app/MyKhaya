"""Central sensitive-data cryptography for MyKhaya.

Public surface — import from here, never reimplement primitives elsewhere:

* ``encrypt_sensitive_value`` / ``decrypt_sensitive_value`` with a
  ``FieldBinding`` (purpose + column + row ID, all authenticated)
* ``reencrypt_sensitive_value`` / ``needs_reencryption`` for key rotation
* ``blind_index`` / ``blind_index_candidates`` for keyed equality lookup
* ``KeyProvider`` / ``StaticKeyring`` and the loaders in ``mykhaya.crypto.config``

Independent of ``mykhaya.secrets_crypto`` and of ``MYKHAYA_SECRET_KEY``. See
docs/operations/sensitive-field-keys.md.
"""

from mykhaya.crypto.blind_index import blind_index, blind_index_candidates
from mykhaya.crypto.errors import (
    KeyConfigurationError,
    KeyUnavailableError,
    MalformedEnvelopeError,
    SensitiveDataError,
    SensitiveValueDecryptionError,
    UnknownKeyIdError,
)
from mykhaya.crypto.field import (
    FieldBinding,
    decrypt_sensitive_value,
    encrypt_sensitive_value,
    envelope_key_id,
    needs_reencryption,
    reencrypt_sensitive_value,
)
from mykhaya.crypto.keyring import KeyProvider, StaticKeyring, parse_keyring

__all__ = [
    "FieldBinding",
    "KeyConfigurationError",
    "KeyProvider",
    "KeyUnavailableError",
    "MalformedEnvelopeError",
    "SensitiveDataError",
    "SensitiveValueDecryptionError",
    "StaticKeyring",
    "UnknownKeyIdError",
    "blind_index",
    "blind_index_candidates",
    "decrypt_sensitive_value",
    "encrypt_sensitive_value",
    "envelope_key_id",
    "needs_reencryption",
    "parse_keyring",
    "reencrypt_sensitive_value",
]
