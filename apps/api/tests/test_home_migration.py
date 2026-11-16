"""Safety and package-format tests for the one-off Home migration utility."""

import asyncio
import hashlib
import json
import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import Group, OutboxEvent
from mykhaya.tools.home_migration import (
    FORMAT,
    VERSION,
    MigrationError,
    MigrationReplayError,
    _canonical_payload,
    _existing_users_by_normalized_email,
    _export_row,
    _is_migratable_home_row,
    _migration_policy_issues,
    _rewrite,
    _row_matches_home_hierarchy,
    _table,
    export_home,
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


def test_removed_home_memberships_are_not_migratable() -> None:
    assert _is_migratable_home_row("group_memberships", {"removed_at": None})
    assert not _is_migratable_home_row(
        "group_memberships", {"removed_at": "2026-01-01T00:00:00+00:00"}
    )
    assert _is_migratable_home_row("todos", {"removed_at": "not a membership"})


def test_external_share_rows_are_rejected_by_migration_policy() -> None:
    value = package()
    value["data"] = {"calendar_shares": [{"id": str(uuid.uuid4())}]}
    assert _migration_policy_issues(value) == [
        "calendar_shares contains external sharing grants that are not recreated"
    ]


def test_household_list_children_follow_the_home_owned_list() -> None:
    home_id = uuid.uuid4()
    member_ids = {uuid.uuid4()}
    own_list = uuid.uuid4()
    other_list = uuid.uuid4()
    selected = {"household_lists": {str(own_list)}}
    assert _row_matches_home_hierarchy(
        "household_list_sections",
        {"list_id": str(own_list)},
        home_id,
        member_ids,
        selected,
    )
    assert _row_matches_home_hierarchy(
        "household_list_items",
        {"list_id": str(own_list)},
        home_id,
        member_ids,
        selected,
    )
    assert not _row_matches_home_hierarchy(
        "household_list_sections",
        {"list_id": str(other_list)},
        home_id,
        member_ids,
        selected,
    )


def test_missing_required_household_list_section_is_not_safe() -> None:
    value = package()
    value["data"] = {
        "household_list_items": [{"id": str(uuid.uuid4()), "section_id": str(uuid.uuid4())}]
    }
    assert _migration_policy_issues(value) == [
        "household_list_items.section_id contains an unresolved required relationship"
    ]


def test_optional_external_user_reference_is_nulled() -> None:
    table = _table("calendar_events")
    old_user = uuid.uuid4()
    old_event = uuid.uuid4()
    maps = {"calendar_events": {str(old_event): uuid.uuid4()}, "users": {}}
    row = _rewrite({"id": str(old_event), "last_edited_by": str(old_user)}, maps, table)
    assert row["last_edited_by"] is None


def test_required_external_user_reference_is_blocked() -> None:
    table = _table("vehicles")
    old_user = uuid.uuid4()
    old_vehicle = uuid.uuid4()
    maps = {"vehicles": {str(old_vehicle): uuid.uuid4()}, "users": {}}
    with pytest.raises(MigrationError, match="Unmapped foreign key vehicles.owner_user_id"):
        _rewrite({"id": str(old_vehicle), "owner_user_id": str(old_user)}, maps, table)


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


def _list_hierarchy_package(email: str) -> dict[str, object]:
    value = _rehearsal_package(email)
    source_home_id = uuid.UUID(str(value["source_home_id"]))
    source_user_id = uuid.UUID(str(value["members"][0]["id"]))
    list_id = uuid.uuid4()
    section_id = uuid.uuid4()
    item_id = uuid.uuid4()
    value["data"].update(
        {
            "household_lists": [
                {
                    "id": str(list_id),
                    "group_id": str(source_home_id),
                    "name": "Groceries",
                    "icon": "cart",
                    "created_by": str(source_user_id),
                    "scope": "household",
                    "deleted_at": None,
                    "source_template_id": None,
                    "source_template_name": None,
                }
            ],
            "household_list_sections": [
                {
                    "id": str(section_id),
                    "list_id": str(list_id),
                    "name": "Fresh food",
                    "position": 0,
                }
            ],
            "household_list_items": [
                {
                    "id": str(item_id),
                    "list_id": str(list_id),
                    "section_id": str(section_id),
                    "position": 0,
                    "text": "Milk",
                    "quantity": None,
                    "note": None,
                    "assigned_member_id": None,
                    "is_checked": False,
                    "completed_at": None,
                    "completed_by": None,
                    "created_by": str(source_user_id),
                },
                {
                    "id": str(uuid.uuid4()),
                    "list_id": str(list_id),
                    "section_id": None,
                    "position": 1,
                    "text": "Unsectioned item",
                    "quantity": None,
                    "note": None,
                    "assigned_member_id": None,
                    "is_checked": False,
                    "completed_at": None,
                    "completed_by": None,
                    "created_by": str(source_user_id),
                },
            ],
        }
    )
    value["manifest"]["record_counts"] = {name: len(rows) for name, rows in value["data"].items()}
    value["integrity_sha256"] = hashlib.sha256(_canonical_payload(value)).hexdigest()
    return value


@pytest.mark.asyncio
async def test_household_list_section_fk_regression_and_import_remapping(
    tmp_path: Path,
) -> None:
    settings = get_settings().model_copy(update={"environment": "production"})
    complete = _list_hierarchy_package(f"lists-{uuid.uuid4().hex}@example.com")
    missing = json.loads(json.dumps(complete))
    missing["data"].pop("household_list_sections")
    missing["manifest"]["record_counts"] = {
        name: len(rows) for name, rows in missing["data"].items()
    }
    missing["integrity_sha256"] = hashlib.sha256(_canonical_payload(missing)).hexdigest()

    dry_run = await import_home(
        missing, settings, dry_run=True, target_environment="production", confirm=True
    )
    assert dry_run["status"] == "NOT_SAFE_TO_IMPORT"
    assert any("household_list_items.section_id" in reason for reason in dry_run["warnings"])

    imported = await import_home(
        complete, settings, dry_run=False, target_environment="production", confirm=True
    )
    assert imported["status"] == "IMPORTED"
    assert imported["reconciliation"]["status"] == "VERIFIED"

    async with SessionFactory() as db:
        lists = _table("household_lists")
        sections = _table("household_list_sections")
        items = _table("household_list_items")
        users = _table("users")
        target_user = await db.scalar(
            select(users.c.id).where(users.c.email == complete["members"][0]["email"])
        )
        target_list = (
            await db.execute(
                select(lists.c.id).where(
                    lists.c.group_id == uuid.UUID(imported["target_home_id"]),
                    lists.c.name == "Groceries",
                )
            )
        ).scalar_one()
        target_section = (
            await db.execute(select(sections.c.id).where(sections.c.list_id == target_list))
        ).scalar_one()
        target_item = (
            (
                await db.execute(
                    select(items).where(
                        items.c.list_id == target_list,
                        items.c.text == "Milk",
                    )
                )
            )
            .mappings()
            .one()
        )
        assert target_user is not None
        assert str(target_list) != str(complete["data"]["household_lists"][0]["id"])
        assert target_section != uuid.UUID(complete["data"]["household_list_sections"][0]["id"])
        assert target_item["section_id"] == target_section
        unsectioned_item = (
            (
                await db.execute(
                    select(items).where(
                        items.c.list_id == target_list,
                        items.c.text == "Unsectioned item",
                    )
                )
            )
            .mappings()
            .one()
        )
        assert unsectioned_item["section_id"] is None

        with pytest.raises(IntegrityError) as error:
            await db.execute(
                insert(items).values(
                    id=uuid.uuid4(),
                    list_id=target_list,
                    section_id=uuid.uuid4(),
                    position=1,
                    text="Broken section reference",
                    is_checked=False,
                    created_by=target_user,
                )
            )
        await db.rollback()
        original = error.value.orig
        assert getattr(original, "sqlstate", None) == "23503"
        constraint_name = (
            await db.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conname = 'fk_household_list_items_section'"
                )
            )
        ).scalar_one()
        assert constraint_name == "fk_household_list_items_section"

    exported = await export_home(
        uuid.UUID(imported["target_home_id"]),
        tmp_path / "export.json",
        settings.model_copy(update={"environment": "development"}),
    )
    assert len(exported["data"]["household_lists"]) == 1
    assert len(exported["data"]["household_list_sections"]) == 1
    assert len(exported["data"]["household_list_items"]) == 2


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


@pytest.mark.asyncio
async def test_concurrent_imports_serialize_on_migration_identity() -> None:
    settings = get_settings().model_copy(update={"environment": "production"})
    candidate = _rehearsal_package(f"concurrent-{uuid.uuid4().hex}@example.com")

    results = await asyncio.gather(
        import_home(
            candidate, settings, dry_run=False, target_environment="production", confirm=True
        ),
        import_home(
            candidate, settings, dry_run=False, target_environment="production", confirm=True
        ),
        return_exceptions=True,
    )

    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, MigrationReplayError) for result in results) == 1
