"""CRUD, visibility, category and completion coverage for Nudges To-dos."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import get_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    FeatureKey,
    FeatureOverride,
    SubscriptionPlan,
    TokenPurpose,
    User,
)
from mykhaya.security import derived_token

ORIGIN = "http://localhost:8080"
PASSWORD = "Correct horse battery staple!"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


async def unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    csrf = client.cookies.get("mk_csrf")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


async def create_verified_user(client: AsyncClient, email: str) -> None:
    registered = await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": "Nudges Owner", "password": PASSWORD},
    )
    assert registered.status_code == 202, registered.text
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        token = await db.scalar(
            select(ActionToken)
            .where(ActionToken.user_id == user.id, ActionToken.purpose == TokenPurpose.verify_email)
            .order_by(ActionToken.created_at.desc())
        )
        assert token is not None
        raw = derived_token(
            token.id, TokenPurpose.verify_email.value, get_settings().secret_key.get_secret_value()
        )
    verified = await unsafe(client, "POST", "/api/v1/auth/verify-email", json={"token": raw})
    assert verified.status_code == 200, verified.text
    logged_in = await unsafe(
        client,
        "POST",
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert logged_in.status_code == 200, logged_in.text


async def create_home_with_notifications(client: AsyncClient) -> str:
    created = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Nudges Test Home"})
    assert created.status_code == 201, created.text
    home_id = uuid.UUID(created.json()["id"])
    async with SessionFactory() as db:
        db.add(
            FeatureOverride(feature_key=FeatureKey.notifications, group_id=home_id, enabled=True)
        )
        # To-dos require the nudges.enabled commercial entitlement
        # (Family-only, Phase 2B) in addition to FeatureKey.nudges — see
        # mykhaya.routers.todos. Free-plan denial is covered separately in
        # test_feature_precedence.py.
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()
    return str(home_id)


@pytest.mark.asyncio
async def test_todo_category_crud_completion_and_category_delete_preserves_todo(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"nudges-{suffix}@example.com")
    home_id = await create_home_with_notifications(client)
    due_date = datetime.now(UTC).date().isoformat()

    category = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/todo-categories",
        json={"name": "School"},
    )
    assert category.status_code == 201, category.text
    category_id = category.json()["id"]

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/todos",
        json={
            "title": "Sign school trip form",
            "description": "Return it tomorrow",
            "scope": "personal",
            "due_date": due_date,
            "category_id": category_id,
            "member_ids": [],
        },
    )
    assert created.status_code == 201, created.text
    todo = created.json()
    assert todo["category"]["name"] == "School"
    assert todo["completed_at"] is None

    renamed = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/todo-categories/{category_id}",
        json={"name": "School admin", "expected_updated_at": category.json()["updated_at"]},
    )
    assert renamed.status_code == 200, renamed.text

    completed = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/todos/{todo['id']}/complete",
        json={"completed": True},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["completed_at"] is not None

    uncompleted = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/todos/{todo['id']}/complete",
        json={"completed": False},
    )
    assert uncompleted.status_code == 200, uncompleted.text
    assert uncompleted.json()["completed_at"] is None

    deleted = await unsafe(
        client, "DELETE", f"/api/v1/homes/{home_id}/todo-categories/{category_id}"
    )
    assert deleted.status_code == 204, deleted.text
    listed = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/todos")
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["category"] is None


@pytest.mark.asyncio
async def test_todo_requires_due_date_and_new_home_starts_empty(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"nudges-validation-{suffix}@example.com")
    home_id = await create_home_with_notifications(client)
    missing_date = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/todos",
        json={"title": "Needs a date", "scope": "personal"},
    )
    assert missing_date.status_code == 422, missing_date.text

    other_home_id = await create_home_with_notifications(client)
    response = await unsafe(client, "GET", f"/api/v1/homes/{other_home_id}/todos")
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
