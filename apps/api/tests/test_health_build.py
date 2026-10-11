"""Public health probes and the authenticated detailed metadata boundary."""

import os
from collections.abc import AsyncIterator
from types import SimpleNamespace

os.environ.setdefault("MYKHAYA_SECRET_KEY", "a" * 40)
os.environ.setdefault("MYKHAYA_ENVIRONMENT", "test")

import pytest
from httpx import ASGITransport, AsyncClient

from mykhaya.config import Settings, get_settings
from mykhaya.dependencies import AuthContext, auth_context
from mykhaya.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://localhost:8080",
        headers={"Origin": "http://localhost:8080"},
    ) as value:
        yield value


def metadata_settings() -> Settings:
    return Settings.model_construct(
        environment="production",
        version="v0.10.4",
        commit_sha="abc123",
        build_time="2026-10-11T12:00:00Z",
        build_channel="stable",
    )


async def test_public_liveness_remains_available_but_build_metadata_is_private(
    client: AsyncClient,
) -> None:
    assert (await client.get("/api/v1/health/live")).status_code == 200
    response = await client.get("/api/v1/health/build")
    assert response.status_code == 401
    assert "version" not in response.json()
    version_response = await client.get("/api/v1/version")
    assert version_response.status_code == 401
    assert "version" not in version_response.json()


async def test_authenticated_session_can_read_detailed_build_metadata(
    client: AsyncClient,
) -> None:
    app.dependency_overrides[get_settings] = metadata_settings
    app.dependency_overrides[auth_context] = lambda: AuthContext(
        user=SimpleNamespace(), session=SimpleNamespace(), transport="cookie"  # type: ignore[arg-type]
    )
    try:
        response = await client.get("/api/v1/health/build")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {
        "version": "v0.10.4",
        "commit": "abc123",
        "build_time": "2026-10-11T12:00:00Z",
        "environment": "production",
        "channel": "stable",
    }


async def test_native_bearer_transport_can_read_detailed_build_metadata(
    client: AsyncClient,
) -> None:
    app.dependency_overrides[get_settings] = metadata_settings
    app.dependency_overrides[auth_context] = lambda: AuthContext(
        user=SimpleNamespace(), session=SimpleNamespace(), transport="bearer"  # type: ignore[arg-type]
    )
    try:
        response = await client.get(
            "/api/v1/health/build",
            headers={"Authorization": "Bearer native-test-token"},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["version"] == "v0.10.4"
