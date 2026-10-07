import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_platform_control_centre import (
    TEST_CLIENT_IP,
    TEST_PROXY_PEER,
    create_admin,
    login,
    unsafe,
)

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.home_migration_pcc import (
    migration_enabled,
    package_checksum,
    package_summary,
    store_package,
)
from mykhaya.main import app
from mykhaya.models import (
    AdministrativeAuditEvent,
    PlatformAdministrator,
    PlatformRole,
    PlatformSession,
    PlatformSetting,
    SecurityEvent,
)
from mykhaya.tools.home_migration import MigrationError


@pytest_asyncio.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    origin = get_settings().admin_url
    async with AsyncClient(
        transport=ASGITransport(app=app, client=(TEST_PROXY_PEER, 44000)),
        base_url=origin,
        headers={"Origin": origin, "X-Forwarded-For": TEST_CLIENT_IP},
    ) as value:
        yield value


@pytest_asyncio.fixture
async def admin_factory() -> AsyncIterator[
    Callable[[PlatformRole], Awaitable[PlatformAdministrator]]
]:
    identifiers: list[uuid.UUID] = []

    async def factory(role: PlatformRole = PlatformRole.owner) -> PlatformAdministrator:
        row = await create_admin(role)
        identifiers.append(row.id)
        return row

    yield factory
    async with SessionFactory() as db:
        await db.execute(
            PlatformSession.__table__.delete().where(
                PlatformSession.administrator_id.in_(identifiers)
            )
        )
        await db.execute(
            AdministrativeAuditEvent.__table__.delete().where(
                AdministrativeAuditEvent.administrator_id.in_(identifiers)
            )
        )
        await db.execute(
            SecurityEvent.__table__.delete().where(SecurityEvent.administrator_id.in_(identifiers))
        )
        await db.execute(
            PlatformAdministrator.__table__.delete().where(
                PlatformAdministrator.id.in_(identifiers)
            )
        )
        await db.commit()


def test_home_migration_is_default_off_without_a_platform_setting() -> None:
    assert migration_enabled(None) is False
    assert migration_enabled({"value": False}) is False
    assert migration_enabled({"value": True}) is True


def test_package_summary_and_checksum_exclude_no_personal_payload_from_state() -> None:
    package = {
        "format": "mykhaya-home-migration",
        "version": 1,
        "migration_id": "11111111-1111-1111-1111-111111111111",
        "source_environment": "development",
        "source_home_id": "22222222-2222-2222-2222-222222222222",
        "exported_at": "2026-01-01T00:00:00+00:00",
        "members": [
            {"id": "33333333-3333-3333-3333-333333333333", "email": "redacted@example.test"}
        ],
        "data": {"todos": [{"id": "44444444-4444-4444-4444-444444444444"}]},
        "files": [{"kind": "avatar", "key": "avatar.jpg", "content": "bytes"}],
        "integrity_sha256": "ignored-by-canonical-checksum",
    }
    summary = package_summary(package)
    assert summary["member_count"] == 1
    assert summary["asset_count"] == 1
    assert summary["counts"] == {"todos": 1}
    assert package_checksum(package) == package_checksum(
        {**package, "integrity_sha256": "different"}
    )


@pytest.mark.asyncio
async def test_package_storage_failure_is_reported_without_exposing_filesystem_details(
    tmp_path, caplog
) -> None:
    storage_root = tmp_path / "storage-file"
    storage_root.write_text("not a directory", encoding="utf-8")
    package = {
        "format": "mykhaya-home-migration",
        "version": 1,
        "migration_id": "11111111-1111-1111-1111-111111111111",
        "source_environment": "development",
        "source_home_id": "22222222-2222-2222-2222-222222222222",
        "exported_at": "2026-01-01T00:00:00+00:00",
        "home": {"id": "22222222-2222-2222-2222-222222222222", "name": "Test Home"},
        "members": [
            {"id": "33333333-3333-3333-3333-333333333333", "email": "redacted@example.test"}
        ],
        "data": {"todos": []},
        "files": [],
    }
    package["integrity_sha256"] = package_checksum(package)
    settings = get_settings().model_copy(update={"home_migration_storage_dir": str(storage_root)})

    with pytest.raises(
        MigrationError,
        match=(
            "Migration package storage is unavailable. "
            "Check the Home Migration storage configuration."
        ),
    ):
        await store_package(None, settings, package, created_by=uuid.uuid4())

    assert str(storage_root) not in caplog.text


@pytest.mark.asyncio
async def test_setting_is_enforced_through_the_authenticated_pcc_api(
    admin_client, admin_factory
) -> None:
    admin = await admin_factory()
    await login(admin_client, admin)
    async with SessionFactory() as db:
        previous = await db.scalar(
            select(PlatformSetting).where(PlatformSetting.key == "home_migration_enabled")
        )
        previous_value = dict(previous.value) if previous else None
        if previous is None:
            previous = PlatformSetting(key="home_migration_enabled", value={"value": False})
            db.add(previous)
        else:
            previous.value = {"value": False}
        await db.commit()
    try:
        settings = await admin_client.get("/api/v1/platform/settings")
        item = next(
            item for item in settings.json()["settings"] if item["key"] == "home_migration_enabled"
        )
        assert item["value"] is False
        blocked = await unsafe(
            admin_client,
            "POST",
            "/api/v1/platform/home-migration/preview-export",
            json={"home_id": str(uuid.uuid4())},
        )
        assert blocked.status_code == 409

        enabled = await unsafe(
            admin_client,
            "PUT",
            "/api/v1/platform/settings/home_migration_enabled",
            json={"value": True, "reason": "Enable controlled migration test", "confirmed": True},
        )
        assert enabled.status_code == 200, enabled.text
        status = await admin_client.get("/api/v1/platform/home-migration/status")
        assert status.status_code == 200
        assert status.json()["enabled"] is True

        disabled = await unsafe(
            admin_client,
            "PUT",
            "/api/v1/platform/settings/home_migration_enabled",
            json={"value": False, "reason": "Disable controlled migration test", "confirmed": True},
        )
        assert disabled.status_code == 200, disabled.text
        blocked_again = await unsafe(
            admin_client,
            "POST",
            "/api/v1/platform/home-migration/preview-export",
            json={"home_id": str(uuid.uuid4())},
        )
        assert blocked_again.status_code == 409
    finally:
        async with SessionFactory() as db:
            row = await db.scalar(
                select(PlatformSetting).where(PlatformSetting.key == "home_migration_enabled")
            )
            if previous_value is None:
                if row is not None:
                    await db.delete(row)
            elif row is not None:
                row.value = previous_value
            await db.commit()
