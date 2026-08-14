import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

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
    Invitation,
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
    # home.max_members restricts Free to a single person — this test is
    # about registration-mode validation, not commercial gating, so upgrade
    # to Family to be able to invite at all.
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, uuid.UUID(home_id))
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()

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


@pytest.mark.asyncio
async def test_weekly_recurrence_survives_dst_transition(client: AsyncClient) -> None:
    """A weekly 09:00 Europe/London event must still show 09:00 local time
    after the clocks change, not 08:00 or 10:00. UK clocks moved forward on
    2026-03-29. Regression test for the UTC-timedelta recurrence bug fixed
    in _expand_occurrences — see docs/design/visual-identity.md context and
    the fix itself in routers/calendar.py."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"dst-{suffix}@example.com", "DST Owner")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "DST Home"})
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

    # First occurrence: Tuesday 2026-03-24 09:00 Europe/London, still GMT
    # (UTC+0) — before the 2026-03-29 spring-forward.
    tz = ZoneInfo("Europe/London")
    first_local = datetime(2026, 3, 24, 9, 0, tzinfo=tz)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Weekly team call",
            "start_at": first_local.astimezone(UTC).isoformat(),
            "end_at": (first_local + timedelta(hours=1)).astimezone(UTC).isoformat(),
            "timezone": "Europe/London",
            "is_all_day": False,
            "member_ids": [],
            "recurrence": "weekly",
            "recurrence_interval": 1,
        },
    )
    assert created.status_code == 201

    # Query a range spanning three weeks after the spring-forward, so the
    # occurrence on 2026-04-14 falls after clocks moved to BST (UTC+1).
    listed = await client.get(
        f"/api/v1/homes/{home_id}/events",
        params={
            "start_at": datetime(2026, 4, 13, tzinfo=UTC).isoformat(),
            "end_at": datetime(2026, 4, 16, tzinfo=UTC).isoformat(),
        },
    )
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert items, "expected an occurrence in the post-DST week"
    occurrence_start = datetime.fromisoformat(items[0]["start_at"])
    local_start = occurrence_start.astimezone(tz)
    assert local_start.hour == 9, (
        f"expected 09:00 local time after DST, got {local_start.isoformat()} "
        "— weekly recurrence is drifting across the clock change"
    )


async def _home_with_calendar(client: AsyncClient, name: str) -> str:
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert group.status_code == 201
    home_id = group.json()["id"]
    async with SessionFactory() as db:
        db.add(
            FeatureOverride(
                feature_key=FeatureKey.calendar, group_id=uuid.UUID(home_id), enabled=True
            )
        )
        await db.commit()
    return home_id


@pytest.mark.asyncio
async def test_event_label_create_update_rename_recolour_and_duplicate_name(
    client: AsyncClient,
) -> None:
    """Calendar/category colour, not who created the event, is what an event
    shows — see docs/design/visual-identity.md. Labels are created and later
    renamed, recoloured and disabled through the same colour_token palette
    used for member colours."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"labeladmin-{suffix}@example.com", "Label Admin")
    home_id = await _home_with_calendar(client, "Label Home")

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/event-labels",
        json={"name": "Sport", "color": "emerald"},
    )
    assert created.status_code == 201
    label = created.json()
    assert label["color"] == "emerald"
    assert label["is_active"] is True

    # An unrecognised colour token is rejected at the schema, not stored.
    invalid_colour = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/event-labels",
        json={"name": "Bad Colour", "color": "not-a-real-colour"},
    )
    assert invalid_colour.status_code == 422

    # Duplicate name within the same home is rejected, not silently accepted
    # as a second identical category.
    duplicate = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/event-labels",
        json={"name": "Sport", "color": "blue"},
    )
    assert duplicate.status_code == 409

    # Rename and recolour independently.
    renamed = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/event-labels/{label['id']}",
        json={"name": "Football"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Football"
    assert renamed.json()["color"] == "emerald"  # unchanged by a name-only update

    recoloured = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/event-labels/{label['id']}",
        json={"color": "sky"},
    )
    assert recoloured.status_code == 200
    assert recoloured.json()["color"] == "sky"
    assert recoloured.json()["name"] == "Football"  # unchanged by a colour-only update

    # Two different labels may share the same colour — not blocked.
    second = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/event-labels",
        json={"name": "Athletics", "color": "sky"},
    )
    assert second.status_code == 201

    # Disable, then confirm it drops out of the active listing.
    disabled = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/event-labels/{label['id']}",
        json={"is_active": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False
    listed = await client.get(f"/api/v1/homes/{home_id}/event-labels")
    assert label["id"] not in {row["id"] for row in listed.json()}


@pytest.mark.asyncio
async def test_event_label_update_requires_calendar_edit_all(client: AsyncClient) -> None:
    """A household member without calendar.edit_all (e.g. an explicit-sharing
    friend/extended-family profile) cannot rename or recolour a shared
    calendar/category — that's shared household structure, gated the same
    way label creation already is."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"labelowner-{suffix}@example.com", "Label Owner")
    home_id = await _home_with_calendar(client, "Label Perms Home")

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/event-labels",
        json={"name": "Outing", "color": "coral"},
    )
    assert created.status_code == 201
    label_id = created.json()["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as friend_client:
        friend_email = f"labelfriend-{suffix}@example.com"
        await create_verified_user(friend_client, friend_email, "Label Friend")
        async with SessionFactory() as db:
            user = await db.scalar(select(User).where(User.email == friend_email))
            assert user is not None
            db.add(
                Membership(
                    group_id=uuid.UUID(home_id),
                    user_id=user.id,
                    role=Role.guest,
                    relationship=HouseholdRelationship.friend,
                    permission_profile=PermissionProfile.explicit_sharing,
                )
            )
            await db.commit()

        blocked = await unsafe(
            friend_client,
            "PATCH",
            f"/api/v1/homes/{home_id}/event-labels/{label_id}",
            json={"color": "rose"},
        )
        assert blocked.status_code == 403

    unchanged = await client.get(f"/api/v1/homes/{home_id}/event-labels")
    assert next(row for row in unchanged.json() if row["id"] == label_id)["color"] == "coral"


@pytest.mark.asyncio
async def test_recurring_event_occurrences_keep_consistent_label_colour(
    client: AsyncClient,
) -> None:
    """One event, one colour — every expanded occurrence of a recurring
    event must carry the same label colour, the same identity every week,
    matching the continuity the month view relies on for multi-day/
    cross-week spans."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    await create_verified_user(client, f"recurcolour-{suffix}@example.com", "Recur Colour")
    home_id = await _home_with_calendar(client, "Recur Colour Home")

    label = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/event-labels",
        json={"name": "Practice", "color": "violet"},
    )
    assert label.status_code == 201
    label_id = label.json()["id"]

    start_at = datetime.now(UTC) + timedelta(days=1)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Weekly practice",
            "start_at": start_at.isoformat(),
            "end_at": (start_at + timedelta(hours=1)).isoformat(),
            "timezone": "Europe/London",
            "is_all_day": False,
            "member_ids": [],
            "label_id": label_id,
            "recurrence": "weekly",
            "recurrence_interval": 1,
        },
    )
    assert created.status_code == 201

    listed = await client.get(
        f"/api/v1/homes/{home_id}/events",
        params={
            "start_at": start_at.isoformat(),
            "end_at": (start_at + timedelta(days=35)).isoformat(),
        },
    )
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) >= 4, "expected multiple weekly occurrences in a 5-week window"
    assert all(item["label"]["color"] == "violet" for item in items)
    assert all(item["label"]["id"] == label_id for item in items)
