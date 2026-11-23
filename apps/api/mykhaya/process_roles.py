"""Process-role credential policy (MK-SEC-001 v1.2 §6.3, SEC-089, SEC-101 to SEC-103).

``MYKHAYA_PROCESS_ROLE`` names the process a configuration belongs to. When it
is unset, nothing here is enforced and every existing deployment behaves
exactly as before. When it is set, configuration is checked against the §6.3
service credential-access matrix:

* credentials the role is not granted are rejected if present (SEC-102);
* credentials another role needs are never *required* of this role (SEC-102);
* the migrate role holds only the migration database credential (SEC-089).

This module holds non-secret policy only: credential identifiers, the names
that carry them, and which role may hold which. It never reads, logs or
returns a credential value, and every error names variables and credential
identifiers only. The identifiers are intended to seed the central secret
registry (SEC-093), which is not implemented here.

Not enforced here (future deployment work): Redis ACL credentials (K-05,
Phase 2B, D-3), whether a value is real or synthetic (beyond refusing live
Stripe keys for the test role), and the DEV/PROD split of DVLA keys (K-14/
K-15), which stays permissive because DEV is authorised to call the
production DVLA and DVSA APIs with its own credentials.
"""

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, get_args
from urllib.parse import urlsplit

ProcessRole = Literal["api", "worker", "scheduler", "migrate", "test", "cli"]
PROCESS_ROLES: tuple[str, ...] = get_args(ProcessRole)

APP_DB_USER = "mykhaya_app"
MIGRATION_DB_USER = "mykhaya_migrator"
ADMIN_DB_USERS = frozenset({"postgres"})


@dataclass(frozen=True)
class CredentialSpec:
    """One §6.3 credential and the names that can carry it.

    ``fields`` are Settings attribute names; ``env`` are the process
    environment variables that carry it (including *_FILE variants and
    variables that are not Settings fields, such as PostgreSQL bootstrap
    passwords).
    """

    identifier: str
    label: str
    fields: tuple[str, ...] = ()
    env: tuple[str, ...] = ()


def _env(*fields: str) -> tuple[str, ...]:
    return tuple(f"MYKHAYA_{name.upper()}" for name in fields)


CREDENTIALS: dict[str, CredentialSpec] = {
    spec.identifier: spec
    for spec in (
        CredentialSpec(
            "K-01", "application secret key", ("secret_key",), _env("secret_key", "secret_key_file")
        ),
        # K-02/K-03/K-04 are carried in MYKHAYA_DATABASE_URL (by its user) and
        # by the PostgreSQL bootstrap variables below.
        CredentialSpec("K-02", "application database password", env=_env("db_password")),
        CredentialSpec("K-03", "migration database password", env=_env("migration_db_password")),
        CredentialSpec(
            "K-04",
            "PostgreSQL superuser password",
            env=("POSTGRES_PASSWORD", *_env("postgres_admin_password")),
        ),
        CredentialSpec("K-05", "Redis connection (password from Phase 2B)", env=_env("redis_url")),
        CredentialSpec("K-06", "SMTP password", ("smtp_password",), _env("smtp_password")),
        CredentialSpec(
            "K-07", "VAPID private key", ("vapid_private_key",), _env("vapid_private_key")
        ),
        CredentialSpec("K-08", "APNs private key", ("apns_private_key",), _env("apns_private_key")),
        CredentialSpec("K-09", "FCM private key", ("fcm_private_key",), _env("fcm_private_key")),
        CredentialSpec(
            "K-10",
            "Apple sign-in key",
            ("apple_private_key", "apple_private_key_file"),
            _env("apple_private_key", "apple_private_key_file"),
        ),
        CredentialSpec(
            "K-11", "Google client secret", ("google_client_secret",), _env("google_client_secret")
        ),
        CredentialSpec(
            "K-12", "Stripe secret key", ("stripe_secret_key",), _env("stripe_secret_key")
        ),
        CredentialSpec(
            "K-13",
            "Stripe webhook secret",
            ("stripe_webhook_secret",),
            _env("stripe_webhook_secret"),
        ),
        CredentialSpec("K-14", "DVLA UAT API key", ("dvla_uat_api_key",), _env("dvla_uat_api_key")),
        CredentialSpec(
            "K-15",
            "DVLA production API key",
            ("dvla_production_api_key",),
            _env("dvla_production_api_key"),
        ),
        CredentialSpec(
            "K-16",
            "DVSA client ID, client secret and API key",
            ("dvsa_client_id", "dvsa_client_secret", "dvsa_api_key"),
            _env("dvsa_client_id", "dvsa_client_secret", "dvsa_api_key"),
        ),
        CredentialSpec(
            "K-17",
            "monitoring watchdog URL",
            ("monitoring_watchdog_url",),
            _env("monitoring_watchdog_url"),
        ),
        CredentialSpec(
            "K-18",
            "field-encryption keyring",
            ("field_encryption_keys",),
            _env("field_encryption_keys", "field_encryption_keys_file"),
        ),
        CredentialSpec(
            "K-19",
            "blind-index keyring",
            ("blind_index_keys",),
            _env("blind_index_keys", "blind_index_keys_file"),
        ),
    )
}

# §6.3 grants. K-05 (Redis ACL) is Phase 2B and not granted or enforced for
# application roles yet. "cli" has no §6.3 row: it is administrative tooling
# run with the API's configuration, so it follows the API row (interim, pending
# an approved matrix entry). "test" holds synthetic values only and is checked
# separately (synthetic_role_violations).
ROLE_GRANTS: dict[str, frozenset[str]] = {
    "api": frozenset(
        {
            "K-01",
            "K-02",
            "K-06",
            "K-07",
            "K-10",
            "K-11",
            "K-12",
            "K-13",
            "K-14",
            "K-15",
            "K-16",
            "K-18",
            "K-19",
        }
    ),
    "worker": frozenset({"K-01", "K-02", "K-06", "K-07", "K-08", "K-09", "K-18", "K-19"}),
    "scheduler": frozenset({"K-01", "K-02", "K-06", "K-12", "K-17", "K-18", "K-19"}),
    "migrate": frozenset({"K-03"}),
}
ROLE_GRANTS["cli"] = ROLE_GRANTS["api"]

# Non-secret "is it configured" switches. The migrate role must not receive
# them (SEC-089); the scheduler uses the SEC-101 presence flags instead of the
# provider credentials.
PRESENCE_FLAGS: tuple[str, ...] = _env(
    "email_delivery_configured",
    "push_delivery_configured",
    "apns_delivery_configured",
    "fcm_delivery_configured",
    "stripe_billing_configured",
    "dvla_api_key_present",
    "dvsa_credentials_present",
    "stripe_webhook_secret_present",
)
# Any other credential-shaped variable is unrelated to migrations.
_SECRET_SUFFIXES = (
    "_PASSWORD",
    "_SECRET",
    "_SECRET_KEY",
    "_PRIVATE_KEY",
    "_API_KEY",
    "_KEY_FILE",
    "_KEYS",
    "_KEYS_FILE",
)


class ProcessRoleError(ValueError):
    """Raised for a configuration that violates its process role. Safe to log."""


def normalise_role(value: object) -> object:
    """A blank MYKHAYA_PROCESS_ROLE means unset (legacy behaviour)."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


def grants(role: str | None, identifier: str) -> bool:
    """True when this process may hold the credential. Unset role: everything,
    exactly as before roles existed."""
    if role is None or role == "test":
        return True
    return identifier in ROLE_GRANTS[role]


def database_user(url: str) -> str | None:
    try:
        return urlsplit(url).username
    except ValueError:
        return None


def database_url_has_password(url: str) -> bool:
    try:
        return bool(urlsplit(url).password)
    except ValueError:
        return False


def _is_present(value: object) -> bool:
    if value is None:
        return False
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        value = getter()
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _describe(violations: Iterable[tuple[str, str]]) -> str:
    return ", ".join(f"{name} ({identifier})" for name, identifier in sorted(set(violations)))


def application_role_violations(
    role: str,
    values: Mapping[str, object],
    *,
    database_url: str,
    database_url_explicit: bool,
    environ: Mapping[str, str] | None = None,
) -> list[str]:
    """Problems for an application process (api, worker, scheduler, cli).

    ``values`` maps Settings field names to their loaded values, so a
    credential supplied by environment variable, .env file, keyword argument
    or *_FILE source is seen the same way. Only names are reported.
    """
    environ = os.environ if environ is None else environ
    problems: list[str] = []
    forbidden: list[tuple[str, str]] = []
    for identifier, spec in CREDENTIALS.items():
        if grants(role, identifier) or identifier == "K-05":
            continue
        for field in spec.fields:
            if _is_present(values.get(field)):
                forbidden.append((f"MYKHAYA_{field.upper()}", identifier))
        if identifier in ("K-03", "K-04"):
            forbidden.extend(
                (name, identifier) for name in spec.env if _is_present(environ.get(name))
            )

    user = database_user(database_url)
    if user == MIGRATION_DB_USER:
        forbidden.append(("MYKHAYA_DATABASE_URL", "K-03"))
    elif user in ADMIN_DB_USERS:
        forbidden.append(("MYKHAYA_DATABASE_URL", "K-04"))
    if forbidden:
        problems.append(f"must not receive {_describe(forbidden)}")
    if (
        not database_url_explicit
        or user != APP_DB_USER
        or not database_url_has_password(database_url)
    ):
        problems.append(
            f"requires MYKHAYA_DATABASE_URL with the {APP_DB_USER} database role (K-02)"
        )
    return problems


def scheduler_presence_problems(values: Mapping[str, object]) -> list[str]:
    """SEC-101: a scheduler states provider presence explicitly whenever the
    non-secret selector says the provider is in use, so a missing flag can
    never silently turn a monitoring check into "not configured"."""
    problems: list[str] = []
    if values.get("dvla_environment") is not None and values.get("dvla_api_key_present") is None:
        problems.append(
            "requires MYKHAYA_DVLA_API_KEY_PRESENT when MYKHAYA_DVLA_ENVIRONMENT is set"
        )
    if (values.get("dvsa_enabled") or values.get("dvsa_token_url")) and values.get(
        "dvsa_credentials_present"
    ) is None:
        problems.append(
            "requires MYKHAYA_DVSA_CREDENTIALS_PRESENT when DVSA is enabled or configured"
        )
    return problems


def synthetic_role_violations(values: Mapping[str, object]) -> list[str]:
    """The test role holds synthetic values only. Whether a value is real
    cannot be proven in general; what can be checked is checked."""
    problems: list[str] = []
    if values.get("environment") != "test":
        problems.append("requires MYKHAYA_ENVIRONMENT=test")
    secret = values.get("stripe_secret_key")
    getter = getattr(secret, "get_secret_value", None)
    raw = getter() if callable(getter) else secret
    if isinstance(raw, str) and raw.startswith(("sk_live_", "rk_live_")):
        problems.append("must not receive a live Stripe key (K-12)")
    return problems


def migrate_role_violations(
    environ: Mapping[str, str], *, database_url: str, database_url_explicit: bool
) -> list[str]:
    """SEC-089: the migrate role holds the migration database credential and
    nothing else: no application key (K-01, D-4), no Redis (K-05), no other
    credential and no presence flag."""
    problems: list[str] = []
    forbidden: list[tuple[str, str]] = []
    for identifier, spec in CREDENTIALS.items():
        if identifier == "K-03":
            continue
        forbidden.extend((name, identifier) for name in spec.env if _is_present(environ.get(name)))
    forbidden.extend(
        (name, "presence flag") for name in PRESENCE_FLAGS if _is_present(environ.get(name))
    )
    known = {name for spec in CREDENTIALS.values() for name in spec.env}
    for name, value in environ.items():
        if (
            _is_present(value)
            and name.startswith("MYKHAYA_")
            and name not in known
            and name != "MYKHAYA_DATABASE_URL"
            and name.endswith(_SECRET_SUFFIXES)
        ):
            forbidden.append((name, "unrelated credential"))
    if forbidden:
        problems.append(f"must not receive {_describe(forbidden)}")
    user = database_user(database_url)
    if (
        not database_url_explicit
        or user != MIGRATION_DB_USER
        or not database_url_has_password(database_url)
    ):
        problems.append(
            f"requires MYKHAYA_DATABASE_URL with the {MIGRATION_DB_USER} database role (K-03)"
        )
    return problems


def raise_if_problems(role: str, problems: list[str]) -> None:
    if problems:
        raise ProcessRoleError(f"MYKHAYA_PROCESS_ROLE={role}: " + "; ".join(problems))
