"""Typed failures for sensitive-field cryptography.

Every message here is a fixed string. None of these exceptions ever carries
plaintext, ciphertext, envelope text or key material — only (at most) a key
ID, which is a non-secret label. Callers log the exception *class* and the
key ID, never ``str(envelope)`` or the value being protected.
"""

from __future__ import annotations


class SensitiveDataError(Exception):
    """Base class for every sensitive-field crypto failure."""


class KeyConfigurationError(SensitiveDataError):
    """The configured key material is missing, malformed or not allowed here.

    Raised at startup validation so a bad keyring fails closed before any
    request is served.
    """


class KeyUnavailableError(SensitiveDataError):
    """No keyring has been provisioned for this process."""


class UnknownKeyIdError(SensitiveDataError):
    """An envelope names a key ID this keyring does not hold."""

    def __init__(self, key_id: str) -> None:
        super().__init__(f"No key is configured for key ID {key_id!r}.")
        self.key_id = key_id


class MalformedEnvelopeError(SensitiveDataError):
    """The stored value is not a well-formed ciphertext envelope."""

    def __init__(self) -> None:
        super().__init__("The stored value is not a valid sensitive-field envelope.")


class SensitiveValueDecryptionError(SensitiveDataError):
    """Authentication failed: wrong key, wrong row/column/purpose, or tampering.

    These causes are deliberately indistinguishable — AES-GCM only reports
    that the tag did not verify, and revealing which binding failed would
    help an attacker probe the scheme.
    """

    def __init__(self, key_id: str) -> None:
        super().__init__(f"The sensitive value could not be authenticated with key ID {key_id!r}.")
        self.key_id = key_id
