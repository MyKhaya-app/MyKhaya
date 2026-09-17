"""HTTP-level coverage for POST /api/v1/notifications/native-devices — the
upsert/lookup-key logic itself, which (per the native-push-device-lifecycle
audit) had no route-level test coverage at all before this phase: every
other test that needed a NativePushDevice row constructed one directly via
`db.add(...)`, bypassing this endpoint entirely.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    NativePushDevice,
    NativePushDisabledSource,
    TokenPurpose,
    User,
)
from mykhaya.security import derived_token

ORIGIN = "http://localhost:8080"
PASSWORD = "Correct horse battery staple!"


def unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}@example.com"


async def create_verified_user(client: AsyncClient, email: str, name: str) -> uuid.UUID:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "display_name": name, "password": PASSWORD},
    )
    assert response.status_code == 202
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        user_id = user.id
        token = await db.scalar(
            select(ActionToken)
            .where(ActionToken.user_id == user.id, ActionToken.purpose == TokenPurpose.verify_email)
            .order_by(ActionToken.created_at.desc())
        )
        assert token is not None
        raw = derived_token(
            token.id, TokenPurpose.verify_email.value, get_settings().secret_key.get_secret_value()
        )
    verified = await client.post("/api/v1/auth/verify-email", json={"token": raw})
    assert verified.status_code == 200
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    return user_id


async def register(client: AsyncClient, **overrides: object) -> Response:
    csrf = client.cookies.get("mk_csrf")
    body: dict[str, object] = {
        "platform": "ios",
        "token": "a" * 64,
        "installation_id": f"installation-{uuid.uuid4()}",
        "device_label": "Test iPhone",
        "apns_environment": "sandbox",
    }
    body.update(overrides)
    return await client.post(
        "/api/v1/notifications/native-devices",
        json=body,
        headers={"X-CSRF-Token": csrf} if csrf else {},
    )


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.mark.asyncio
async def test_initial_registration_creates_a_row(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("initial"), "Initial User")
    installation_id = f"installation-{uuid.uuid4()}"

    response = await register(client, installation_id=installation_id)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["platform"] == "ios"
    assert body["apns_environment"] == "sandbox"
    assert body["disabled_at"] is None
    async with SessionFactory() as db:
        row = await db.get(NativePushDevice, uuid.UUID(body["id"]))
        assert row is not None
        assert row.installation_id == installation_id
        assert row.disabled_source is None


@pytest.mark.asyncio
async def test_same_installation_platform_environment_reuses_same_row(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("reuse"), "Reuse User")
    installation_id = f"installation-{uuid.uuid4()}"

    first = await register(client, installation_id=installation_id)
    second = await register(client, installation_id=installation_id)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    async with SessionFactory() as db:
        count = len(
            (
                await db.scalars(
                    select(NativePushDevice).where(
                        NativePushDevice.installation_id == installation_id
                    )
                )
            ).all()
        )
        assert count == 1


@pytest.mark.asyncio
async def test_new_token_updates_the_same_row(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("newtoken"), "New Token User")
    installation_id = f"installation-{uuid.uuid4()}"

    first = await register(client, installation_id=installation_id, token="a" * 64)
    second = await register(client, installation_id=installation_id, token="b" * 64)

    assert first.json()["id"] == second.json()["id"]
    async with SessionFactory() as db:
        row = await db.get(NativePushDevice, uuid.UUID(second.json()["id"]))
        assert row is not None
        assert row.token == "b" * 64


@pytest.mark.asyncio
async def test_legacy_null_environment_row_is_promoted_on_reregistration(
    client: AsyncClient,
) -> None:
    """A row from before migration 0075 (apns_environment IS NULL) must be
    found by the fallback lookup and promoted, not duplicated, the next time
    its installation registers with a real environment — every current iOS
    client always sends one (routers.notifications.register_native_device
    enforces this), so this is the actual, current self-healing path."""
    user_id = await create_verified_user(client, unique_email("legacy"), "Legacy User")
    installation_id = f"installation-{uuid.uuid4()}"
    async with SessionFactory() as db:
        legacy_row = NativePushDevice(
            user_id=user_id,
            platform="ios",
            token="c" * 64,
            installation_id=installation_id,
            apns_environment=None,
        )
        db.add(legacy_row)
        await db.commit()
        await db.refresh(legacy_row)
        legacy_id = legacy_row.id

    response = await register(
        client, installation_id=installation_id, apns_environment="production", token="d" * 64
    )

    assert response.status_code == 201, response.text
    assert response.json()["id"] == str(legacy_id), "the legacy row was promoted, not duplicated"
    assert response.json()["apns_environment"] == "production"
    async with SessionFactory() as db:
        count = len(
            (
                await db.scalars(
                    select(NativePushDevice).where(
                        NativePushDevice.installation_id == installation_id
                    )
                )
            ).all()
        )
        assert count == 1


@pytest.mark.asyncio
async def test_sandbox_and_production_coexist_as_separate_rows(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("coexist"), "Coexist User")
    installation_id = f"installation-{uuid.uuid4()}"

    sandbox = await register(client, installation_id=installation_id, apns_environment="sandbox")
    production = await register(
        client, installation_id=installation_id, apns_environment="production"
    )

    assert sandbox.status_code == 201
    assert production.status_code == 201
    assert sandbox.json()["id"] != production.json()["id"]
    async with SessionFactory() as db:
        rows = (
            await db.scalars(
                select(NativePushDevice).where(NativePushDevice.installation_id == installation_id)
            )
        ).all()
        assert {row.apns_environment for row in rows} == {"sandbox", "production"}


@pytest.mark.asyncio
async def test_provider_disabled_row_reactivates_on_natural_reregistration(
    client: AsyncClient,
) -> None:
    """Mirrors what worker.py actually does on an ApnsPermanentError/
    FcmPermanentError — disabled_source=provider. This is existing, intended
    behaviour: a device is expected to resume working the next time it
    genuinely re-registers (e.g. a fresh install after the old token died)."""
    await create_verified_user(client, unique_email("provider-disabled"), "Provider Disabled User")
    installation_id = f"installation-{uuid.uuid4()}"
    created = await register(client, installation_id=installation_id)
    device_id = uuid.UUID(created.json()["id"])
    async with SessionFactory() as db:
        device = await db.get(NativePushDevice, device_id)
        assert device is not None
        device.disabled_at = datetime.now(UTC)
        device.disabled_reason = "APNs rejected this device registration."
        device.disabled_source = NativePushDisabledSource.provider
        await db.commit()

    response = await register(client, installation_id=installation_id, token="e" * 64)

    assert response.status_code == 201
    assert response.json()["id"] == str(device_id)
    assert response.json()["disabled_at"] is None
    async with SessionFactory() as db:
        row = await db.get(NativePushDevice, device_id)
        assert row is not None
        assert row.disabled_at is None
        assert row.disabled_reason is None
        assert row.disabled_source is None
        assert row.token == "e" * 64


@pytest.mark.asyncio
async def test_platform_admin_disabled_row_does_not_auto_reactivate(client: AsyncClient) -> None:
    """The central behaviour this phase adds: a Platform-Admin disable must
    survive the app's own natural re-registration — unlike provider/user
    disables, which are expected to reactivate."""
    await create_verified_user(client, unique_email("admin-disabled"), "Admin Disabled User")
    installation_id = f"installation-{uuid.uuid4()}"
    created = await register(client, installation_id=installation_id, token="f" * 64)
    device_id = uuid.UUID(created.json()["id"])
    async with SessionFactory() as db:
        device = await db.get(NativePushDevice, device_id)
        assert device is not None
        device.disabled_at = datetime.now(UTC)
        device.disabled_reason = "Disabled by Platform Admin"
        device.disabled_source = NativePushDisabledSource.platform_admin
        await db.commit()

    # Simulates the app's own reconcileNativePush() -> PushNotifications.
    # register() -> POST cycle firing again with OS permission still granted
    # — same installation, a fresh token (as if the provider rotated it).
    response = await register(client, installation_id=installation_id, token="g" * 64)

    assert response.status_code == 201, response.text
    assert response.json()["id"] == str(device_id), "no duplicate row was created"
    assert response.json()["disabled_at"] is not None, "must remain disabled"
    async with SessionFactory() as db:
        row = await db.get(NativePushDevice, device_id)
        assert row is not None
        assert row.disabled_at is not None
        assert row.disabled_reason == "Disabled by Platform Admin"
        assert row.disabled_source == NativePushDisabledSource.platform_admin
        # Technical fields still refresh even while parked.
        assert row.token == "g" * 64


@pytest.mark.asyncio
async def test_reenabled_row_reactivates_normally_and_can_be_disabled_again(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("reenable-cycle"), "Reenable Cycle User")
    installation_id = f"installation-{uuid.uuid4()}"
    created = await register(client, installation_id=installation_id)
    device_id = uuid.UUID(created.json()["id"])
    async with SessionFactory() as db:
        device = await db.get(NativePushDevice, device_id)
        assert device is not None
        device.disabled_at = None
        device.disabled_reason = None
        device.disabled_source = None
        await db.commit()

    # After a Platform Admin re-enable (disabled_source cleared to None,
    # exactly as enable_native_push_device does), a subsequent natural
    # re-registration must behave exactly like any other never-disabled row.
    response = await register(client, installation_id=installation_id, token="h" * 64)

    assert response.status_code == 201
    assert response.json()["id"] == str(device_id)
    assert response.json()["disabled_at"] is None
