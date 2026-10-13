import io
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException, UploadFile
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
    PACKAGE_STORE,
    discard_package_file,
    migration_enabled,
    package_checksum,
    package_summary,
    purge_expired_packages,
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
from mykhaya.routers import platform as platform_router
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
async def test_oversized_package_returns_a_useful_bounded_limit_error(monkeypatch) -> None:
    limit = 3 * 1024 * 1024
    monkeypatch.setattr(platform_router, "MAX_FILE_BYTES", limit)
    monkeypatch.setattr(
        platform_router, "_home_migration_environment", lambda settings, expected: None
    )

    async def allow_migration(db, settings) -> None:
        return None

    monkeypatch.setattr(platform_router, "_home_migration_guard", allow_migration)
    context = SimpleNamespace(administrator=SimpleNamespace(id=uuid.uuid4()))

    with pytest.raises(HTTPException) as error:
        await platform_router.home_migration_upload(
            None,
            UploadFile(file=io.BytesIO(b"x" * (limit + 1))),
            context,
            None,
            None,
        )

    assert error.value.status_code == 413
    assert error.value.detail == "Migration package is too large. Maximum supported size is 3 MiB."


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


# --- Phase 2A′: download gating and package file lifecycle -------------------


def _minimal_package(migration_id: uuid.UUID) -> dict:
    package = {
        "format": "mykhaya-home-migration",
        "version": 1,
        "migration_id": str(migration_id),
        "source_environment": "development",
        "source_home_id": str(uuid.uuid4()),
        "exported_at": "2026-01-01T00:00:00+00:00",
        "home": {"id": "22222222-2222-2222-2222-222222222222", "name": "Test Home"},
        "members": [{"id": str(uuid.uuid4()), "email": "redacted@example.test"}],
        "data": {"todos": []},
        "files": [],
    }
    package["integrity_sha256"] = package_checksum(package)
    return package


async def _store(settings, created_by: uuid.UUID) -> dict:
    async with SessionFactory() as db:
        return await store_package(
            db, settings, _minimal_package(uuid.uuid4()), created_by=created_by
        )


async def _delete_package_rows(ids: list[str]) -> None:
    async with SessionFactory() as db:
        await db.execute(
            PACKAGE_STORE.delete().where(PACKAGE_STORE.c.id.in_([uuid.UUID(i) for i in ids]))
        )
        await db.commit()


async def _allow_migration(db, settings) -> None:
    return None


@pytest.mark.asyncio
async def test_package_download_requires_the_development_environment(
    admin_client, admin_factory
) -> None:
    admin = await admin_factory()
    await login(admin_client, admin)
    response = await admin_client.get(
        f"/api/v1/platform/home-migration/packages/{uuid.uuid4()}/download"
    )
    assert response.status_code == 409
    assert "available only in development" in response.json()["detail"]


@pytest.mark.asyncio
async def test_package_download_requires_home_migration_enabled(
    admin_client, admin_factory, monkeypatch
) -> None:
    monkeypatch.setattr(
        platform_router, "_home_migration_environment", lambda settings, expected: None
    )

    async def disabled(db, settings) -> None:
        raise HTTPException(409, "Home Migration is disabled.")

    monkeypatch.setattr(platform_router, "_home_migration_guard", disabled)
    admin = await admin_factory()
    await login(admin_client, admin)
    response = await admin_client.get(
        f"/api/v1/platform/home-migration/packages/{uuid.uuid4()}/download"
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_package_download_requires_recent_authentication_and_is_audited(
    admin_client, admin_factory, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        platform_router, "_home_migration_environment", lambda settings, expected: None
    )
    monkeypatch.setattr(platform_router, "_home_migration_guard", _allow_migration)
    settings = get_settings().model_copy(update={"home_migration_storage_dir": str(tmp_path)})
    app.dependency_overrides[get_settings] = lambda: settings
    admin = await admin_factory()
    created: list[str] = []
    try:
        await login(admin_client, admin)
        row = await _store(settings, admin.id)
        created.append(row["id"])
        url = f"/api/v1/platform/home-migration/packages/{row['id']}/download"

        downloaded = await admin_client.get(url)
        assert downloaded.status_code == 200, downloaded.text
        assert downloaded.headers["cache-control"] == "no-store"
        assert downloaded.json()["migration_id"] == row["migration_id"]
        async with SessionFactory() as db:
            event = await db.scalar(
                select(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.administrator_id == admin.id,
                    AdministrativeAuditEvent.action == "home_migration.package_downloaded",
                )
            )
        assert event is not None
        assert event.new_values == {"package_checksum": row["package_checksum"]}
        assert "redacted@example.test" not in str(event.new_values)

        # Stale authentication: the same session can no longer download.
        async with SessionFactory() as db:
            await db.execute(
                PlatformSession.__table__.update()
                .where(PlatformSession.administrator_id == admin.id)
                .values(authenticated_at=datetime.now(UTC) - timedelta(hours=2))
            )
            await db.commit()
        stale = await admin_client.get(url)
        assert stale.status_code == 403
        assert stale.json()["detail"] == "Recent administrator authentication required."
    finally:
        app.dependency_overrides.pop(get_settings, None)
        await _delete_package_rows(created)


@pytest.mark.asyncio
async def test_purge_removes_completed_and_expired_packages_but_keeps_fresh_ones(
    tmp_path,
) -> None:
    settings = get_settings().model_copy(
        update={"home_migration_storage_dir": str(tmp_path), "home_migration_package_ttl_hours": 24}
    )
    creator = uuid.uuid4()
    fresh = await _store(settings, creator)
    stale = await _store(settings, creator)
    completed = await _store(settings, creator)
    ids = [fresh["id"], stale["id"], completed["id"]]
    now = datetime.now(UTC)
    async with SessionFactory() as db:
        await db.execute(
            PACKAGE_STORE.update()
            .where(PACKAGE_STORE.c.id == uuid.UUID(stale["id"]))
            .values(created_at=now - timedelta(hours=25))
        )
        await db.execute(
            PACKAGE_STORE.update()
            .where(PACKAGE_STORE.c.id == uuid.UUID(completed["id"]))
            .values(status="completed", completed_at=now)
        )
        await db.commit()
    fresh_orphan = tmp_path / f"{uuid.uuid4()}.json"
    fresh_orphan.write_text("{}", encoding="utf-8")
    old_orphan = tmp_path / f"{uuid.uuid4()}.json"
    old_orphan.write_text("{}", encoding="utf-8")
    old_time = (now - timedelta(hours=30)).timestamp()
    os.utime(old_orphan, (old_time, old_time))
    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("not a package", encoding="utf-8")
    try:
        async with SessionFactory() as db:
            result = await purge_expired_packages(db, settings, now=now)
            await db.commit()
        assert (result.removed_completed, result.removed_expired, result.removed_orphaned) == (
            1,
            1,
            1,
        )
        assert (tmp_path / fresh["storage_key"]).is_file()
        assert not (tmp_path / stale["storage_key"]).exists()
        assert not (tmp_path / completed["storage_key"]).exists()
        assert fresh_orphan.is_file()
        assert not old_orphan.exists()
        assert unrelated.is_file()
        async with SessionFactory() as db:
            statuses = {
                str(row.id): row.status
                for row in await db.execute(
                    select(PACKAGE_STORE.c.id, PACKAGE_STORE.c.status).where(
                        PACKAGE_STORE.c.id.in_([uuid.UUID(i) for i in ids])
                    )
                )
            }
        # Rows survive as the audit trail; only the expired one changes state.
        assert statuses == {
            fresh["id"]: "uploaded",
            stale["id"]: "expired",
            completed["id"]: "completed",
        }
        # Idempotent: a second pass has nothing left to do.
        async with SessionFactory() as db:
            again = await purge_expired_packages(db, settings, now=now)
        assert again.removed == 0
    finally:
        await _delete_package_rows(ids)


@pytest.mark.asyncio
async def test_purge_is_a_no_op_when_storage_is_absent(tmp_path) -> None:
    settings = get_settings().model_copy(
        update={"home_migration_storage_dir": str(tmp_path / "missing")}
    )
    async with SessionFactory() as db:
        result = await purge_expired_packages(db, settings)
    assert result.removed == 0 and result.scanned == 0


@pytest.mark.asyncio
async def test_discard_package_file_is_best_effort(tmp_path) -> None:
    settings = get_settings().model_copy(update={"home_migration_storage_dir": str(tmp_path)})
    target = tmp_path / "abc.json"
    target.write_text("{}", encoding="utf-8")
    await discard_package_file(settings, "abc.json")
    assert not target.exists()
    await discard_package_file(settings, "abc.json")  # already gone: no error
    await discard_package_file(settings, "../escape.json")  # rejected key: logged, no error
