"""Shared family events must be explicitly protected by events.shared.enabled
— not indirectly by home.max_members. A downgraded Family Home that kept
its existing members (the member limit only blocks *new* growth, never
evicts anyone) must still be blocked from creating new shared events or
adding new participants to an existing one, while historical shared events
and their participant sets survive the downgrade untouched. See
docs/architecture/commercial-entitlements.md "Shared family events are now
enforced".
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

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


async def _set_subscription(home_id: uuid.UUID, **fields: object) -> None:
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        for key, value in fields.items():
            setattr(subscription, key, value)
        await db.commit()


def _suffix() -> str:
    return datetime.now(UTC).strftime("%H%M%S%f")


async def _add_member_directly(home_id: uuid.UUID, email: str, name: str) -> uuid.UUID:
    """Registers a second adult and adds them as a full household member by
    direct DB insert — bypassing the invite()/accept() HTTP flow, which is
    orthogonal to what shared-event enforcement tests are actually about
    (same pattern as test_calendar_notifications.py's _join_home), and which
    would otherwise run this file into the "household-invitation" endpoint's
    own rate limit given how many Homes-with-a-second-member these tests
    need."""
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
    return user.id


async def _make_family_home_with_two_members(
    client: AsyncClient, suffix: str
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Registers an owner, creates a Home, upgrades it to Family, adds a
    second member. Returns (home_id, owner_user_id, second_user_id)."""
    owner = await create_verified_user(client, f"owner-{suffix}@example.com", "Owner")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Shared Event Home"})
    assert group.status_code == 201
    home_id = uuid.UUID(group.json()["id"])
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    async with SessionFactory() as db:
        db.add(FeatureOverride(feature_key=FeatureKey.calendar, group_id=home_id, enabled=True))
        await db.commit()

    second_id = await _add_member_directly(home_id, f"second-{suffix}@example.com", "Second Member")
    return home_id, owner.id, second_id


def _event_body(member_ids: list[str], **overrides: object) -> dict:
    start = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)
    body = {
        "title": "Family outing",
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(hours=1)).isoformat(),
        "timezone": "Europe/London",
        "is_all_day": False,
        "member_ids": member_ids,
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_family_home_can_create_a_shared_event(client: AsyncClient) -> None:
    home_id, owner_id, second_id = await _make_family_home_with_two_members(client, _suffix())
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body([str(second_id)]),
    )
    assert response.status_code == 201, response.text
    assert set(response.json()["member_ids"]) == {str(owner_id), str(second_id)}


@pytest.mark.asyncio
async def test_downgraded_free_home_cannot_create_a_new_shared_event(client: AsyncClient) -> None:
    home_id, _owner_id, second_id = await _make_family_home_with_two_members(client, _suffix())
    await _set_subscription(home_id, plan=SubscriptionPlan.free)
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body([str(second_id)]),
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "plan_feature_unavailable"
    assert detail["entitlement"] == "events.shared.enabled"


@pytest.mark.asyncio
async def test_free_home_can_still_create_an_ordinary_personal_event(client: AsyncClient) -> None:
    home_id, _owner_id, _second_id = await _make_family_home_with_two_members(client, _suffix())
    await _set_subscription(home_id, plan=SubscriptionPlan.free)
    response = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/events", json=_event_body([])
    )
    assert response.status_code == 201, response.text
    assert len(response.json()["member_ids"]) == 1


@pytest.mark.asyncio
async def test_downgraded_home_retains_its_historical_shared_event(client: AsyncClient) -> None:
    home_id, _owner_id, second_id = await _make_family_home_with_two_members(client, _suffix())
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body([str(second_id)]),
    )
    assert created.status_code == 201
    event_id = created.json()["event_id"]

    await _set_subscription(home_id, plan=SubscriptionPlan.free)

    detail = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/events/{event_id}")
    assert detail.status_code == 200
    assert len(detail.json()["event"]["member_ids"]) == 2


@pytest.mark.asyncio
async def test_downgraded_home_cannot_convert_a_personal_event_to_shared(
    client: AsyncClient,
) -> None:
    home_id, _owner_id, second_id = await _make_family_home_with_two_members(client, _suffix())
    await _set_subscription(home_id, plan=SubscriptionPlan.free)
    created = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/events", json=_event_body([])
    )
    assert created.status_code == 201
    event = created.json()

    switch = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event['event_id']}",
        json=_event_body(
            [str(second_id)],
            expected_updated_at=event["updated_at"],
        ),
    )
    assert switch.status_code == 403
    detail = switch.json()["detail"]
    assert detail["code"] == "plan_feature_unavailable"
    assert detail["entitlement"] == "events.shared.enabled"


@pytest.mark.asyncio
async def test_downgraded_home_cannot_add_a_participant_to_its_historical_shared_event(
    client: AsyncClient,
) -> None:
    home_id, _owner_id, second_id = await _make_family_home_with_two_members(client, _suffix())
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body([str(second_id)]),
    )
    assert created.status_code == 201
    event = created.json()

    # A third member exists only so there's someone new to (attempt to) add —
    # added directly while still Family, so this isn't itself blocked.
    third_id = await _add_member_directly(home_id, f"third-{_suffix()}@example.com", "Third Member")

    await _set_subscription(home_id, plan=SubscriptionPlan.free)

    grow = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event['event_id']}",
        json=_event_body(
            [str(second_id), str(third_id)],
            expected_updated_at=event["updated_at"],
        ),
    )
    assert grow.status_code == 403
    assert grow.json()["detail"]["entitlement"] == "events.shared.enabled"


@pytest.mark.asyncio
async def test_editing_unrelated_fields_on_a_historical_shared_event_preserves_participants(
    client: AsyncClient,
) -> None:
    home_id, owner_id, second_id = await _make_family_home_with_two_members(client, _suffix())
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body([str(second_id)]),
    )
    assert created.status_code == 201
    event = created.json()

    await _set_subscription(home_id, plan=SubscriptionPlan.free)

    edited = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event['event_id']}",
        json=_event_body(
            [str(second_id)],
            title="Family outing (renamed)",
            expected_updated_at=event["updated_at"],
        ),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["title"] == "Family outing (renamed)"
    assert set(edited.json()["member_ids"]) == {str(second_id), str(owner_id)}


@pytest.mark.asyncio
async def test_downgraded_home_can_still_remove_a_participant_from_a_shared_event(
    client: AsyncClient,
) -> None:
    home_id, owner_id, second_id = await _make_family_home_with_two_members(client, _suffix())
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body([str(second_id)]),
    )
    assert created.status_code == 201
    event = created.json()

    await _set_subscription(home_id, plan=SubscriptionPlan.free)

    shrink = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event['event_id']}",
        json=_event_body([], expected_updated_at=event["updated_at"]),
    )
    assert shrink.status_code == 200, shrink.text
    assert shrink.json()["member_ids"] == [str(owner_id)]
