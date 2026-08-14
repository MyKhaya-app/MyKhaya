"""members.external_invites.enabled: Extended Family/Friend is a genuinely
reachable capability (PermissionProfile.explicit_sharing, selectively
granted shared_resources) — not a placeholder — so it gets real enforcement,
independent of home.max_members, at both invitation creation and the
member-relationship-change endpoint. See
docs/architecture/commercial-entitlements.md "Free plan enforcement pass,
part 2".
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
from mykhaya.models import (
    ActionToken,
    HouseholdRelationship,
    Membership,
    PermissionProfile,
    Role,
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


async def _add_ordinary_member_directly(home_id: uuid.UUID, email: str, name: str) -> User:
    """Registers a second adult and adds them as an ordinary (partner)
    household member by direct DB insert — bypassing invite()/accept(),
    which would otherwise be an extra call against the same
    "household-invitation" rate-limit bucket every other invitation test in
    the suite shares, for tests where the invite itself isn't what's under
    test (only the later relationship *change* is)."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as second_client:
        user = await create_verified_user(second_client, email, name)
    async with SessionFactory() as db:
        db.add(
            Membership(
                group_id=home_id,
                user_id=user.id,
                role=Role.adult_member,
                relationship=HouseholdRelationship.partner,
                permission_profile=PermissionProfile.standard_partner,
            )
        )
        await db.commit()
    return user


@pytest.mark.asyncio
async def test_free_home_cannot_invite_an_extended_family_member(client: AsyncClient) -> None:
    home_id = await _make_home(client, _suffix())
    response = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={
            "group_id": str(home_id),
            "email": f"guest-{_suffix()}@example.com",
            "relationship": "extended_family",
        },
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "plan_feature_unavailable"
    assert detail["entitlement"] == "members.external_invites.enabled"


@pytest.mark.asyncio
async def test_free_home_cannot_invite_a_friend(client: AsyncClient) -> None:
    home_id = await _make_home(client, _suffix())
    response = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={
            "group_id": str(home_id),
            "email": f"guest-{_suffix()}@example.com",
            "relationship": "friend",
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["entitlement"] == "members.external_invites.enabled"


@pytest.mark.asyncio
async def test_family_home_can_invite_an_extended_family_member(client: AsyncClient) -> None:
    home_id = await _make_home(client, _suffix())
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    response = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={
            "group_id": str(home_id),
            "email": f"guest-{_suffix()}@example.com",
            "relationship": "extended_family",
            "shared_resources": ["calendar"],
        },
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_downgraded_home_cannot_convert_an_existing_member_to_extended_family(
    client: AsyncClient,
) -> None:
    home_id = await _make_home(client, _suffix())
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    second_user = await _add_ordinary_member_directly(
        home_id, f"second-{_suffix()}@example.com", "Second Member"
    )

    await _set_subscription(home_id, plan=SubscriptionPlan.free)

    convert = await unsafe(
        client,
        "PATCH",
        f"/api/v1/groups/{home_id}/members/{second_user.id}",
        json={
            "relationship": "extended_family",
            "permission_profile": None,
            "permission_overrides": {},
            "shared_resources": ["calendar"],
            "confirmed": True,
        },
    )
    assert convert.status_code == 403
    detail = convert.json()["detail"]
    assert detail["code"] == "plan_feature_unavailable"
    assert detail["entitlement"] == "members.external_invites.enabled"


@pytest.mark.asyncio
async def test_downgraded_home_can_still_edit_an_existing_external_member(
    client: AsyncClient,
) -> None:
    home_id = await _make_home(client, _suffix())
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    second_email = f"second-{_suffix()}@example.com"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as second_client:
        second_user = await create_verified_user(second_client, second_email, "Second Member")
    async with SessionFactory() as db:
        db.add(
            Membership(
                group_id=home_id,
                user_id=second_user.id,
                role=Role.guest,
                relationship=HouseholdRelationship.extended_family,
                permission_profile=PermissionProfile.explicit_sharing,
                shared_resources=[],
            )
        )
        await db.commit()

    await _set_subscription(home_id, plan=SubscriptionPlan.free)

    # Still Extended Family, but granting the Calendar share now — a
    # transition-safe edit of an already-external member, not a *new*
    # transition into that state, so it must remain allowed.
    edit = await unsafe(
        client,
        "PATCH",
        f"/api/v1/groups/{home_id}/members/{second_user.id}",
        json={
            "relationship": "extended_family",
            "permission_profile": None,
            "permission_overrides": {},
            "shared_resources": ["calendar"],
            "confirmed": True,
        },
    )
    assert edit.status_code == 200, edit.text
    assert edit.json()["shared_resources"] == ["calendar"]
