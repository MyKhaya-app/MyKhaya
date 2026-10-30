import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import func, select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import get_home_subscription
from mykhaya.main import app
from mykhaya.models import ActionToken, Group, SubscriptionPlan, TokenPurpose, User
from mykhaya.security import derived_token

ORIGIN = "http://localhost:8080"
PASSWORD = "Correct horse battery staple!"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


async def unsafe(client: AsyncClient, method: str, path: str, **kwargs: Any) -> Response:
    raw_headers = kwargs.pop("headers", {})
    headers: dict[str, str] = dict(raw_headers) if isinstance(raw_headers, dict) else {}
    csrf = client.cookies.get("mk_csrf")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


async def latest_token(email: str, purpose: TokenPurpose) -> str:
    async with SessionFactory() as db:
        row = await db.scalar(
            select(ActionToken)
            .join(User, User.id == ActionToken.user_id)
            .where(User.email == email, ActionToken.purpose == purpose)
            .order_by(ActionToken.created_at.desc())
        )
        assert row is not None
        return derived_token(row.id, purpose.value, get_settings().secret_key.get_secret_value())


async def create_verified_user(
    client: AsyncClient, email: str, name: str, **registration_fields: object
) -> None:
    response = await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={
            "email": email,
            "display_name": name,
            "password": PASSWORD,
            **registration_fields,
        },
    )
    assert response.status_code == 202
    token = await latest_token(email, TokenPurpose.verify_email)
    assert (
        await unsafe(client, "POST", "/api/v1/auth/verify-email", json={"token": token})
    ).status_code == 200
    login = await unsafe(
        client, "POST", "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200
    assert client.cookies.get("mk_session")
    assert client.cookies.get("mk_csrf")


@pytest.mark.asyncio
async def test_disabled_email_verification_allows_unverified_login(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"no-verification-{suffix}@example.com"
    registered = await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": "Local User", "password": PASSWORD},
    )
    assert registered.status_code == 202
    assert registered.json()["verification_required"] is True

    disabled_settings = get_settings().model_copy(update={"email_verification_enabled": False})
    app.dependency_overrides[get_settings] = lambda: disabled_settings
    try:
        login = await unsafe(
            client,
            "POST",
            "/api/v1/auth/login",
            json={"email": email, "password": PASSWORD},
        )
        assert login.status_code == 200
        assert login.json()["email_verified"] is False

        second_email = f"auto-verified-{suffix}@example.com"
        second = await unsafe(
            client,
            "POST",
            "/api/v1/auth/register",
            json={
                "email": second_email,
                "display_name": "Auto Verified",
                "password": PASSWORD,
            },
        )
        assert second.status_code == 202
        assert second.json()["verification_required"] is False
        async with SessionFactory() as db:
            user = await db.scalar(select(User).where(User.email == second_email))
            assert user is not None
            assert user.email_verified_at is not None
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.asyncio
async def test_onboarding_home_creation_is_idempotent_and_free_completion_is_explicit(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"onboarding-{suffix}@example.com", "Onboarding User")
    key = str(uuid.uuid4())

    first = await unsafe(
        client,
        "POST",
        "/api/v1/groups",
        json={"name": "Our Home", "onboarding_key": key},
    )
    assert first.status_code == 201
    first_id = first.json()["id"]

    retry = await unsafe(
        client,
        "POST",
        "/api/v1/groups",
        json={"name": "Our Home", "onboarding_key": key},
    )
    assert retry.status_code == 201
    assert retry.json()["id"] == first_id

    # A second browser/device using the same account and operation key must
    # converge even when both requests are in flight at once.
    concurrent_key = str(uuid.uuid4())
    async with (
        AsyncClient(
            transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
        ) as first_device,
        AsyncClient(
            transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
        ) as second_device,
    ):
        first_device.cookies.update(client.cookies)
        second_device.cookies.update(client.cookies)
        concurrent_responses = await asyncio.gather(
            unsafe(
                first_device,
                "POST",
                "/api/v1/groups",
                json={"name": "Concurrent Home", "onboarding_key": concurrent_key},
            ),
            unsafe(
                second_device,
                "POST",
                "/api/v1/groups",
                json={"name": "Concurrent Home", "onboarding_key": concurrent_key},
            ),
        )
    assert all(response.status_code == 201 for response in concurrent_responses)
    concurrent_id = concurrent_responses[0].json()["id"]
    assert len({response.json()["id"] for response in concurrent_responses}) == 1

    # The key is scoped to the authenticated account, so another account can
    # intentionally use the same client-generated key without gaining access
    # to this Home.
    other_email = f"onboarding-other-{suffix}@example.com"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        await create_verified_user(other_client, other_email, "Other Onboarding User")
        other_home = await unsafe(
            other_client,
            "POST",
            "/api/v1/groups",
            json={"name": "Other Home", "onboarding_key": key},
        )
        assert other_home.status_code == 201
        other_id = other_home.json()["id"]
        assert other_id not in {first_id, concurrent_id}
        assert (
            await unsafe(
                other_client,
                "POST",
                f"/api/v1/groups/{other_id}/onboarding/complete",
            )
        ).status_code == 200

    ambiguous_resume = await unsafe(
        client, "GET", "/api/v1/groups/onboarding/resume"
    )
    assert ambiguous_resume.status_code == 409

    completed = await unsafe(client, "POST", f"/api/v1/groups/{first_id}/onboarding/complete")
    assert completed.status_code == 200
    completed_concurrent = await unsafe(
        client, "POST", f"/api/v1/groups/{concurrent_id}/onboarding/complete"
    )
    assert completed_concurrent.status_code == 200
    assert (await unsafe(client, "GET", "/api/v1/groups/onboarding/resume")).status_code == 404

    # The idempotency scope is explicit: a normal Home create is still allowed.
    second = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Our Home"})
    assert second.status_code == 201
    assert second.json()["id"] != first_id

    async with SessionFactory() as db:
        count = await db.scalar(
            select(func.count(Group.id)).where(Group.id.in_([first_id, second.json()["id"]]))
        )
    assert count == 2


@pytest.mark.asyncio
async def test_onboarding_invitation_tenant_denial_and_removed_member(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    owner_email = f"owner-{suffix}@example.com"
    invitee_email = f"invitee-{suffix}@example.com"
    outsider_email = f"outsider-{suffix}@example.com"
    await create_verified_user(client, owner_email, "Home Owner")
    mass_assignment = await unsafe(
        client,
        "POST",
        "/api/v1/groups",
        json={"name": "Hales Home", "created_by": "00000000-0000-0000-0000-000000000000"},
    )
    assert mass_assignment.status_code == 422
    created = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Hales Home"})
    assert created.status_code == 201
    group_id = created.json()["id"]
    # home.max_members restricts Free to a single person — this test is
    # about tenant isolation/mass-assignment, not commercial gating, so
    # upgrade to Family to invite at all.
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, uuid.UUID(group_id))
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()
    invitation = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={"group_id": group_id, "email": invitee_email, "role": "adult_member"},
    )
    assert invitation.status_code == 201
    invitation_id = invitation.json()["id"]
    raw_invitation = derived_token(
        uuid.UUID(invitation_id),
        "invitation",
        get_settings().secret_key.get_secret_value(),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as invitee:
        await create_verified_user(invitee, invitee_email, "Invited Adult")
        accepted = await unsafe(
            invitee, "POST", "/api/v1/invitations/accept", json={"token": raw_invitation}
        )
        assert accepted.status_code == 200
        assert (
            await unsafe(
                invitee, "POST", "/api/v1/invitations/accept", json={"token": raw_invitation}
            )
        ).status_code == 400
        assert (await invitee.get(f"/api/v1/groups/{group_id}/members")).status_code == 200

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
        ) as outsider:
            await create_verified_user(outsider, outsider_email, "Outsider")
            denied = await outsider.get(f"/api/v1/groups/{group_id}")
            assert denied.status_code == 404

        me = (await invitee.get("/api/v1/users/me")).json()
        removed = await unsafe(client, "DELETE", f"/api/v1/groups/{group_id}/members/{me['id']}")
        assert removed.status_code == 204
        assert (await invitee.get(f"/api/v1/groups/{group_id}")).status_code == 404


@pytest.mark.asyncio
async def test_csrf_cors_reset_replay_and_session_rotation(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    email = f"security-{suffix}@example.com"
    await create_verified_user(client, email, "Security Test")
    missing_csrf = await client.post("/api/v1/groups", json={"name": "No CSRF"})
    assert missing_csrf.status_code == 403
    wrong_origin = await client.post(
        "/api/v1/groups",
        json={"name": "Wrong origin"},
        headers={"Origin": "https://evil.example", "X-CSRF-Token": client.cookies["mk_csrf"]},
    )
    assert wrong_origin.status_code == 403
    old_session = client.cookies["mk_session"]
    rotated = await unsafe(client, "POST", "/api/v1/auth/sessions/rotate", json={})
    assert rotated.status_code == 200
    assert client.cookies["mk_session"] != old_session
    assert (
        await unsafe(client, "POST", "/api/v1/auth/forgot-password", json={"email": email})
    ).status_code == 202
    reset_token = await latest_token(email, TokenPurpose.reset_password)
    assert (
        await unsafe(
            client,
            "POST",
            "/api/v1/auth/reset-password",
            json={"token": reset_token, "password": PASSWORD + " changed"},
        )
    ).status_code == 200
    assert (
        await unsafe(
            client,
            "POST",
            "/api/v1/auth/reset-password",
            json={"token": reset_token, "password": PASSWORD},
        )
    ).status_code == 400
