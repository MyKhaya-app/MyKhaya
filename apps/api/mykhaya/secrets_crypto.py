"""Encryption at rest for Platform-Admin-managed secrets (e.g. the SMTP password).

There is no separate key-management surface: the Fernet key is derived from
``MYKHAYA_SECRET_KEY`` via HKDF-SHA256 with a purpose-specific info string, so rotating
that secret invalidates stored ciphertext the same way it invalidates sessions.
"""

from __future__ import annotations

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from mykhaya.config import Settings

_HKDF_INFO = b"mykhaya-smtp-secret-v1"
_HKDF_SALT = b"mykhaya-secrets-crypto"


class SecretDecryptionError(RuntimeError):
    """Raised when stored ciphertext cannot be decrypted with the current secret key."""


def _derive_fernet_key(settings: Settings) -> bytes:
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=_HKDF_INFO,
    )
    raw = hkdf.derive(settings.secret_key.get_secret_value().encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


def encrypt_secret(settings: Settings, plaintext: str) -> str:
    fernet = Fernet(_derive_fernet_key(settings))
    return fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(settings: Settings, ciphertext: str) -> str:
    fernet = Fernet(_derive_fernet_key(settings))
    try:
        return fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretDecryptionError(
            "Stored secret could not be decrypted with the current MYKHAYA_SECRET_KEY. "
            "This happens after a secret-key rotation and requires re-entering the secret."
        ) from exc
