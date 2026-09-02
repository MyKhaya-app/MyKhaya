"""GET /api/v1/config/public — the one consumer-safe window into
platform_settings. See mykhaya.routers.public_config and
mykhaya.platform_settings.SETTINGS_SCHEMA's consumer_visible flag.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import PlatformSetting


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:8080"
    ) as value:
        yield value


@pytest.fixture(autouse=True)
async def _cleanup():
    yield
    async with SessionFactory() as db:
        await db.execute(delete(PlatformSetting).where(PlatformSetting.key == "service_status_url"))
        await db.commit()


@pytest.mark.asyncio
async def test_exposes_service_status_url_falling_back_to_the_environment_default(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/config/public")
    assert response.status_code == 200
    payload = response.json()
    assert payload == {"service_status_url": get_settings().status_url}


@pytest.mark.asyncio
async def test_reflects_a_stored_override_once_one_exists(client: AsyncClient) -> None:
    async with SessionFactory() as db:
        db.add(PlatformSetting(key="service_status_url", value={"value": "https://status.example.com/"}))
        await db.commit()

    response = await client.get("/api/v1/config/public")
    assert response.json() == {"service_status_url": "https://status.example.com/"}


@pytest.mark.asyncio
async def test_never_exposes_a_non_consumer_visible_setting_even_when_set(
    client: AsyncClient,
) -> None:
    async with SessionFactory() as db:
        db.add(PlatformSetting(key="platform_display_name", value={"value": "Should not leak"}))
        await db.commit()

    response = await client.get("/api/v1/config/public")
    payload = response.json()
    assert set(payload.keys()) == {"service_status_url"}
    assert "platform_display_name" not in payload

    async with SessionFactory() as db:
        await db.execute(
            delete(PlatformSetting).where(PlatformSetting.key == "platform_display_name")
        )
        await db.commit()


@pytest.mark.asyncio
async def test_response_has_no_cache_control_that_would_hide_a_pcc_change(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/config/public")
    assert response.headers.get("cache-control") == "no-store"
