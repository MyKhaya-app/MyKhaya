import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    FeatureKey,
    FeatureOverride,
    Invitation,
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


async def create_verified_user(client: AsyncClient, email: str, name: str) -> None:
    response = await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": name, "password": PASSWORD},
    )
    assert response.status_code == 202
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        token = await db.scalar(
            select(ActionToken)
            .where(
                ActionToken.user_id == user.id,
                ActionToken.purpose == TokenPurpose.verify_email,
            )
            .order_by(ActionToken.created_at.desc())
        )
        assert token is not None
        raw = derived_token(
            token.id,
            TokenPurpose.verify_email.value,
            get_settings().secret_key.get_secret_value(),
        )
    verified = await unsafe(client, "POST", "/api/v1/auth/verify-email", json={"token": raw})
    assert verified.status_code == 200
    login = await unsafe(
        client,
        "POST",
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_calendar_crud_and_conflict(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"owner-{suffix}@example.com", "Owner")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Pilot Home"})
    assert group.status_code == 201
    home_id = group.json()["id"]

    disabled = await client.get(f"/api/v1/homes/{home_id}/event-labels")
    assert disabled.status_code == 404
    async with SessionFactory() as db:
        db.add(
            FeatureOverride(
                feature_key=FeatureKey.calendar,
                group_id=uuid.UUID(home_id),
                enabled=True,
            )
        )
        await db.commit()
    evaluation = await client.get(f"/api/v1/features/{home_id}/calendar")
    assert evaluation.status_code == 200
    assert evaluation.json() == {"feature": "calendar", "enabled": True}

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "School run",
            "start_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
            "end_at": (datetime.now(UTC) + timedelta(hours=3)).isoformat(),
            "timezone": "Europe/London",
            "is_all_day": False,
            "member_ids": [],
            "recurrence": "weekly",
            "recurrence_interval": 1,
        },
    )
    assert created.status_code == 201
    event = created.json()

    listed = await client.get(
        f"/api/v1/homes/{home_id}/events",
        params={
            "start_at": datetime.now(UTC).isoformat(),
            "end_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        },
    )
    assert listed.status_code == 200
    assert listed.json()["items"]

    conflict = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event['event_id']}",
        json={
            "title": "School run updated",
            "start_at": event["start_at"],
            "end_at": event["end_at"],
            "timezone": "Europe/London",
            "is_all_day": False,
            "member_ids": [],
            "recurrence": "weekly",
            "recurrence_interval": 1,
            "expected_updated_at": "2000-01-01T00:00:00+00:00",
        },
    )
    assert conflict.status_code == 409

    deleted = await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/events/{event['event_id']}")
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_cross_home_event_access_denied(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"owner2-{suffix}@example.com", "Owner Two")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Private Home"})
    assert group.status_code == 201
    home_id = group.json()["id"]

    async with SessionFactory() as db:
        db.add(
            FeatureOverride(
                feature_key=FeatureKey.calendar,
                group_id=uuid.UUID(home_id),
                enabled=True,
            )
        )
        await db.commit()

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Private Event",
            "start_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "end_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
            "timezone": "Europe/London",
            "is_all_day": False,
            "member_ids": [],
            "recurrence": "none",
            "recurrence_interval": 1,
        },
    )
    assert created.status_code == 201

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as outsider:
        await create_verified_user(outsider, f"outsider-{suffix}@example.com", "Outsider")
        denied = await outsider.get(
            f"/api/v1/homes/{home_id}/events",
            params={
                "start_at": datetime.now(UTC).isoformat(),
                "end_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            },
        )
        assert denied.status_code == 404


@pytest.mark.asyncio
async def test_invitation_only_registration_mode_requires_valid_invitation(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    owner_email = f"owner3-{suffix}@example.com"
    invitee_email = f"invitee3-{suffix}@example.com"

    await create_verified_user(client, owner_email, "Owner Three")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Invitation Home"})
    assert group.status_code == 201
    home_id = group.json()["id"]

    invitation = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={"group_id": home_id, "email": invitee_email, "role": "adult_member"},
    )
    assert invitation.status_code == 201

    async with SessionFactory() as db:
        row = await db.scalar(
            select(Invitation).where(
                Invitation.group_id == uuid.UUID(home_id),
                Invitation.email == invitee_email,
            )
        )
        assert row is not None
        token = derived_token(row.id, "invitation", get_settings().secret_key.get_secret_value())

    invitation_only = get_settings().model_copy(update={"registration_mode": "invitation_only"})
    app.dependency_overrides[get_settings] = lambda: invitation_only
    try:
        rejected = await unsafe(
            client,
            "POST",
            "/api/v1/auth/register",
            json={
                "email": f"other-{suffix}@example.com",
                "display_name": "Other",
                "password": PASSWORD,
            },
        )
        assert rejected.status_code == 403

        accepted = await unsafe(
            client,
            "POST",
            "/api/v1/auth/register",
            json={
                "email": invitee_email,
                "display_name": "Invited",
                "password": PASSWORD,
                "invitation_token": token,
            },
        )
        assert accepted.status_code == 202
    finally:
        app.dependency_overrides.pop(get_settings, None)
