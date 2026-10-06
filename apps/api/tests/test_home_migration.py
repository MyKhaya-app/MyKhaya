"""Safety and package-format tests for the one-off Home migration utility."""

import hashlib
import uuid

import pytest

from mykhaya.tools.home_migration import (
    FORMAT,
    VERSION,
    MigrationError,
    _canonical_payload,
    _existing_users_by_normalized_email,
    _export_row,
    _rewrite,
    _table,
    validate_package,
)


def package() -> dict[str, object]:
    value: dict[str, object] = {
        "format": FORMAT,
        "version": VERSION,
        "migration_id": str(uuid.uuid4()),
        "exported_at": "2026-01-01T00:00:00+00:00",
        "source_environment": "development",
        "source_home_id": str(uuid.uuid4()),
        "home": {},
        "members": [],
        "data": {},
        "files": [],
    }
    value["integrity_sha256"] = hashlib.sha256(_canonical_payload(value)).hexdigest()
    return value


def test_valid_package_has_integrity_check() -> None:
    validate_package(package())


def test_corrupt_package_is_rejected() -> None:
    value = package()
    value["source_home_id"] = str(uuid.uuid4())
    with pytest.raises(MigrationError, match="integrity"):
        validate_package(value)


def test_credentials_and_unsupported_tables_are_rejected() -> None:
    value = package()
    value["data"] = {"sessions": [{"token_hash": "secret"}]}
    value["integrity_sha256"] = hashlib.sha256(_canonical_payload(value)).hexdigest()
    with pytest.raises(MigrationError, match="Unsupported or malformed|secret"):
        validate_package(value)


def test_export_row_removes_credentials_provider_ids_and_admin_ids() -> None:
    row = _export_row(
        {
            "display_name": "Member",
            "password_hash": "never",
            "external_customer_id": "cus_test",
            "created_by": str(uuid.uuid4()),
        }
    )
    assert row == {"display_name": "Member"}


def test_relationship_rewrite_uses_fresh_ids() -> None:
    table = _table("group_memberships")
    old_group = uuid.uuid4()
    old_user = uuid.uuid4()
    old_membership = uuid.uuid4()
    maps = {
        "groups": {str(old_group): uuid.uuid4()},
        "users": {str(old_user): uuid.uuid4()},
        "group_memberships": {str(old_membership): uuid.uuid4()},
    }
    row = _rewrite(
        {"id": str(old_membership), "group_id": str(old_group), "user_id": str(old_user)},
        maps,
        table,
    )
    assert row["id"] == str(maps["group_memberships"][str(old_membership)])
    assert row["group_id"] == str(maps["groups"][str(old_group)])
    assert row["user_id"] == str(maps["users"][str(old_user)])


@pytest.mark.asyncio
async def test_existing_users_are_indexed_by_normalized_email() -> None:
    class Result:
        def mappings(self):
            return self

        def __iter__(self):
            return iter([{"id": uuid.uuid4(), "email": "  Anthony@Example.com "}])

    class Database:
        async def execute(self, query):
            return Result()

    indexed = await _existing_users_by_normalized_email(Database())
    assert list(indexed) == ["anthony@example.com"]
