"""Central registry of file-backed secrets (MK-SEC-001 v1.2 SEC-093).

Every secret that can be supplied as a file is declared here once: the
Settings field it fills, the ``*_FILE`` field that names the file, its
credential identifier (K-01 to K-19, §6.3), its format, whether it is
required, and whether a literal environment value is still accepted. The
roles authorised to hold it are not repeated here; they come from the §6.3
grants in mykhaya.process_roles, so there is one source for each rule.

``resolve_secret_files`` is the only place a registry file is read. It runs
before field validation, so each file value reaches the same ``SecretStr``
field, type checks and provider validation as the equivalent environment
value. It reads through mykhaya.secret_files, the hardened descriptor-based
reader (SEC-017): absolute paths under /run/secrets only, no symbolic links,
regular files only, bounded per format.

The resolver never reads a file the process role is not granted, refuses a
literal value and a file for the same secret, and does nothing at all when no
``*_FILE`` setting is configured, so existing deployments are unaffected.
Nothing is cached here: the value goes straight into the settings model, and
errors name settings and credential identifiers only, never a value or path.

Two entries keep their own established loaders for compatibility and are
declared here for coverage only (``loader`` other than "registry"):

* the Apple sign-in key (K-10), whose MYKHAYA_APPLE_PRIVATE_KEY_FILE loader
  in mykhaya.config predates SEC-017 and is used by deployed configuration;
* the field-encryption and blind-index keyrings (K-18, K-19), whose loader in
  mykhaya.crypto.config treats a missing default file as "not provisioned".

Moving those to the hardened reader tightens their path rules and needs the
deployed file layout confirmed first.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from mykhaya.process_roles import (
    PROCESS_ROLES,
    ROLE_GRANTS,
    ProcessRoleError,
    grants,
    normalise_role,
)
from mykhaya.secret_files import SecretFormat, read_secret

SecretLoader = Literal["registry", "apple_compat", "keyring_compat"]


@dataclass(frozen=True)
class SecretSpec:
    """One file-backed secret.

    ``setting`` is the Settings field that receives the value (always a
    ``SecretStr``); ``file_setting`` is the field naming its file.
    ``literal_allowed`` is False where the secret may only come from a file
    (the database password: its legacy literal form is the password inside
    MYKHAYA_DATABASE_URL, checked by mykhaya.db_credentials).
    """

    setting: str
    file_setting: str
    credential: str
    format: SecretFormat
    required: bool = False
    literal_allowed: bool = True
    loader: SecretLoader = "registry"

    @property
    def env(self) -> str:
        return f"MYKHAYA_{self.setting.upper()}"

    @property
    def file_env(self) -> str:
        return f"MYKHAYA_{self.file_setting.upper()}"

    @property
    def authorised_roles(self) -> tuple[str, ...]:
        """Roles that may hold this secret (§6.3). "test" holds synthetic
        values of everything; an unset role keeps legacy behaviour."""
        return tuple(
            role
            for role in PROCESS_ROLES
            if role == "test" or self.credential in ROLE_GRANTS.get(role, frozenset())
        )


def _spec(
    setting: str, credential: str, kind: SecretFormat = "single_line", **options: Any
) -> SecretSpec:
    return SecretSpec(setting, f"{setting}_file", credential, kind, **options)


# The application Settings (api, worker, scheduler, cli and test processes).
SECRET_REGISTRY: tuple[SecretSpec, ...] = (
    _spec("secret_key", "K-01", required=True),
    _spec("database_password", "K-02", literal_allowed=False),
    _spec("smtp_password", "K-06"),
    _spec("vapid_private_key", "K-07"),
    _spec("apns_private_key", "K-08", "pem"),
    _spec("fcm_private_key", "K-09", "pem"),
    _spec("apple_private_key", "K-10", "pem", loader="apple_compat"),
    _spec("google_client_secret", "K-11"),
    _spec("stripe_secret_key", "K-12"),
    _spec("stripe_webhook_secret", "K-13"),
    _spec("dvla_uat_api_key", "K-14"),
    _spec("dvla_production_api_key", "K-15"),
    _spec("dvsa_client_id", "K-16"),
    _spec("dvsa_client_secret", "K-16"),
    _spec("dvsa_api_key", "K-16"),
    _spec("monitoring_watchdog_url", "K-17"),
    _spec("field_encryption_keys", "K-18", "json", loader="keyring_compat"),
    _spec("blind_index_keys", "K-19", "json", loader="keyring_compat"),
)

# The Alembic migrator's MigrationSettings: its database password is the
# migration credential (K-03), never the application one.
MIGRATION_SECRET_REGISTRY: tuple[SecretSpec, ...] = (
    _spec("database_password", "K-03", literal_allowed=False),
)


def _given(value: object) -> bool:
    if value is None:
        return False
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        value = getter()
    return not (isinstance(value, str) and not value.strip())


def resolve_secret_files(data: Any, registry: tuple[SecretSpec, ...]) -> Any:
    """Fill each registry secret from its ``*_FILE`` setting (a ``mode="before"``
    model validator body). Returns ``data`` untouched when nothing applies."""
    if not isinstance(data, Mapping):
        return data
    raw_role = normalise_role(data.get("process_role"))
    role = raw_role if isinstance(raw_role, str) and raw_role in PROCESS_ROLES else None
    resolved: dict[str, Any] | None = None
    for spec in registry:
        if spec.loader != "registry":
            continue
        literal = data.get(spec.setting)
        if not spec.literal_allowed and _given(literal):
            raise ValueError(f"{spec.env} is not supported; use {spec.file_env}")
        path = data.get(spec.file_setting)
        if not _given(path):
            continue
        if _given(literal):
            raise ValueError(f"Set {spec.env} or {spec.file_env}, not both")
        # SEC-102: a role never even reads a credential it is not granted.
        if role is not None and not grants(role, spec.credential):
            raise ProcessRoleError(
                f"MYKHAYA_PROCESS_ROLE={role}: must not receive {spec.file_env} ({spec.credential})"
            )
        if resolved is None:
            resolved = dict(data)
        resolved[spec.setting] = read_secret(spec.file_env, str(path), spec.format)
    return data if resolved is None else resolved


def registry_spec(setting: str) -> SecretSpec:
    """The application registry entry for a Settings field."""
    for spec in SECRET_REGISTRY:
        if spec.setting == setting:
            return spec
    raise KeyError(setting)
