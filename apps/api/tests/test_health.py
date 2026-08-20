"""The /health/ready migration-head safety guard — see
docs/architecture/meal-plans.md "Migration-head safety": a stale `migrate`
image previously no-op'd silently, leaving the API running against a
database several revisions behind. This guard makes that fail loudly
(503) instead.
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

import mykhaya.routers.health as health
from mykhaya.main import app

ORIGIN = "http://localhost:8080"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.mark.asyncio
async def test_ready_passes_when_schema_matches_expected_head(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Read the real current revision directly, then assert the expected
    # head "matches" it, isolating this test from whatever the real
    # alembic.ini/migrations layout looks like in this image.
    from mykhaya.db import SessionFactory
    from sqlalchemy import text

    async with SessionFactory() as db:
        row = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    monkeypatch.setattr(health, "_expected_alembic_head", lambda: row)

    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_ready_fails_loudly_when_schema_is_behind(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health, "_expected_alembic_head", lambda: "0099_a_future_migration")

    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert "0099_a_future_migration" in response.json()["detail"]


@pytest.mark.asyncio
async def test_ready_skips_the_check_when_expected_head_cannot_be_determined(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No alembic.ini at the process's working directory (e.g. under
    pytest) must never turn into a false readiness failure."""
    monkeypatch.setattr(health, "_expected_alembic_head", lambda: None)

    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
