"""Safety and package-format tests for the one-off Home migration utility."""

import hashlib
import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import Group, OutboxEvent
from mykhaya.tools.home_migration import (
    FORMAT,
    VERSION,
    MigrationError,
    _canonical_payload,
    _existing_users_by_normalized_email,
    _export_row,
    _rewrite,
    _table,
    import_home,
    validate_package,
)


@pytest.fixture
async def auth_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://localhost:8080",
        headers={"Origin": "http://localhost:8080"},
    ) as value:
        yield value


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
        "environment_mappings": {"holiday_sources": []},
        "manifest": {
            "record_counts": {},
            "asset_count": 0,
            "assets": [],
            "classified_tables": 0,
            "excluded_tables": [],
        },
    }
    value["integrity_sha256"] = hashlib.sha256(_canonical_payload(value)).hexdigest()
    return value


def test_valid_package_has_integrity_check() -> None:
    validate_package(package())


def test_current_schema_has_explicit_migration_coverage() -> None:
    from mykhaya.tools.home_migration import validate_schema_coverage

    validate_schema_coverage()


def test_corrupt_package_is_rejected() -> None:
    value = package()
    value["source_home_id"] = str(uuid.uuid4())
    with pytest.raises(MigrationError, match="integrity"):
        validate_package(value)


def test_manifest_record_count_tampering_is_rejected() -> None:
    value = package()
    value["manifest"] = {
        "record_counts": {"todos": 1},
        "asset_count": 0,
        "assets": [],
    }
    value["integrity_sha256"] = hashlib.sha256(_canonical_payload(value)).hexdigest()
    with pytest.raises(MigrationError, match="record counts"):
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


def _rehearsal_package(email: str) -> dict[str, object]:
    source_home_id = uuid.uuid4()
    source_user_id = uuid.uuid4()
    package_value = package()
    package_value.update(
        {
            "source_home_id": str(source_home_id),
            "home": {"created_by": str(source_user_id), "name": f"Rehearsal {email}"},
            "members": [
                {
                    "id": str(source_user_id),
                    "email": email,
                    "display_name": "Migrated Rehearsal User",
                    "email_verified_at": datetime.now(UTC).isoformat(),
                    "is_active": True,
                }
            ],
            "data": {
                "group_memberships": [
                    {
                        "id": str(uuid.uuid4()),
                        "group_id": str(source_home_id),
                        "user_id": str(source_user_id),
                        "role": "owner",
                        "relationship": "home_admin",
                        "permission_profile": "home_admin",
                        "permission_overrides": {},
                        "shared_resources": [],
                        "family_sponsorship_decided": None,
                        "colour": None,
                        "removed_at": None,
                    }
                ]
            },
        }
    )
    package_value["manifest"] = {
        "record_counts": {"group_memberships": 1},
        "asset_count": 0,
        "assets": [],
        "classified_tables": 0,
        "excluded_tables": [],
    }
    package_value["integrity_sha256"] = hashlib.sha256(
        _canonical_payload(package_value)
    ).hexdigest()
    return package_value


@pytest.mark.asyncio
async def test_two_home_rehearsal_and_migrated_account_password_recovery(
    auth_client: AsyncClient,
) -> None:
    """Exercise two independent imports, then the unchanged forgot/reset/login flow."""
    settings = get_settings().model_copy(update={"environment": "production"})
    first_email = f"rehearsal-one-{uuid.uuid4().hex}@example.com"
    second_email = f"rehearsal-two-{uuid.uuid4().hex}@example.com"
    first = _rehearsal_package(first_email)
    second = _rehearsal_package(second_email)

    first_report = await import_home(
        first, settings, dry_run=False, target_environment="production", confirm=True
    )
    second_report = await import_home(
        second, settings, dry_run=False, target_environment="production", confirm=True
    )
    assert first_report["status"] == second_report["status"] == "IMPORTED"
    assert first_report["reconciliation"]["status"] == "VERIFIED"
    assert second_report["reconciliation"]["status"] == "VERIFIED"
    assert first_report["target_home_id"] != second_report["target_home_id"]

    forgot = await auth_client.post("/api/v1/auth/forgot-password", json={"email": first_email})
    assert forgot.status_code == 202
    async with SessionFactory() as db:
        outbox = (
            await db.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.topic == "notification.email",
                    OutboxEvent.payload["recipient_email"].as_string() == first_email,
                )
                .order_by(OutboxEvent.created_at.desc())
            )
        ).first()
        assert outbox is not None
        match = re.search(r"token=([^\s<]+)", outbox.payload["body"])
        assert match is not None
        reset_token = match.group(1)

    reset = await auth_client.post(
        "/api/v1/auth/reset-password",
        json={"token": reset_token, "password": "A new isolated rehearsal password!"},
    )
    assert reset.status_code == 200
    login = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": first_email, "password": "A new isolated rehearsal password!"},
    )
    assert login.status_code == 200
    homes = await auth_client.get("/api/v1/groups")
    assert homes.status_code == 200
    assert {item["id"] for item in homes.json()} == {first_report["target_home_id"]}

    async with SessionFactory() as db:
        assert await db.scalar(select(Group.id).where(Group.id == second_report["target_home_id"]))
