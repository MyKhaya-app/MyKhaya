"""Static guards for the process-role and secret-registry architecture (WP-4).

These fail when a credential is added without a §6.3 role allocation, when a
secret setting escapes process-role enforcement, or when the role set or the
order of the enforcing validators changes. The exact §6.3 grants are pinned
in test_process_roles.py and the registry in test_secret_registry.py.
"""

import types
from typing import Any, Union, get_args, get_origin

from pydantic import SecretStr

from mykhaya.config import MigrationSettings, Settings
from mykhaya.process_roles import CREDENTIALS, ROLE_GRANTS
from mykhaya.secret_registry import MIGRATION_SECRET_REGISTRY, SECRET_REGISTRY

# Credentials deliberately granted to no application role, with the reason.
UNALLOCATED = {
    "K-03": "migration database password: held by the migrate role only",
    "K-04": "PostgreSQL superuser password: database bootstrap only",
    "K-05": "Redis ACL credential: Phase 2B (D-3), not yet enforced",
}


def _secret_fields(model: type[Any]) -> set[str]:
    fields = set()
    for name, field in model.model_fields.items():
        annotation = field.annotation
        args = (
            get_args(annotation)
            if get_origin(annotation) in (Union, types.UnionType)
            else (annotation,)
        )
        if SecretStr in args:
            fields.add(name)
    return fields


def test_the_role_set_is_fixed() -> None:
    assert set(ROLE_GRANTS) == {"api", "worker", "scheduler", "migrate", "cli"}


def test_every_credential_has_a_documented_role_allocation() -> None:
    application_roles = ("api", "worker", "scheduler", "cli")
    for identifier in CREDENTIALS:
        held = [role for role in application_roles if identifier in ROLE_GRANTS[role]]
        if identifier in UNALLOCATED:
            assert held == [], f"{identifier} is listed as unallocated but granted to {held}"
        else:
            assert held, f"{identifier} has no §6.3 role allocation"
    assert set(UNALLOCATED) <= set(CREDENTIALS)
    assert ROLE_GRANTS["migrate"] == {"K-03"}


def test_grants_only_name_known_credentials() -> None:
    for role, grants in ROLE_GRANTS.items():
        assert grants <= set(CREDENTIALS), role


def test_every_secret_setting_is_covered_by_process_role_enforcement() -> None:
    covered = {field for spec in CREDENTIALS.values() for field in spec.fields}
    assert _secret_fields(Settings) <= covered, "map new secret settings to a K- identifier"
    assert covered <= set(Settings.model_fields)


def test_every_registry_credential_is_held_by_some_role() -> None:
    for spec in (*SECRET_REGISTRY, *MIGRATION_SECRET_REGISTRY):
        assert set(spec.authorised_roles) - {"test"}, spec.setting


def _after_validators(model: type[Any]) -> list[str]:
    decorators = model.__pydantic_decorators__.model_validators
    return [name for name, info in decorators.items() if info.info.mode == "after"]


def test_process_role_enforcement_runs_after_every_other_validator() -> None:
    assert _after_validators(Settings)[-1] == "enforce_process_role"
    assert _after_validators(MigrationSettings)[-1] == "enforce_migrate_role"


def test_secret_files_are_resolved_before_validation() -> None:
    for model in (Settings, MigrationSettings):
        decorators = model.__pydantic_decorators__.model_validators
        assert decorators["resolve_secret_files"].info.mode == "before"
