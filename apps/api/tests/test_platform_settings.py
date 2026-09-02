"""Platform Control Centre operational settings: apps/api/mykhaya/platform_settings.py
(schema/validation) and the /platform/settings GET/PUT endpoints in
apps/api/mykhaya/routers/platform.py.

Reuses the admin_client/admin_factory/login/unsafe fixtures and helpers from
test_platform_control_centre.py rather than re-declaring the whole admin-auth
test harness.
"""

from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from test_platform_control_centre import (  # noqa: F401
    admin_client,
    admin_factory,
    login,
    unsafe,
)

from mykhaya.db import SessionFactory
from mykhaya.models import (
    AdministrativeAuditEvent,
    PlatformAdministrator,
    PlatformRole,
    PlatformSetting,
)


async def _delete_setting(key: str) -> None:
    async with SessionFactory() as db:
        await db.execute(delete(PlatformSetting).where(PlatformSetting.key == key))
        await db.commit()


@pytest.fixture(autouse=True)
async def _cleanup_settings():
    yield
    keys = (
        "platform_display_name",
        "service_status_url",
        "maximum_homes_per_user",
        "maintenance_mode",
    )
    for key in keys:
        await _delete_setting(key)


@pytest.mark.asyncio
async def test_owner_can_read_settings_with_friendly_metadata(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)

    response = await admin_client.get("/api/v1/platform/settings")
    assert response.status_code == 200
    payload = response.json()
    by_key = {row["key"]: row for row in payload["settings"]}

    display_name = by_key["platform_display_name"]
    assert display_name["label"] == "Platform name"
    assert display_name["section"] == "General"
    assert display_name["value_type"] == "text"
    assert display_name["state"] == "unset"
    assert display_name["value"] is None
    assert "category" not in display_name

    service_status = by_key["service_status_url"]
    assert service_status["state"] == "default"
    assert service_status["value"]  # falls back to Settings.status_url
    assert service_status["consumer_visible"] is True
    assert service_status["runtime_effect"] == "effective"

    maintenance = by_key["maintenance_mode"]
    assert maintenance["risk"] == "sensitive"
    assert maintenance["runtime_effect"] == "not_enforced"


@pytest.mark.asyncio
async def test_owner_can_update_an_editable_setting_and_it_is_audited(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)

    response = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/settings/platform_display_name",
        json={
            "value": "MyKhaya Test Platform",
            "reason": "Branding update for testing.",
            "confirmed": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["value"] == "MyKhaya Test Platform"

    follow_up = await admin_client.get("/api/v1/platform/settings")
    row = next(r for r in follow_up.json()["settings"] if r["key"] == "platform_display_name")
    assert row["value"] == "MyKhaya Test Platform"
    assert row["state"] == "configured"

    async with SessionFactory() as db:
        event = (
            await db.scalars(
                select(AdministrativeAuditEvent)
                .where(AdministrativeAuditEvent.action == "setting.updated")
                .order_by(AdministrativeAuditEvent.created_at.desc())
            )
        ).first()
    assert event is not None
    assert event.new_values == {"platform_display_name": "MyKhaya Test Platform"}
    assert event.previous_values["platform_display_name"] is None
    assert event.previous_values["previous_source"] == "unset"


@pytest.mark.asyncio
async def test_first_write_to_service_status_url_audits_the_environment_default_as_previous(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)

    before = await admin_client.get("/api/v1/platform/settings")
    default_value = next(
        row for row in before.json()["settings"] if row["key"] == "service_status_url"
    )["value"]
    assert default_value

    response = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/settings/service_status_url",
        json={
            "value": "https://status.example.com/",
            "reason": "Point at the real status page.",
            "confirmed": True,
        },
    )
    assert response.status_code == 200, response.text

    async with SessionFactory() as db:
        event = (
            await db.scalars(
                select(AdministrativeAuditEvent)
                .where(AdministrativeAuditEvent.action == "setting.updated")
                .order_by(AdministrativeAuditEvent.created_at.desc())
            )
        ).first()
    assert event.previous_values["service_status_url"] is None
    assert event.previous_values["previous_effective_value"] == default_value
    assert event.previous_values["previous_source"] == "environment_default"
    assert event.new_values == {"service_status_url": "https://status.example.com/"}


@pytest.mark.asyncio
async def test_non_owner_cannot_update_settings(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.support)
    await login(admin_client, admin)

    response = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/settings/platform_display_name",
        json={
            "value": "Should not work",
            "reason": "Attempting unauthorised change.",
            "confirmed": True,
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_unknown_setting_key_is_rejected(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)

    response = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/settings/not_a_real_setting",
        json={"value": "anything", "reason": "Probing for unknown keys.", "confirmed": True},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_environment_controlled_keys_are_rejected_as_not_editable(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)

    for key in ("public_url", "admin_url", "status_url"):
        response = await unsafe(
            admin_client,
            "PUT",
            f"/api/v1/platform/settings/{key}",
            json={
                "value": "https://example.com",
                "reason": "Attempting to edit infra config.",
                "confirmed": True,
            },
        )
        assert response.status_code == 422, key
        assert "deployment environment" in response.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_service_status_url_values_are_rejected(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)

    for bad_value in (
        "not-a-url",
        "ftp://status.example.com",
        "https://",
        "https://user:pass@status.example.com/",
    ):
        response = await unsafe(
            admin_client,
            "PUT",
            "/api/v1/platform/settings/service_status_url",
            json={
                "value": bad_value,
                "reason": "Testing invalid URL rejection.",
                "confirmed": True,
            },
        )
        assert response.status_code == 422, bad_value


@pytest.mark.asyncio
async def test_valid_service_status_url_is_accepted(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)

    response = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/settings/service_status_url",
        json={
            "value": "https://status.example.com/",
            "reason": "Setting the real status page.",
            "confirmed": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["value"] == "https://status.example.com/"


@pytest.mark.asyncio
async def test_integer_setting_range_validation(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)

    too_low = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/settings/maximum_homes_per_user",
        json={"value": 0, "reason": "Testing integer range validation.", "confirmed": True},
    )
    assert too_low.status_code == 422

    valid = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/settings/maximum_homes_per_user",
        json={"value": 5, "reason": "Testing integer range validation.", "confirmed": True},
    )
    assert valid.status_code == 200, valid.text


@pytest.mark.asyncio
async def test_boolean_setting_validation(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)

    wrong_type = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/settings/maintenance_mode",
        json={"value": "true", "reason": "Testing boolean validation.", "confirmed": True},
    )
    assert wrong_type.status_code == 422

    valid = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/settings/maintenance_mode",
        json={"value": True, "reason": "Testing boolean validation.", "confirmed": True},
    )
    assert valid.status_code == 200, valid.text


@pytest.mark.asyncio
async def test_failed_validation_does_not_create_a_misleading_audit_entry(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)

    async with SessionFactory() as db:
        before_count = len(
            (
                await db.scalars(
                    select(AdministrativeAuditEvent).where(
                        AdministrativeAuditEvent.action == "setting.updated"
                    )
                )
            ).all()
        )

    response = await unsafe(
        admin_client,
        "PUT",
        "/api/v1/platform/settings/service_status_url",
        json={"value": "not-a-url", "reason": "Testing failed validation.", "confirmed": True},
    )
    assert response.status_code == 422

    async with SessionFactory() as db:
        after_count = len(
            (
                await db.scalars(
                    select(AdministrativeAuditEvent).where(
                        AdministrativeAuditEvent.action == "setting.updated"
                    )
                )
            ).all()
        )
    assert after_count == before_count
