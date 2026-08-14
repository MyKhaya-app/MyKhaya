"""Free Plan Enforcement Pass: closes two direct member-add bypasses of
home.max_members that the Commercial Plan Cleanup task's invite-creation-only
check missed — invitation *acceptance* (a Home's effective plan can change
between an invite being sent and being accepted) and child-profile creation
(mykhaya.routers.children.create_child adds a Membership row directly, with
no invitation involved at all). Also covers the new
BillingStatusResponse.member_usage / household_routines_enabled fields that
drive the corresponding frontend gating. See
docs/architecture/commercial-entitlements.md "Free plan enforcement pass".
"""

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
from mykhaya.models import ActionToken, SubscriptionPlan, TokenPurpose, User
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


async def create_verified_user(client: AsyncClient, email: str, name: str) -> User:
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
            token.id, TokenPurpose.verify_email.value, get_settings().secret_key.get_secret_value()
        )
    verified = await unsafe(client, "POST", "/api/v1/auth/verify-email", json={"token": raw})
    assert verified.status_code == 200
    login = await unsafe(
        client, "POST", "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200
    return user


async def _make_home(client: AsyncClient, suffix: str) -> uuid.UUID:
    await create_verified_user(client, f"owner-{suffix}@example.com", "Owner")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Test Home"})
    assert group.status_code == 201
    return uuid.UUID(group.json()["id"])


async def _set_subscription(home_id: uuid.UUID, **fields: object) -> None:
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        for key, value in fields.items():
            setattr(subscription, key, value)
        await db.commit()


def _suffix() -> str:
    return datetime.now(UTC).strftime("%H%M%S%f")


# ---------------------------------------------------------------------------
# home.max_members — invitation ACCEPTANCE (not just creation)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invitation_acceptance_cannot_bypass_member_limit_after_downgrade(
    client: AsyncClient,
) -> None:
    """A Family Home invites someone (allowed — unlimited), then downgrades
    to Free before they respond. The invitation itself is untouched by the
    downgrade, but accepting it must not be able to push a Free Home past
    its single-person limit."""
    suffix = _suffix()
    home_id = await _make_home(client, suffix)
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    invitee_email = f"invitee-{suffix}@example.com"
    invitation = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={"group_id": str(home_id), "email": invitee_email},
    )
    assert invitation.status_code == 201
    invitation_id = invitation.json()["id"]
    raw_invitation = derived_token(
        uuid.UUID(invitation_id), "invitation", get_settings().secret_key.get_secret_value()
    )

    await _set_subscription(home_id, plan=SubscriptionPlan.free)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as invitee:
        await create_verified_user(invitee, invitee_email, "Invited Adult")
        accepted = await unsafe(
            invitee, "POST", "/api/v1/invitations/accept", json={"token": raw_invitation}
        )
        assert accepted.status_code == 403
        detail = accepted.json()["detail"]
        assert detail["code"] == "plan_limit_reached"
        assert detail["entitlement"] == "home.max_members"

    # The invitation itself is untouched — not silently revoked — so it can
    # still be accepted once the Home upgrades again.
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as invitee:
        await unsafe(
            invitee,
            "POST",
            "/api/v1/auth/login",
            json={"email": invitee_email, "password": PASSWORD},
        )
        await _set_subscription(home_id, plan=SubscriptionPlan.family)
        accepted = await unsafe(
            invitee, "POST", "/api/v1/invitations/accept", json={"token": raw_invitation}
        )
        assert accepted.status_code == 200


@pytest.mark.asyncio
async def test_invitation_acceptance_allowed_within_family_limit(client: AsyncClient) -> None:
    suffix = _suffix()
    home_id = await _make_home(client, suffix)
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    invitee_email = f"invitee-{suffix}@example.com"
    invitation = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={"group_id": str(home_id), "email": invitee_email},
    )
    assert invitation.status_code == 201
    raw_invitation = derived_token(
        uuid.UUID(invitation.json()["id"]),
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


# ---------------------------------------------------------------------------
# home.max_members — direct child-profile creation
# ---------------------------------------------------------------------------


async def _owner_membership_id(client: AsyncClient, home_id: uuid.UUID) -> str:
    members = await unsafe(client, "GET", f"/api/v1/groups/{home_id}/members")
    assert members.status_code == 200
    return members.json()[0]["membership_id"]


@pytest.mark.asyncio
async def test_free_home_cannot_add_a_child_beyond_the_member_limit(client: AsyncClient) -> None:
    """create_child adds a full Membership row directly — a second,
    entirely separate member-add path from invitations — and must respect
    the same home.max_members limit."""
    home_id = await _make_home(client, _suffix())
    owner_membership_id = await _owner_membership_id(client, home_id)
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/groups/{home_id}/children",
        json={
            "display_name": "Kid One",
            "age_band": "under_13",
            "guardian_membership_ids": [owner_membership_id],
        },
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "plan_limit_reached"
    assert detail["entitlement"] == "home.max_members"


@pytest.mark.asyncio
async def test_family_home_can_add_a_child(client: AsyncClient) -> None:
    home_id = await _make_home(client, _suffix())
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    owner_membership_id = await _owner_membership_id(client, home_id)
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/groups/{home_id}/children",
        json={
            "display_name": "Kid One",
            "age_band": "under_13",
            "guardian_membership_ids": [owner_membership_id],
        },
    )
    assert response.status_code == 201


# ---------------------------------------------------------------------------
# BillingStatusResponse: member_usage / household_routines_enabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_billing_status_reports_member_usage_and_household_routines(
    client: AsyncClient,
) -> None:
    home_id = await _make_home(client, _suffix())
    response = await unsafe(client, "GET", f"/api/v1/groups/{home_id}/billing")
    assert response.status_code == 200
    body = response.json()
    assert body["member_usage"] == {"count": 1, "limit": 1, "over_limit": False}
    assert body["household_routines_enabled"] is False

    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    response = await unsafe(client, "GET", f"/api/v1/groups/{home_id}/billing")
    assert response.status_code == 200
    body = response.json()
    assert body["member_usage"] == {"count": 1, "limit": None, "over_limit": False}
    assert body["household_routines_enabled"] is True
