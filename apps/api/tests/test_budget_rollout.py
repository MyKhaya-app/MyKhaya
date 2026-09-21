"""Focused rollout tests for the disabled-by-default Budget Home control."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import AuditEvent
from test_journey import ORIGIN, create_verified_user, unsafe


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.mark.asyncio
async def test_budget_home_rollout_preserves_profile_and_audits_enable_disable(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"budget-rollout-{suffix}@example.com", "Budget Owner")
    home = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Budget Rollout Home"})
    assert home.status_code == 201
    home_id = home.json()["id"]

    management = await client.get(f"/api/v1/features/{home_id}/modules/management")
    assert management.status_code == 200
    budget = next(row for row in management.json() if row["id"] == "budget")
    assert budget["enabled"] is False
    assert budget["toggleable"] is True

    enabled = await unsafe(
        client,
        "PUT",
        f"/api/v1/features/{home_id}/budget/household",
        json={"enabled": True, "reason": "Enable Budget for rollout", "confirmed": True},
    )
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True

    profile = await client.get(f"/api/v1/homes/{home_id}/budget")
    assert profile.status_code == 200
    profile_id = profile.json()["id"]
    settings = await unsafe(
        client,
        "PUT",
        f"/api/v1/homes/{home_id}/budget/settings",
        json={"currency": "EUR", "month_start_day": 15},
    )
    assert settings.status_code == 200
    assert settings.json()["month_start_day"] == 15

    disabled = await unsafe(
        client,
        "PUT",
        f"/api/v1/features/{home_id}/budget/household",
        json={"enabled": False, "reason": "Disable Budget for rollout", "confirmed": True},
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert (await client.get(f"/api/v1/homes/{home_id}/budget")).status_code == 404

    reenabled = await unsafe(
        client,
        "PUT",
        f"/api/v1/features/{home_id}/budget/household",
        json={"enabled": True, "reason": "Restore Budget access", "confirmed": True},
    )
    assert reenabled.status_code == 200
    restored = await client.get(f"/api/v1/homes/{home_id}/budget/settings")
    assert restored.status_code == 200
    assert restored.json()["id"] == profile_id
    assert restored.json()["currency"] == "EUR"
    assert restored.json()["month_start_day"] == 15

    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.group_id == uuid.UUID(home_id),
                    AuditEvent.action.in_(("feature.enabled", "feature.disabled")),
                )
                .order_by(AuditEvent.created_at)
            )
        ).all()
    budget_events = [event for event in events if event.metadata_.get("feature") == "budget"]
    assert [event.action for event in budget_events[-3:]] == [
        "feature.enabled",
        "feature.disabled",
        "feature.enabled",
    ]
