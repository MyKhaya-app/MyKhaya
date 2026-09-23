"""GET /api/v1/config/public — the one consumer-safe window into
platform_settings, plus (Phase 2D) the derived `support_enabled` capability
signal and (Phase 2H) the `status_overall`/`status_overall_message` Service
Status summary. See mykhaya.routers.public_config,
mykhaya.platform_settings.SETTINGS_SCHEMA's consumer_visible flag,
mykhaya.features.platform_feature_enabled, and
mykhaya.status_aggregation.overall_public_state.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    FeatureFlag,
    FeatureKey,
    PlatformAdministrator,
    PlatformRole,
    PlatformSetting,
    PublicIncident,
    ServiceState,
    StatusIncidentService,
)
from mykhaya.security import password_hash

PUBLIC_CONFIG_KEYS = {
    "service_status_url",
    "support_enabled",
    "status_overall",
    "status_overall_message",
}


async def _create_admin_id() -> uuid.UUID:
    async with SessionFactory() as db:
        admin = PlatformAdministrator(
            email=f"status-cfg-{datetime.now(UTC).strftime('%H%M%S%f')}@example.com",
            display_name="Status Config Admin",
            password_hash=password_hash.hash("irrelevant for this test"),
            role=PlatformRole.owner,
            mfa_enrolled=True,
        )
        db.add(admin)
        await db.commit()
        await db.refresh(admin)
        return admin.id


async def _create_active_incident(impact: ServiceState) -> uuid.UUID:
    admin_id = await _create_admin_id()
    async with SessionFactory() as db:
        incident = PublicIncident(
            title="Public config test incident",
            message="Investigating",
            starts_at=datetime.now(UTC) - timedelta(minutes=1),
            created_by=admin_id,
        )
        db.add(incident)
        await db.flush()
        db.add(StatusIncidentService(incident_id=incident.id, service="api", impact=impact))
        await db.commit()
        return incident.id


async def _delete_incident(incident_id: uuid.UUID) -> None:
    async with SessionFactory() as db:
        await db.execute(delete(PublicIncident).where(PublicIncident.id == incident_id))
        await db.commit()


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


async def _set_support_flag(enabled: bool) -> None:
    async with SessionFactory() as db:
        row = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == FeatureKey.support))
        assert row is not None, "migration 0088 must have seeded a 'support' FeatureFlag row"
        row.enabled = enabled
        await db.commit()


@pytest.mark.asyncio
async def test_exposes_service_status_url_falling_back_to_the_environment_default(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/config/public")
    assert response.status_code == 200
    payload = response.json()
    assert payload["service_status_url"] == get_settings().status_url


@pytest.mark.asyncio
async def test_reflects_a_stored_override_once_one_exists(client: AsyncClient) -> None:
    async with SessionFactory() as db:
        db.add(
            PlatformSetting(
                key="service_status_url", value={"value": "https://status.example.com/"}
            )
        )
        await db.commit()

    response = await client.get("/api/v1/config/public")
    assert response.json()["service_status_url"] == "https://status.example.com/"


@pytest.mark.asyncio
async def test_never_exposes_a_non_consumer_visible_setting_even_when_set(
    client: AsyncClient,
) -> None:
    async with SessionFactory() as db:
        db.add(PlatformSetting(key="platform_display_name", value={"value": "Should not leak"}))
        await db.commit()

    response = await client.get("/api/v1/config/public")
    payload = response.json()
    assert set(payload.keys()) == PUBLIC_CONFIG_KEYS
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


# --- support_enabled (Phase 2D) -----------------------------------------------


@pytest.mark.asyncio
async def test_support_enabled_reflects_true_when_the_global_flag_is_on(
    client: AsyncClient,
) -> None:
    await _set_support_flag(True)
    try:
        response = await client.get("/api/v1/config/public")
        assert response.json()["support_enabled"] is True
    finally:
        await _set_support_flag(False)


@pytest.mark.asyncio
async def test_support_enabled_reflects_false_when_the_global_flag_is_off(
    client: AsyncClient,
) -> None:
    await _set_support_flag(False)
    response = await client.get("/api/v1/config/public")
    assert response.json()["support_enabled"] is False


@pytest.mark.asyncio
async def test_support_enabled_never_leaks_feature_override_or_admin_metadata(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/config/public")
    payload = response.json()
    assert isinstance(payload["support_enabled"], bool)
    # Only the boolean — no release_state, no updated_by, no override list,
    # no reason, nothing beyond the keys this endpoint has ever exposed.
    assert set(payload.keys()) == PUBLIC_CONFIG_KEYS


# --- status_overall / status_overall_message (Phase 2H) ------------------------
#
# mykhaya.routers.status's GET /status is deliberately host-gated to the
# dedicated status subdomain (enforce_status_host) and unreachable from the
# consumer web/native app's own origin — see that router's docstring. These
# fields give the Help & Support hub the exact same overall-severity
# computation from a surface it can actually call, never a new status model.


@pytest.mark.asyncio
async def test_status_overall_is_operational_with_no_active_incidents(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/config/public")
    payload = response.json()
    assert payload["status_overall"] == "operational"
    assert payload["status_overall_message"] == "Operational"


@pytest.mark.asyncio
async def test_status_overall_reflects_an_active_incidents_severity(
    client: AsyncClient,
) -> None:
    incident_id = await _create_active_incident(ServiceState.major_outage)
    try:
        response = await client.get("/api/v1/config/public")
        payload = response.json()
        assert payload["status_overall"] == "major_outage"
        assert payload["status_overall_message"] == "Major service disruption"
    finally:
        await _delete_incident(incident_id)


@pytest.mark.asyncio
async def test_status_overall_never_exposes_raw_incident_or_service_detail(
    client: AsyncClient,
) -> None:
    incident_id = await _create_active_incident(ServiceState.degraded)
    try:
        response = await client.get("/api/v1/config/public")
        payload = response.json()
        # Only the two summary fields — never the services list, incident
        # list, internal_notes, or any other detail the full Status page
        # (and PCC) expose.
        assert set(payload.keys()) == PUBLIC_CONFIG_KEYS
        assert "services" not in payload
        assert "incidents" not in payload
        assert "current_incidents" not in payload
    finally:
        await _delete_incident(incident_id)


@pytest.mark.asyncio
async def test_status_fields_are_omitted_when_status_public_enabled_is_false() -> None:
    disabled = get_settings().model_copy(update={"status_public_enabled": False})
    app.dependency_overrides[get_settings] = lambda: disabled
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://localhost:8080"
        ) as client:
            response = await client.get("/api/v1/config/public")
        payload = response.json()
        assert "status_overall" not in payload
        assert "status_overall_message" not in payload
        # Everything else this endpoint has always exposed is unaffected.
        assert "service_status_url" in payload
        assert "support_enabled" in payload
    finally:
        app.dependency_overrides.pop(get_settings, None)
