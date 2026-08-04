import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    AuditEvent,
    FeatureKey,
    FeatureOverride,
    Session as SessionRow,
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


async def register_and_verify(client: AsyncClient, email: str, name: str) -> None:
    response = await client.post(
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
            token.id, TokenPurpose.verify_email.value, get_settings().secret_key.get_secret_value()
        )
    verified = await client.post("/api/v1/auth/verify-email", json={"token": raw})
    assert verified.status_code == 200


async def mobile_login(client: AsyncClient, email: str) -> tuple[str, object]:
    response = await client.post(
        "/api/v1/auth/mobile/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200
    return response.json()["session_token"], response


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_web_login_never_returns_bearer_token(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"web-{suffix}@example.com"
    await register_and_verify(client, email, "Web User")
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    assert "session_token" not in login.json()
    assert client.cookies.get("mk_session")


@pytest.mark.asyncio
async def test_mobile_login_returns_token_and_sets_no_cookies(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"mobile-{suffix}@example.com"
    await register_and_verify(client, email, "Mobile User")
    token, response = await mobile_login(client, email)
    assert token
    assert "mk_session" not in response.cookies
    assert "mk_csrf" not in response.cookies
    assert client.cookies.get("mk_session") is None


@pytest.mark.asyncio
async def test_mobile_login_and_rotate_responses_are_not_cacheable(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"nocache-{suffix}@example.com"
    await register_and_verify(client, email, "No Cache")
    token, login_response = await mobile_login(client, email)
    assert login_response.headers.get("cache-control") == "no-store"
    assert login_response.headers.get("pragma") == "no-cache"

    rotated = await client.post("/api/v1/auth/mobile/sessions/rotate", headers=bearer(token))
    assert rotated.status_code == 200
    assert rotated.headers.get("cache-control") == "no-store"
    assert rotated.headers.get("pragma") == "no-cache"


@pytest.mark.asyncio
async def test_bearer_authentication_succeeds_on_protected_endpoint(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"protected-{suffix}@example.com"
    await register_and_verify(client, email, "Protected User")
    token, _ = await mobile_login(client, email)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as bearer_client:
        me = await bearer_client.get("/api/v1/users/me", headers=bearer(token))
        assert me.status_code == 200
        assert me.json()["email"] == email


@pytest.mark.asyncio
async def test_malformed_bearer_returns_401(client: AsyncClient) -> None:
    denied = await client.get("/api/v1/users/me", headers={"Authorization": "not-a-bearer-token"})
    assert denied.status_code == 401
    denied_empty = await client.get("/api/v1/users/me", headers={"Authorization": "Bearer "})
    assert denied_empty.status_code == 401


@pytest.mark.asyncio
async def test_invalid_bearer_does_not_fall_back_to_valid_cookie(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"fallback-{suffix}@example.com"
    await register_and_verify(client, email, "Fallback User")
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    assert client.cookies.get("mk_session")

    denied = await client.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert denied.status_code == 401


@pytest.mark.asyncio
async def test_bearer_authenticated_request_bypasses_csrf(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"csrf-{suffix}@example.com"
    await register_and_verify(client, email, "CSRF Bearer")
    token, _ = await mobile_login(client, email)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as bearer_client:
        created = await bearer_client.post(
            "/api/v1/groups", json={"name": "Bearer Home"}, headers=bearer(token)
        )
        assert created.status_code == 201


@pytest.mark.asyncio
async def test_expired_bearer_returns_401(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"expired-{suffix}@example.com"
    await register_and_verify(client, email, "Expired User")
    token, _ = await mobile_login(client, email)

    async with SessionFactory() as db:
        await db.execute(
            update(SessionRow)
            .where(SessionRow.user_id.in_(select(User.id).where(User.email == email)))
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as bearer_client:
        denied = await bearer_client.get("/api/v1/users/me", headers=bearer(token))
        assert denied.status_code == 401


@pytest.mark.asyncio
async def test_mobile_logout_revokes_session_and_old_token_is_rejected(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"logout-{suffix}@example.com"
    await register_and_verify(client, email, "Logout User")
    token, _ = await mobile_login(client, email)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as bearer_client:
        logout = await bearer_client.post("/api/v1/auth/mobile/logout", headers=bearer(token))
        assert logout.status_code == 204
        denied = await bearer_client.get("/api/v1/users/me", headers=bearer(token))
        assert denied.status_code == 401


@pytest.mark.asyncio
async def test_mobile_rotation_issues_new_token_and_invalidates_old(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"rotate-{suffix}@example.com"
    await register_and_verify(client, email, "Rotate User")
    old_token, _ = await mobile_login(client, email)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as bearer_client:
        rotated = await bearer_client.post(
            "/api/v1/auth/mobile/sessions/rotate", headers=bearer(old_token)
        )
        assert rotated.status_code == 200
        new_token = rotated.json()["session_token"]
        assert new_token != old_token

        old_rejected = await bearer_client.get("/api/v1/users/me", headers=bearer(old_token))
        assert old_rejected.status_code == 401

        new_accepted = await bearer_client.get("/api/v1/users/me", headers=bearer(new_token))
        assert new_accepted.status_code == 200


@pytest.mark.asyncio
async def test_cookie_transport_endpoints_reject_bearer_only_sessions(
    client: AsyncClient,
) -> None:
    """/auth/mobile/logout and /auth/mobile/sessions/rotate require bearer
    transport - a cookie-authenticated caller is rejected rather than
    silently operating on the wrong transport's semantics."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"transport-{suffix}@example.com"
    await register_and_verify(client, email, "Transport User")
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    csrf = client.cookies["mk_csrf"]

    denied = await client.post(
        "/api/v1/auth/mobile/logout", headers={"X-CSRF-Token": csrf}
    )
    assert denied.status_code == 400


@pytest.mark.asyncio
async def test_cross_household_isolation_unchanged_with_bearer_auth(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    owner_email = f"bearer-owner-{suffix}@example.com"
    outsider_email = f"bearer-outsider-{suffix}@example.com"
    await register_and_verify(client, owner_email, "Bearer Owner")
    owner_token, _ = await mobile_login(client, owner_email)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as owner_bearer_client:
        group = await owner_bearer_client.post(
            "/api/v1/groups", json={"name": "Bearer Isolated Home"}, headers=bearer(owner_token)
        )
        assert group.status_code == 201
        home_id = group.json()["id"]

        async with SessionFactory() as db:
            db.add(
                FeatureOverride(
                    feature_key=FeatureKey.calendar, group_id=uuid.UUID(home_id), enabled=True
                )
            )
            await db.commit()

        created = await owner_bearer_client.post(
            f"/api/v1/homes/{home_id}/events",
            headers=bearer(owner_token),
            json={
                "title": "Bearer Private Event",
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
        await register_and_verify(outsider, outsider_email, "Bearer Outsider")
        outsider_token, _ = await mobile_login(outsider, outsider_email)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
        ) as outsider_bearer_client:
            denied = await outsider_bearer_client.get(
                f"/api/v1/homes/{home_id}/events",
                headers=bearer(outsider_token),
                params={
                    "start_at": datetime.now(UTC).isoformat(),
                    "end_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                },
            )
            assert denied.status_code == 404


@pytest.mark.asyncio
async def test_bearer_token_never_written_to_audit_metadata(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"audit-{suffix}@example.com"
    await register_and_verify(client, email, "Audit User")
    token, _ = await mobile_login(client, email)

    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        events = (
            await db.scalars(select(AuditEvent).where(AuditEvent.actor_user_id == user.id))
        ).all()
        assert events
        for event in events:
            assert token not in str(event.metadata_)
