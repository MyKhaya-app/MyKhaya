"""Locating, loading and validating the sensitive-field keyrings.

Sources, in order:

1. **File** (the production mechanism): ``MYKHAYA_FIELD_ENCRYPTION_KEYS_FILE`` /
   ``MYKHAYA_BLIND_INDEX_KEYS_FILE``, defaulting to files under
   ``/run/secrets/mykhaya/``. Compose bind-mounts that directory read-only
   into api/worker/scheduler only — never postgres, migrate, web or test.
2. **Environment** (development/test only): ``MYKHAYA_FIELD_ENCRYPTION_KEYS`` /
   ``MYKHAYA_BLIND_INDEX_KEYS`` holding the same JSON document. Settings
   validation rejects these variables outright in production.

Supplying both a file and an environment value is a configuration error
rather than a silent precedence rule.

Startup validation fails closed on anything malformed. A keyring whose
declared environment does not match the running environment is refused in
both directions: production will not load development keys, and
development/test will not load production keys.

Phase 2A: nothing encrypts with these keys yet, so an *unprovisioned*
keyring is allowed (logged) unless ``MYKHAYA_SENSITIVE_FIELD_KEYS_REQUIRED``
is true. Phase 2B makes them mandatory in production.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import structlog

from mykhaya.config import Settings, get_settings
from mykhaya.crypto.errors import KeyConfigurationError, KeyUnavailableError
from mykhaya.crypto.keyring import (
    KeyringPurpose,
    StaticKeyring,
    load_keyring_file,
    parse_keyring,
)

log = structlog.get_logger("sensitive_keys")


@dataclass(frozen=True)
class SensitiveKeyStatus:
    """Non-secret summary safe to log: sources and key IDs only."""

    field_source: str | None
    blind_index_source: str | None
    field_active_key_id: str | None
    blind_index_active_key_id: str | None

    @property
    def provisioned(self) -> bool:
        return self.field_source is not None


def _load(
    *,
    file_path: str,
    env_value: str | None,
    purpose: KeyringPurpose,
) -> tuple[StaticKeyring | None, str | None]:
    path = Path(file_path)
    file_present = path.exists()
    if file_present and not path.is_file():
        raise KeyConfigurationError(f"The {purpose} keyring path exists but is not a file.")
    if file_present and env_value:
        raise KeyConfigurationError(
            f"The {purpose} keyring is configured both as a file and as an environment "
            "variable. Configure exactly one."
        )
    if file_present:
        return load_keyring_file(path, expected_purpose=purpose), "file"
    if env_value:
        return parse_keyring(env_value, expected_purpose=purpose), "environment"
    return None, None


def _check_environment(keyring: StaticKeyring, settings: Settings) -> None:
    if settings.environment == "production" and keyring.environment != "production":
        raise KeyConfigurationError(
            f"Production refuses a {keyring.purpose} keyring declared for {keyring.environment!r}."
        )
    if settings.environment != "production" and keyring.environment == "production":
        raise KeyConfigurationError(
            f"A production {keyring.purpose} keyring must never be loaded outside production."
        )


def load_sensitive_keyrings(
    settings: Settings,
) -> tuple[StaticKeyring | None, StaticKeyring | None, SensitiveKeyStatus]:
    field, field_source = _load(
        file_path=settings.field_encryption_keys_file,
        env_value=(
            settings.field_encryption_keys.get_secret_value()
            if settings.field_encryption_keys
            else None
        ),
        purpose="field-encryption",
    )
    blind, blind_source = _load(
        file_path=settings.blind_index_keys_file,
        env_value=(
            settings.blind_index_keys.get_secret_value() if settings.blind_index_keys else None
        ),
        purpose="blind-index",
    )
    if (field is None) != (blind is None):
        raise KeyConfigurationError(
            "Field-encryption and blind-index keyrings must be provisioned together."
        )
    for keyring in (field, blind):
        if keyring is not None:
            _check_environment(keyring, settings)
    if field is not None and blind is not None and field.shares_material_with(blind):
        raise KeyConfigurationError(
            "Field-encryption and blind-index keyrings must not share key material."
        )
    if field is None and settings.sensitive_field_keys_required:
        raise KeyConfigurationError(
            "Sensitive-field keyrings are required but none are provisioned."
        )
    status = SensitiveKeyStatus(
        field_source=field_source,
        blind_index_source=blind_source,
        field_active_key_id=field.active_key_id() if field else None,
        blind_index_active_key_id=blind.active_key_id() if blind else None,
    )
    return field, blind, status


def validate_sensitive_key_configuration(settings: Settings, *, service: str) -> SensitiveKeyStatus:
    """Run at process start (api, worker, scheduler). Raises
    KeyConfigurationError on any invalid configuration; logs only sources and
    key IDs, never key material."""
    _, _, status = load_sensitive_keyrings(settings)
    if status.provisioned:
        log.info(
            "sensitive_field_keys_loaded",
            service=service,
            field_source=status.field_source,
            field_active_key_id=status.field_active_key_id,
            blind_index_source=status.blind_index_source,
            blind_index_active_key_id=status.blind_index_active_key_id,
        )
    else:
        log.info("sensitive_field_keys_not_provisioned", service=service)
    return status


@lru_cache
def _cached_keyrings() -> tuple[StaticKeyring | None, StaticKeyring | None]:
    field, blind, _ = load_sensitive_keyrings(get_settings())
    return field, blind


def get_field_keyring() -> StaticKeyring:
    field, _ = _cached_keyrings()
    if field is None:
        raise KeyUnavailableError("No field-encryption keyring is provisioned.")
    return field


def get_blind_index_keyring() -> StaticKeyring:
    _, blind = _cached_keyrings()
    if blind is None:
        raise KeyUnavailableError("No blind-index keyring is provisioned.")
    return blind
