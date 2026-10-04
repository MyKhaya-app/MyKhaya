"""Tests for the DVLA UAT/production environment configuration surface:
Settings resolution (no fallback between environments, "Not configured" is a
valid safe state), the PCC Driveway integrations card, and the consumer
lookup flow. Provider-level field mapping and 404 handling already live in
test_driveway_providers.py. No test in this file calls the real DVLA
service — every provider response is mocked via monkeypatch or httpx.MockTransport.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import delete, select

import mykhaya.driveway_providers as driveway_providers
from mykhaya.config import Settings, get_settings
from mykhaya.db import SessionFactory
from mykhaya.driveway_providers import VehicleLookup
from mykhaya.entitlements import get_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    AdministrativeAuditEvent,
    FeatureFlag,
    FeatureKey,
    FeatureOverride,
    PlatformAdministrator,
    PlatformRole,
    PlatformSetting,
    SubscriptionPlan,
    TokenPurpose,
    User,
)
from mykhaya.security import derived_token, password_hash

ORIGIN = "http://localhost:8080"
ADMIN_ORIGIN = get_settings().admin_url
PASSWORD = "Correct horse battery staple!"
ADMIN_PASSWORD = "A separate operator password!"
TEST_PROXY_PEER = "172.16.0.2"
TEST_CLIENT_IP = "127.0.0.1"


# --- Configuration resolution (no DB, no app) --------------------------------


def _base_settings_kwargs() -> dict[str, object]:
    return {
        "secret_key": SecretStr("test-only-secret-key-never-used-in-production-1234"),
    }


def test_dvla_not_configured_when_no_environment_selected() -> None:
    settings = Settings(**_base_settings_kwargs())
    assert settings.dvla_environment is None
    assert settings.dvla_configured is False
    assert settings.dvla_active_endpoint is None
    assert settings.dvla_active_api_key is None
    assert settings.dvla_environment_label is None


def test_dvla_uat_selected_and_fully_configured() -> None:
    settings = Settings(
        **_base_settings_kwargs(),
        dvla_environment="uat",
        dvla_uat_endpoint="https://uat.dvla.example/vehicle-enquiry",
        dvla_uat_api_key=SecretStr("uat-secret"),
    )
    assert settings.dvla_configured is True
    assert settings.dvla_active_endpoint == "https://uat.dvla.example/vehicle-enquiry"
    assert settings.dvla_active_api_key is not None
    assert settings.dvla_active_api_key.get_secret_value() == "uat-secret"
    assert settings.dvla_environment_label == "UAT"


def test_dvla_uat_selected_but_missing_key_is_not_configured_and_never_falls_back() -> None:
    settings = Settings(
        **_base_settings_kwargs(),
        dvla_environment="uat",
        dvla_uat_endpoint="https://uat.dvla.example/vehicle-enquiry",
        dvla_uat_api_key=None,
        dvla_production_api_key=SecretStr("prod-secret"),
    )
    assert settings.dvla_configured is False
    # Never silently uses the production key just because it happens to be set.
    assert settings.dvla_active_api_key is None


def test_dvla_uat_selected_with_blank_key_is_not_configured() -> None:
    settings = Settings(
        **_base_settings_kwargs(),
        dvla_environment="uat",
        dvla_uat_endpoint="https://uat.dvla.example/vehicle-enquiry",
        dvla_uat_api_key=SecretStr(""),
    )
    assert settings.dvla_configured is False
    assert settings.dvla_active_api_key is None


def test_dvla_production_selected_and_configured() -> None:
    settings = Settings(
        **_base_settings_kwargs(),
        dvla_environment="production",
        dvla_production_api_key=SecretStr("prod-secret"),
    )
    assert settings.dvla_configured is True
    assert settings.dvla_active_endpoint == (
        "https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles"
    )
    assert settings.dvla_environment_label == "Production"


def test_dvla_invalid_environment_value_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(**_base_settings_kwargs(), dvla_environment="staging")


# --- Provider: auth failure is distinct from general unavailability ----------


@pytest.mark.asyncio
async def test_dvla_provider_distinguishes_auth_failure_from_unavailable() -> None:
    import httpx

    provider = driveway_providers.UKDVLAProvider(
        SecretStr("bad-key"),
        "https://dvla.test",
        transport=httpx.MockTransport(lambda _: httpx.Response(401)),
    )
    with pytest.raises(driveway_providers.VehicleLookupAuthFailed):
        await provider.lookup("AB12 CDE")

    provider = driveway_providers.UKDVLAProvider(
        SecretStr("key"),
        "https://dvla.test",
        transport=httpx.MockTransport(lambda _: httpx.Response(503)),
    )
    with pytest.raises(driveway_providers.VehicleLookupUnavailable):
        await provider.lookup("AB12 CDE")


# --- PCC: Driveway integrations card -----------------------------------------


@pytest.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app, client=(TEST_PROXY_PEER, 44000)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN, "X-Forwarded-For": TEST_CLIENT_IP},
    ) as value:
        yield value


async def create_admin(role: PlatformRole = PlatformRole.owner) -> PlatformAdministrator:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    async with SessionFactory() as db:
        row = PlatformAdministrator(
            email=f"dvla-operator-{suffix}@example.com",
            display_name="Test Operator",
            password_hash=password_hash.hash(ADMIN_PASSWORD),
            role=role,
            mfa_enrolled=True,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row


@pytest.fixture
async def admin_factory() -> AsyncIterator[
    Callable[[PlatformRole], Awaitable[PlatformAdministrator]]
]:
    identifiers: list[uuid.UUID] = []

    async def factory(role: PlatformRole = PlatformRole.owner) -> PlatformAdministrator:
        row = await create_admin(role)
        identifiers.append(row.id)
        return row

    yield factory
    if identifiers:
        async with SessionFactory() as db:
            await db.execute(
                delete(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.administrator_id.in_(identifiers)
                )
            )
            await db.execute(
                delete(PlatformAdministrator).where(PlatformAdministrator.id.in_(identifiers))
            )
            await db.commit()


async def login(client: AsyncClient, admin: PlatformAdministrator) -> None:
    response = await client.post(
        "/api/v1/platform/auth/login", json={"email": admin.email, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200, response.text


async def unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    csrf = client.cookies.get("mk_admin_csrf")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


async def _clear_dvla_platform_setting() -> None:
    async with SessionFactory() as db:
        await db.execute(
            delete(PlatformSetting).where(PlatformSetting.key == "driveway_dvla_enabled")
        )
        await db.commit()


@pytest.fixture(autouse=True)
async def _reset_driveway_dvla_platform_setting() -> AsyncIterator[None]:
    yield
    await _clear_dvla_platform_setting()


def _override_settings(**overrides: object) -> Settings:
    return get_settings().model_copy(update=overrides)


def _test_connection_body(registration: str) -> dict[str, object]:
    return {"registration": registration, "reason": "Verify UAT connectivity", "confirmed": True}


@pytest.mark.asyncio
async def test_pcc_dvla_status_reports_not_configured_when_no_environment_selected(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    app.dependency_overrides[get_settings] = lambda: _override_settings(
        dvla_environment=None, dvla_uat_api_key=None
    )
    try:
        response = await admin_client.get("/api/v1/platform/integrations/dvla")
        assert response.status_code == 200
        payload = response.json()
        assert payload["configured"] is False
        assert payload["health"]["state"] == "Not configured"
        assert payload["environment"] is None
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_pcc_dvla_status_shows_friendly_uat_label_and_never_exposes_the_key(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    app.dependency_overrides[get_settings] = lambda: _override_settings(
        dvla_environment="uat",
        dvla_uat_endpoint="https://uat.dvla.example/vehicle-enquiry",
        dvla_uat_api_key=SecretStr("super-secret-uat-key"),
    )
    try:
        response = await admin_client.get("/api/v1/platform/integrations/dvla")
        assert response.status_code == 200
        payload = response.json()
        assert payload["configured"] is True
        assert payload["environment"] == "UAT"
        assert payload["endpoint"] == "https://uat.dvla.example/vehicle-enquiry"
        assert "super-secret-uat-key" not in response.text
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_pcc_dvla_disabled_state_overrides_any_stale_stored_health(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    async with SessionFactory() as db:
        db.add(
            PlatformSetting(
                key="driveway_dvla_enabled",
                value={"value": False, "health": {"state": "Healthy"}},
            )
        )
        await db.commit()
    app.dependency_overrides[get_settings] = lambda: _override_settings(
        dvla_environment="uat",
        dvla_uat_endpoint="https://uat.dvla.example/vehicle-enquiry",
        dvla_uat_api_key=SecretStr("uat-secret"),
    )
    try:
        response = await admin_client.get("/api/v1/platform/integrations/dvla")
        assert response.json()["health"]["state"] == "Disabled"
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_pcc_dvla_test_connection_success_names_the_active_environment(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)

    async def fake_lookup(self: object, registration: str) -> VehicleLookup:
        return VehicleLookup(registration=registration)

    monkeypatch.setattr(driveway_providers.UKDVLAProvider, "lookup", fake_lookup)
    app.dependency_overrides[get_settings] = lambda: _override_settings(
        dvla_environment="uat",
        dvla_uat_endpoint="https://uat.dvla.example/vehicle-enquiry",
        dvla_uat_api_key=SecretStr("uat-secret"),
    )
    try:
        response = await unsafe(
            admin_client,
            "POST",
            "/api/v1/platform/integrations/dvla/test",
            json=_test_connection_body("AB12 CDE"),
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["state"] == "Healthy"
        assert "UAT" in payload["message"]
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_pcc_dvla_test_connection_not_found_is_still_a_healthy_connection(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)

    async def fake_lookup(self: object, registration: str) -> VehicleLookup:
        raise driveway_providers.VehicleLookupNotFound

    monkeypatch.setattr(driveway_providers.UKDVLAProvider, "lookup", fake_lookup)
    app.dependency_overrides[get_settings] = lambda: _override_settings(
        dvla_environment="uat",
        dvla_uat_endpoint="https://uat.dvla.example/vehicle-enquiry",
        dvla_uat_api_key=SecretStr("uat-secret"),
    )
    try:
        response = await unsafe(
            admin_client,
            "POST",
            "/api/v1/platform/integrations/dvla/test",
            json=_test_connection_body("ZZ99 ZZZ"),
        )
        payload = response.json()
        assert payload["state"] == "Healthy"
        assert "not found" in payload["message"].lower()
        assert "working" in payload["message"].lower()
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_pcc_dvla_test_connection_auth_failure_message(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)

    async def fake_lookup(self: object, registration: str) -> VehicleLookup:
        raise driveway_providers.VehicleLookupAuthFailed

    monkeypatch.setattr(driveway_providers.UKDVLAProvider, "lookup", fake_lookup)
    app.dependency_overrides[get_settings] = lambda: _override_settings(
        dvla_environment="uat",
        dvla_uat_endpoint="https://uat.dvla.example/vehicle-enquiry",
        dvla_uat_api_key=SecretStr("wrong-key"),
    )
    try:
        response = await unsafe(
            admin_client,
            "POST",
            "/api/v1/platform/integrations/dvla/test",
            json=_test_connection_body("AB12 CDE"),
        )
        payload = response.json()
        assert payload["state"] == "Unavailable"
        assert payload["message"] == "DVLA authentication failed."
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_pcc_dvla_test_connection_unavailable_when_not_configured(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    app.dependency_overrides[get_settings] = lambda: _override_settings(
        dvla_environment=None, dvla_uat_api_key=None
    )
    try:
        response = await unsafe(
            admin_client,
            "POST",
            "/api/v1/platform/integrations/dvla/test",
            json=_test_connection_body("AB12 CDE"),
        )
        assert response.status_code == 503
    finally:
        app.dependency_overrides.pop(get_settings, None)


# --- Consumer lookup flow -----------------------------------------------------


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


async def consumer_unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    csrf = client.cookies.get("mk_csrf")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


def unique_email(prefix: str) -> str:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    return f"{prefix}-{suffix}@example.com"


async def create_verified_user(client: AsyncClient, email: str, name: str) -> uuid.UUID:
    response = await consumer_unsafe(
        client,
        "POST",
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
    verified = await consumer_unsafe(
        client, "POST", "/api/v1/auth/verify-email", json={"token": raw}
    )
    assert verified.status_code == 200
    login_response = await consumer_unsafe(
        client, "POST", "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login_response.status_code == 200
    return user_id


async def create_driveway_home(client: AsyncClient, name: str = "DVLA Test Home") -> uuid.UUID:
    group = await consumer_unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert group.status_code == 201
    home_id = uuid.UUID(group.json()["id"])
    async with SessionFactory() as db:
        flag = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == FeatureKey.driveway))
        if flag is None:
            db.add(FeatureFlag(key=FeatureKey.driveway, enabled=True))
        else:
            flag.enabled = True
        db.add(FeatureOverride(feature_key=FeatureKey.driveway, group_id=home_id, enabled=True))
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        subscription.plan = SubscriptionPlan.ultimate
        await db.commit()
    return home_id


async def enable_dvla_toggle(*, enabled: bool = True) -> None:
    async with SessionFactory() as db:
        row = await db.scalar(
            select(PlatformSetting).where(PlatformSetting.key == "driveway_dvla_enabled")
        )
        if row is None:
            db.add(PlatformSetting(key="driveway_dvla_enabled", value={"value": enabled}))
        else:
            row.value = {**row.value, "value": enabled}
        await db.commit()


@pytest.fixture(autouse=True)
async def _reset_consumer_dvla_platform_setting() -> AsyncIterator[None]:
    yield
    await _clear_dvla_platform_setting()


@pytest.mark.asyncio
async def test_consumer_lookup_succeeds_against_configured_uat(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await create_verified_user(client, unique_email("dvla-uat"), "Driveway UAT")
    home_id = await create_driveway_home(client)
    await enable_dvla_toggle(enabled=True)

    async def fake_lookup(self: object, registration: str) -> VehicleLookup:
        return VehicleLookup(registration="AP22OOJ", make="BMW", model="i4", colour="Black")

    monkeypatch.setattr(driveway_providers.UKDVLAProvider, "lookup", fake_lookup)
    app.dependency_overrides[get_settings] = lambda: _override_settings(
        dvla_environment="uat",
        dvla_uat_endpoint="https://uat.dvla.example/vehicle-enquiry",
        dvla_uat_api_key=SecretStr("uat-secret"),
    )
    try:
        response = await consumer_unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/vehicles/lookup",
            json={"country_code": "GB", "registration": "AP22 OOJ"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["found"] is True
        assert payload["make"] == "BMW"
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_consumer_lookup_falls_back_to_manual_entry_when_not_configured(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("dvla-unconfigured"), "Driveway Unconfigured")
    home_id = await create_driveway_home(client)
    app.dependency_overrides[get_settings] = lambda: _override_settings(
        dvla_environment=None, dvla_uat_api_key=None
    )
    try:
        response = await consumer_unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/vehicles/lookup",
            json={"country_code": "GB", "registration": "AP22 OOJ"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["found"] is False
        assert payload["manual_entry_required"] is True
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_consumer_lookup_falls_back_to_manual_entry_when_provider_disabled(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await create_verified_user(client, unique_email("dvla-disabled"), "Driveway Disabled")
    home_id = await create_driveway_home(client)
    await enable_dvla_toggle(enabled=False)

    async def fail_if_called(self: object, registration: str) -> VehicleLookup:
        raise AssertionError("Provider must never be called while disabled")

    monkeypatch.setattr(driveway_providers.UKDVLAProvider, "lookup", fail_if_called)
    app.dependency_overrides[get_settings] = lambda: _override_settings(
        dvla_environment="uat",
        dvla_uat_endpoint="https://uat.dvla.example/vehicle-enquiry",
        dvla_uat_api_key=SecretStr("uat-secret"),
    )
    try:
        response = await consumer_unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/vehicles/lookup",
            json={"country_code": "GB", "registration": "AP22 OOJ"},
        )
        assert response.status_code == 200
        assert response.json()["manual_entry_required"] is True
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_consumer_lookup_unsupported_country_requires_manual_entry(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("dvla-country"), "Driveway Country")
    home_id = await create_driveway_home(client)
    response = await consumer_unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/lookup",
        json={"country_code": "US", "registration": "ABC123"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["found"] is False
    assert payload["manual_entry_required"] is True


@pytest.mark.asyncio
async def test_consumer_lookup_provider_failure_offers_manual_entry(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await create_verified_user(client, unique_email("dvla-failure"), "Driveway Failure")
    home_id = await create_driveway_home(client)
    await enable_dvla_toggle(enabled=True)

    async def fake_lookup(self: object, registration: str) -> VehicleLookup:
        raise driveway_providers.VehicleLookupUnavailable

    monkeypatch.setattr(driveway_providers.UKDVLAProvider, "lookup", fake_lookup)
    app.dependency_overrides[get_settings] = lambda: _override_settings(
        dvla_environment="uat",
        dvla_uat_endpoint="https://uat.dvla.example/vehicle-enquiry",
        dvla_uat_api_key=SecretStr("uat-secret"),
    )
    try:
        response = await consumer_unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/vehicles/lookup",
            json={"country_code": "GB", "registration": "AP22 OOJ"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["found"] is False
        assert payload["manual_entry_required"] is True
    finally:
        app.dependency_overrides.pop(get_settings, None)
