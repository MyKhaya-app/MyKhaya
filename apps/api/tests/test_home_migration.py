"""Safety and package-format tests for the one-off Home migration utility."""

import asyncio
import base64
import hashlib
import json
import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, insert, select, text
from sqlalchemy.exc import IntegrityError

import mykhaya.tools.home_migration as home_migration
from mykhaya.avatars.storage import LocalAvatarStorage
from mykhaya.config import Settings, get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.managed_demo_homes import ManagedDemoService
from mykhaya.models import (
    AuthIdentity,
    Group,
    HouseholdListItem,
    HouseholdListSection,
    ManagedDemoType,
    Membership,
    OutboxEvent,
    User,
)
from mykhaya.security import password_hash
from mykhaya.tools.home_migration import (
    FORMAT,
    VERSION,
    MigrationError,
    MigrationReplayError,
    _canonical_payload,
    _existing_users_by_normalized_email,
    _export_row,
    _import_plan_issues,
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
    selected.update(
        {
            "meals": {"meal"},
            "wishlists": {"wishlist"},
            "budget_profiles": {"profile"},
        }
    )
    assert _row_matches_home_hierarchy(
        "meal_ingredients",
        {"meal_id": "meal"},
        home_id,
        member_ids,
        selected,
    )
    assert _row_matches_home_hierarchy(
        "wishlist_items",
        {"wishlist_id": "wishlist"},
        home_id,
        member_ids,
        selected,
    )
    assert _row_matches_home_hierarchy(
        "budget_months",
        {"profile_id": "profile"},
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


def test_excluded_external_share_relationship_is_not_safe() -> None:
    value = package()
    value["data"] = {
        "wishlist_item_reservations": [
            {"id": str(uuid.uuid4()), "actor_share_id": str(uuid.uuid4())}
        ]
    }
    assert _migration_policy_issues(value) == [
        "wishlist_item_reservations.actor_share_id contains an unresolved required relationship"
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


def test_import_plan_rejects_duplicate_one_to_one_rows() -> None:
    value = _rehearsal_package(f"duplicate-prefs-{uuid.uuid4().hex}@example.com")
    user_id = value["members"][0]["id"]
    value["data"]["notification_preferences"] = [
        {"id": str(uuid.uuid4()), "user_id": user_id, "push_enabled": True},
        {"id": str(uuid.uuid4()), "user_id": user_id, "push_enabled": False},
    ]
    issues = _import_plan_issues(
        value,
        {str(user_id): uuid.uuid4()},
    )
    assert any("notification_preferences" in issue for issue in issues)


def _list_hierarchy_package(email: str) -> dict[str, object]:
    value = _rehearsal_package(email)
    source_home_id = uuid.UUID(str(value["source_home_id"]))
    source_user_id = uuid.UUID(str(value["members"][0]["id"]))
    list_id = uuid.uuid4()
    section_id = uuid.uuid4()
    item_id = uuid.uuid4()
    preferences_id = uuid.uuid4()
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
            "notification_preferences": [
                {
                    "id": str(preferences_id),
                    "user_id": str(source_user_id),
                    "push_enabled": False,
                    "in_app_enabled": True,
                    "email_enabled": True,
                    "event_reminders_enabled": False,
                    "default_event_reminder_enabled": True,
                    "default_event_reminder_minutes": 15,
                    "all_day_reminder_enabled": True,
                    "all_day_reminder_time": "08:15:00",
                    "default_calendar_id": None,
                    "week_starts_on": "sunday",
                    "show_declined_events": True,
                    "event_invitations_enabled": False,
                    "event_changes_enabled": False,
                    "household_reminders_enabled": False,
                    "list_assignments_enabled": False,
                    "wishlist_sharing_enabled": False,
                    "daily_briefing_enabled": True,
                    "briefing_time": "06:45:00",
                    "briefing_days": "weekdays",
                    "empty_day_briefing_enabled": False,
                    "daily_nudge_summary_enabled": False,
                    "daily_nudge_summary_time": "07:15:00",
                    "nudges_evening_cleanup_enabled": False,
                    "nudges_evening_time": "21:15:00",
                    "nudges_day_complete_enabled": False,
                    "lock_screen_preview_level": "hidden",
                    "quiet_hours_start": "22:00:00",
                    "quiet_hours_end": "06:30:00",
                    "quiet_hours_critical_only": False,
                }
            ],
        }
    )
    value["manifest"]["record_counts"] = {name: len(rows) for name, rows in value["data"].items()}
    value["integrity_sha256"] = hashlib.sha256(_canonical_payload(value)).hexdigest()
    return value


def _asset_fault_package(tmp_path: Path) -> tuple[dict[str, object], Settings]:
    value = _list_hierarchy_package(f"asset-fault-{uuid.uuid4().hex}@example.com")
    source_user_id = value["members"][0]["id"]
    second_user_id = str(uuid.uuid4())
    value["members"].append(
        {
            "id": second_user_id,
            "email": f"asset-fault-second-{uuid.uuid4().hex}@example.com",
            "display_name": "Second Asset User",
            "email_verified_at": datetime.now(UTC).isoformat(),
            "is_active": True,
        }
    )
    value["data"]["group_memberships"].append(
        {
            **value["data"]["group_memberships"][0],
            "id": str(uuid.uuid4()),
            "user_id": second_user_id,
        }
    )
    content = base64.b64encode(b"synthetic disposable avatar bytes").decode("ascii")
    value["files"] = [
        {
            "kind": "avatar",
            "owner_id": second_user_id,
            "key": "source-avatar-one.webp",
            "content": content,
            "size_bytes": len(base64.b64decode(content)),
            "sha256": hashlib.sha256(base64.b64decode(content)).hexdigest(),
        },
        {
            "kind": "avatar",
            "owner_id": source_user_id,
            "key": "source-avatar-two.webp",
            "content": content,
            "size_bytes": len(base64.b64decode(content)),
            "sha256": hashlib.sha256(base64.b64decode(content)).hexdigest(),
        },
    ]
    value["manifest"]["asset_count"] = 2
    value["manifest"]["record_counts"] = {name: len(rows) for name, rows in value["data"].items()}
    value["manifest"]["assets"] = [
        {
            "kind": asset["kind"],
            "owner_id": asset["owner_id"],
            "size_bytes": asset["size_bytes"],
            "sha256": asset["sha256"],
        }
        for asset in value["files"]
    ]
    value["integrity_sha256"] = hashlib.sha256(_canonical_payload(value)).hexdigest()
    settings = get_settings().model_copy(
        update={
            "environment": "production",
            "avatar_storage_dir": str(tmp_path / "avatars"),
            "meal_image_storage_dir": str(tmp_path / "meals"),
            "vehicle_photo_storage_dir": str(tmp_path / "vehicles"),
        }
    )
    return value, settings


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
        preferences = _table("notification_preferences")
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
        target_preferences = (
            (await db.execute(select(preferences).where(preferences.c.user_id == target_user)))
            .mappings()
            .one()
        )
        assert target_preferences["id"] != uuid.UUID(
            complete["data"]["notification_preferences"][0]["id"]
        )
        assert target_preferences["push_enabled"] is False
        assert target_preferences["default_event_reminder_minutes"] == 15
        assert target_preferences["week_starts_on"] == "sunday"

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


@pytest.mark.asyncio
async def test_complete_postgres_home_migration_acceptance_rehearsal(tmp_path: Path) -> None:
    """Run one real export/preflight/import across the complete showcase fixture.

    The Ultimate showcase is the repository's maintained synthetic fixture for
    every currently supported customer module.  This test deliberately uses
    its ordinary model seeders, the production exporter/importer, and the
    disposable storage seams rather than mocked database operations.
    Tables outside TABLE_ORDER (auth/session/MFA, PCC ledgers, notifications,
    audit/outbox, billing provider state, external-share grants and provider
    caches) remain intentionally excluded by the migration contract.
    """
    # conftest roots the shared settings object and the showcase seeders in the
    # same per-test disposable directories; preserve those roots for export and
    # import instead of copying different storage paths.
    settings = get_settings().model_copy(update={"environment": "development"})
    fixture_key = f"migration-acceptance-{uuid.uuid4().hex}"
    owner_email = f"acceptance-owner-{uuid.uuid4().hex}@example.com"

    async with SessionFactory() as db:
        source = await ManagedDemoService.create(
            db,
            fixture_key=fixture_key,
            display_name="Migration Acceptance Source",
            fixture_type=ManagedDemoType.ultimate_demo,
            email=owner_email,
            password="Synthetic-only acceptance password!",
            created_by=None,
            reference_date=datetime(2026, 1, 15, tzinfo=UTC).date(),
        )
        removed = User(
            email=f"removed-{uuid.uuid4().hex}@example.com",
            display_name="Removed Historical Member",
            is_active=True,
        )
        external = User(
            email=f"external-{uuid.uuid4().hex}@example.net",
            display_name="External Share Recipient",
            is_active=True,
        )
        db.add_all([removed, external])
        await db.flush()
        db.add(
            Membership(
                group_id=source.home_id,
                user_id=removed.id,
                role="member",
                relationship="partner",
                permission_profile="standard_partner",
                removed_at=datetime(2025, 12, 1, tzinfo=UTC),
            )
        )
        source_list = await db.scalar(
            select(_table("household_lists").c.id).where(
                _table("household_lists").c.group_id == source.home_id
            )
        )
        assert source_list is not None
        source_section = HouseholdListSection(
            list_id=source_list,
            name="Acceptance section",
            position=0,
        )
        db.add(source_section)
        await db.flush()
        source_item = await db.scalar(
            select(HouseholdListItem).where(HouseholdListItem.list_id == source_list)
        )
        assert source_item is not None
        source_item.section_id = source_section.id
        active_user_ids = list(
            await db.scalars(
                select(Membership.user_id).where(
                    Membership.group_id == source.home_id,
                    Membership.removed_at.is_(None),
                )
            )
        )
        existing_identity_ids = set(await db.scalars(select(AuthIdentity.user_id)))
        db.add_all(
            [
                AuthIdentity(
                    user_id=user_id,
                    password_hash=password_hash.hash("Synthetic-only account password!"),
                )
                for user_id in active_user_ids
                if user_id not in existing_identity_ids
            ]
        )
        await db.commit()

    package_path = tmp_path / "home-migration.json"
    exported = await export_home(source.home_id, package_path, settings)
    validate_package(exported)
    assert len(exported["members"]) == 4
    exported_emails = {member["email"] for member in exported["members"]}
    assert removed.email not in exported_emails
    assert external.email not in exported_emails
    assert exported["files"]
    assert {name for name, rows in exported["data"].items() if rows} >= {
        "group_memberships",
        "home_calendars",
        "calendar_events",
        "household_routines",
        "reminders",
        "todos",
        "meals",
        "meal_plan_entries",
        "household_lists",
        "household_list_sections",
        "household_list_items",
        "wishlists",
        "wishlist_items",
        "budget_profiles",
        "budget_months",
        "child_profiles",
        "vehicles",
        "notification_preferences",
    }
    assert not exported["data"].get("calendar_shares")
    assert not exported["data"].get("wishlist_shares")

    # Turn the exported Home into an independent destination rehearsal.  Only
    # disposable source rows are removed; the source asset bytes remain in the
    # per-test storage so the actual import transfer is exercised.
    source_user_ids = [uuid.UUID(member["id"]) for member in exported["members"]]
    async with SessionFactory() as db:
        await db.execute(
            delete(_table("managed_demo_homes")).where(
                _table("managed_demo_homes").c.home_id == source.home_id
            )
        )
        await db.execute(delete(_table("groups")).where(_table("groups").c.id == source.home_id))
        await db.execute(delete(_table("users")).where(_table("users").c.id.in_(source_user_ids)))
        destination_owner = User(
            email=owner_email,
            display_name="Existing Destination Owner",
            is_active=True,
            email_verified_at=datetime.now(UTC),
        )
        db.add(destination_owner)
        await db.flush()
        db.add(
            AuthIdentity(
                user_id=destination_owner.id,
                password_hash=password_hash.hash("Existing destination password!"),
            )
        )
        await db.commit()

    production_settings = settings.model_copy(update={"environment": "production"})
    dry_run = await import_home(
        exported,
        production_settings,
        dry_run=True,
        target_environment="production",
        confirm=True,
    )
    assert dry_run["status"] == "READY_TO_IMPORT", dry_run["warnings"]

    imported = await import_home(
        exported,
        production_settings,
        dry_run=False,
        target_environment="production",
        confirm=True,
    )
    assert imported["status"] == "IMPORTED"
    reconciliation = imported["reconciliation"]
    assert reconciliation["status"] == "VERIFIED"
    assert reconciliation["files_verified"] == len(exported["files"])
    assert reconciliation["broken_relationships"] == 0
    assert all(
        row["source"] == row["destination"] for row in reconciliation["table_counts"].values()
    )

    async with SessionFactory() as db:
        destination_home = uuid.UUID(imported["target_home_id"])
        groups = _table("groups")
        memberships = _table("group_memberships")
        users = _table("users")
        assert await db.scalar(select(groups.c.id).where(groups.c.id == source.home_id)) is None
        assert (
            await db.scalar(
                select(memberships.c.id).where(memberships.c.group_id == destination_home)
            )
            is not None
        )
        assert await db.scalar(select(users.c.id).where(users.c.email == removed.email)) is not None
        assert (
            await db.scalar(select(users.c.id).where(users.c.email == external.email)) is not None
        )
        assert (
            await db.scalar(
                select(memberships.c.id)
                .join(users, memberships.c.user_id == users.c.id)
                .where(
                    memberships.c.group_id == destination_home,
                    users.c.email.in_([removed.email, external.email]),
                )
            )
            is None
        )
        assert (
            await db.scalar(
                select(memberships.c.id).where(
                    memberships.c.group_id == destination_home,
                    memberships.c.removed_at.is_(None),
                )
            )
            is not None
        )


def _file_set(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in root.rglob("*") if path.is_file()}


@pytest.mark.asyncio
async def test_asset_copy_failure_after_first_copy_rolls_back_and_cleans_assets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    candidate, settings = _asset_fault_package(tmp_path)
    avatar_root = Path(settings.avatar_storage_dir)
    await asyncio.to_thread(avatar_root.mkdir, parents=True)
    pre_existing = avatar_root / "pre-existing.webp"
    await asyncio.to_thread(pre_existing.write_bytes, b"must remain untouched")
    before_files = _file_set(tmp_path)
    original_save = LocalAvatarStorage.save
    calls = 0

    async def fail_on_second_copy(self: LocalAvatarStorage, key: str, data: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            await original_save(self, key, data)
            return
        raise OSError("controlled disposable asset-copy failure")

    monkeypatch.setattr(LocalAvatarStorage, "save", fail_on_second_copy)
    with pytest.raises(OSError, match="controlled disposable asset-copy failure"):
        await import_home(
            candidate, settings, dry_run=False, target_environment="production", confirm=True
        )

    assert calls >= 2
    assert _file_set(tmp_path) == before_files
    assert await asyncio.to_thread(pre_existing.read_bytes) == b"must remain untouched"
    async with SessionFactory() as db:
        users = _table("users")
        groups = _table("groups")
        ledger = _table("home_migration_ledger")
        email = candidate["members"][0]["email"]
        home_name = candidate["home"]["name"]
        assert await db.scalar(select(users.c.id).where(users.c.email == email)) is None
        assert await db.scalar(select(groups.c.id).where(groups.c.name == home_name)) is None
        assert (
            await db.scalar(
                select(ledger.c.id).where(
                    ledger.c.migration_id == uuid.UUID(candidate["migration_id"])
                )
            )
            is None
        )
    validate_package(candidate)
    monkeypatch.setattr(LocalAvatarStorage, "save", original_save)
    retry = await import_home(
        candidate, settings, dry_run=False, target_environment="production", confirm=True
    )
    assert retry["status"] == "IMPORTED"
    assert retry["reconciliation"]["status"] == "VERIFIED"


@pytest.mark.asyncio
async def test_reconciliation_failure_rolls_back_rows_and_assets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    candidate, settings = _asset_fault_package(tmp_path)
    avatar_root = Path(settings.avatar_storage_dir)
    await asyncio.to_thread(avatar_root.mkdir, parents=True)
    pre_existing = avatar_root / "pre-existing.webp"
    await asyncio.to_thread(pre_existing.write_bytes, b"must remain untouched")
    before_files = _file_set(tmp_path)
    original_reconcile = home_migration._reconcile_import

    async def report_mismatch(*args: object, **kwargs: object) -> dict[str, object]:
        report = await original_reconcile(*args, **kwargs)
        report["status"] = "VERIFICATION_FAILED"
        report["destination_records"] = report["source_records"] + 1
        return report

    monkeypatch.setattr(home_migration, "_reconcile_import", report_mismatch)
    with pytest.raises(MigrationError, match="Post-import reconciliation failed"):
        await import_home(
            candidate, settings, dry_run=False, target_environment="production", confirm=True
        )

    assert _file_set(tmp_path) == before_files
    assert await asyncio.to_thread(pre_existing.read_bytes) == b"must remain untouched"
    async with SessionFactory() as db:
        users = _table("users")
        groups = _table("groups")
        ledger = _table("home_migration_ledger")
        email = candidate["members"][0]["email"]
        home_name = candidate["home"]["name"]
        assert await db.scalar(select(users.c.id).where(users.c.email == email)) is None
        assert await db.scalar(select(groups.c.id).where(groups.c.name == home_name)) is None
        assert (
            await db.scalar(
                select(ledger.c.id).where(
                    ledger.c.migration_id == uuid.UUID(candidate["migration_id"])
                )
            )
            is None
        )
    validate_package(candidate)
    monkeypatch.setattr(home_migration, "_reconcile_import", original_reconcile)
    retry = await import_home(
        candidate, settings, dry_run=False, target_environment="production", confirm=True
    )
    assert retry["status"] == "IMPORTED"
    assert retry["reconciliation"]["status"] == "VERIFIED"
