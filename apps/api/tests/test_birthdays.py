"""Tests for birthdays (Stage 7): annual month/day occurrence math (including the Feb 29
edge case), self-service and guardian-controlled birthday fields, child-privacy-safe
visibility on GET /homes/{home_id}/birthdays, the durable scan/deliver pair, and daily
briefing integration.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import get_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    ChildProfile,
    FeatureKey,
    FeatureOverride,
    HouseholdRelationship,
    Membership,
    Notification,
    OutboxEvent,
    PermissionProfile,
    Role,
    SubscriptionPlan,
    TokenPurpose,
    User,
)
from mykhaya.notifications.birthday_occurrences import is_birthday_date, next_birthday_date
from mykhaya.notifications.birthdays import (
    BIRTHDAY_TOPIC,
    deliver_birthday_reminder,
    scan_due_birthdays,
)
from mykhaya.notifications.briefing import _birthdays_for_user_today
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


def unique_email(prefix: str) -> str:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    return f"{prefix}-{suffix}@example.com"


async def create_verified_user(client: AsyncClient, email: str, name: str) -> uuid.UUID:
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
        user_id = user.id
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
        client, "POST", "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200
    return user_id


async def create_home(client: AsyncClient, name: str = "Birthday Test Home") -> uuid.UUID:
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert group.status_code == 201
    home_id = uuid.UUID(group.json()["id"])
    async with SessionFactory() as db:
        db.add(
            FeatureOverride(feature_key=FeatureKey.notifications, group_id=home_id, enabled=True)
        )
        # These tests are about birthday visibility/scheduling, not commercial
        # plan enforcement — a child adds a Membership row (home.max_members),
        # so every caller of this helper needs Family, not just the ones that
        # happen to add a child today.
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()
    return home_id


@pytest.fixture(autouse=True)
async def clean_birthday_outbox() -> AsyncIterator[None]:
    yield
    async with SessionFactory() as db:
        await db.execute(delete(OutboxEvent).where(OutboxEvent.topic == BIRTHDAY_TOPIC))
        await db.commit()


# --- occurrence math -------------------------------------------------------


def test_is_birthday_date_regular() -> None:
    assert is_birthday_date(6, 15, date(2026, 6, 15))
    assert not is_birthday_date(6, 15, date(2026, 6, 16))
    assert not is_birthday_date(6, 15, date(2026, 7, 15))


def test_is_birthday_date_feb29_observed_on_feb28_in_non_leap_years() -> None:
    assert is_birthday_date(2, 29, date(2026, 2, 28))  # 2026 is not a leap year
    assert not is_birthday_date(2, 29, date(2024, 2, 28))  # 2024 is a leap year
    assert is_birthday_date(2, 29, date(2024, 2, 29))


def test_next_birthday_date_this_year_or_rolled_to_next() -> None:
    assert next_birthday_date(6, 15, date(2026, 1, 1)) == date(2026, 6, 15)
    assert next_birthday_date(6, 15, date(2026, 6, 15)) == date(2026, 6, 15)
    assert next_birthday_date(6, 15, date(2026, 6, 16)) == date(2027, 6, 15)


# --- self-service and guardian-controlled fields ----------------------------


@pytest.mark.asyncio
async def test_user_can_set_and_view_own_birthday(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("self"), "Self Owner")
    updated = await unsafe(
        client,
        "PUT",
        "/api/v1/users/me/birthday",
        json={"birth_month": 3, "birth_day": 21, "birth_year": 1990},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["birth_month"] == 3
    assert updated.json()["birth_day"] == 21
    assert updated.json()["birth_year"] == 1990

    me = await client.get("/api/v1/users/me")
    assert me.json()["birth_month"] == 3


@pytest.mark.asyncio
async def test_invalid_birthday_date_rejected(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("invalid"), "Invalid Owner")
    response = await unsafe(
        client, "PUT", "/api/v1/users/me/birthday", json={"birth_month": 2, "birth_day": 30}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_guardian_can_set_child_birthday_and_visibility(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("guardian"), "Guardian")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Child Birthday Home"})
    home_id = group.json()["id"]
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, uuid.UUID(home_id))
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()
    members = await client.get(f"/api/v1/groups/{home_id}/members")
    owner_membership_id = members.json()[0]["membership_id"]

    child = await unsafe(
        client,
        "POST",
        f"/api/v1/groups/{home_id}/children",
        json={
            "display_name": "Young Person",
            "age_band": "under_13",
            "guardian_membership_ids": [owner_membership_id],
        },
    )
    assert child.status_code == 201
    child_row = child.json()
    assert child_row["birthday_visible"] is False
    assert child_row["birth_month"] is None

    updated = await unsafe(
        client,
        "PUT",
        f"/api/v1/groups/{home_id}/children/{child_row['membership_id']}/birthday",
        json={
            "birth_month": 9,
            "birth_day": 5,
            "birthday_visible": True,
            "reason": "Adding the child's birthday for reminders",
            "confirmed": True,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["birth_month"] == 9
    assert updated.json()["birthday_visible"] is True


@pytest.mark.asyncio
async def test_non_guardian_cannot_set_child_birthday(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("owner3"), "Owner")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Restricted Home"})
    home_id = group.json()["id"]
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, uuid.UUID(home_id))
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()
    members = await client.get(f"/api/v1/groups/{home_id}/members")
    owner_membership_id = members.json()[0]["membership_id"]
    child = await unsafe(
        client,
        "POST",
        f"/api/v1/groups/{home_id}/children",
        json={
            "display_name": "Kid",
            "age_band": "under_13",
            "guardian_membership_ids": [owner_membership_id],
        },
    )
    child_row = child.json()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        await create_verified_user(other_client, unique_email("stranger"), "Stranger")
        response = await unsafe(
            other_client,
            "PUT",
            f"/api/v1/groups/{home_id}/children/{child_row['membership_id']}/birthday",
            json={
                "birth_month": 1,
                "birth_day": 1,
                "birthday_visible": True,
                "reason": "Should not be permitted",
                "confirmed": True,
            },
        )
        assert response.status_code in (403, 404)


# --- GET /homes/{home_id}/birthdays -----------------------------------------


@pytest.mark.asyncio
async def test_list_birthdays_respects_child_visibility(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("listowner"), "Owner")
    home_id = await create_home(client)
    await unsafe(
        client, "PUT", "/api/v1/users/me/birthday", json={"birth_month": 4, "birth_day": 10}
    )
    members = await client.get(f"/api/v1/groups/{home_id}/members")
    owner_membership_id = members.json()[0]["membership_id"]
    child = await unsafe(
        client,
        "POST",
        f"/api/v1/groups/{home_id}/children",
        json={
            "display_name": "Hidden Kid",
            "age_band": "under_13",
            "guardian_membership_ids": [owner_membership_id],
        },
    )
    child_row = child.json()
    await unsafe(
        client,
        "PUT",
        f"/api/v1/groups/{home_id}/children/{child_row['membership_id']}/birthday",
        json={
            "birth_month": 8,
            "birth_day": 1,
            "birthday_visible": False,
            "reason": "Keep private for now",
            "confirmed": True,
        },
    )

    listed = await client.get(f"/api/v1/homes/{home_id}/birthdays")
    assert listed.status_code == 200
    owner_names = {item["display_name"] for item in listed.json()["items"]}
    assert "Owner" in owner_names
    assert "Hidden Kid" not in owner_names

    await unsafe(
        client,
        "PUT",
        f"/api/v1/groups/{home_id}/children/{child_row['membership_id']}/birthday",
        json={
            "birth_month": 8,
            "birth_day": 1,
            "birthday_visible": True,
            "reason": "Now visible",
            "confirmed": True,
        },
    )
    listed_again = await client.get(f"/api/v1/homes/{home_id}/birthdays")
    names_after = {item["display_name"] for item in listed_again.json()["items"]}
    assert "Hidden Kid" in names_after


# --- scan and delivery --------------------------------------------------


async def birthday_rows(owner_type: str, owner_id: str) -> list[OutboxEvent]:
    async with SessionFactory() as db:
        rows = (
            await db.scalars(select(OutboxEvent).where(OutboxEvent.topic == BIRTHDAY_TOPIC))
        ).all()
        return [
            row
            for row in rows
            if row.payload.get("owner_type") == owner_type
            and row.payload.get("owner_id") == owner_id
        ]


@pytest.mark.asyncio
async def test_scan_is_idempotent_for_a_due_birthday(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("scanbday"), "Scan Owner")
    await create_home(client)
    today = datetime.now(UTC).date()
    async with SessionFactory() as db:
        user = await db.get(User, user_id)
        assert user is not None
        user.birth_month = today.month
        user.birth_day = today.day
        user.timezone = "Europe/London"
        await db.commit()

        await scan_due_birthdays(db, get_settings())
        rows = await birthday_rows("user", str(user_id))
        await scan_due_birthdays(db, get_settings())
        rows_after = await birthday_rows("user", str(user_id))
        assert len(rows_after) == len(rows)
        assert len(rows) <= 1
        if rows:
            rows[0].processed_at = datetime.now(UTC)
            await db.commit()
            await scan_due_birthdays(db, get_settings())
            assert len(await birthday_rows("user", str(user_id))) == 1


@pytest.mark.asyncio
async def test_deliver_sends_self_and_household_variants(client: AsyncClient) -> None:
    birthday_user_id = await create_verified_user(client, unique_email("bday"), "Birthday Person")
    home_id = await create_home(client)

    other_id: uuid.UUID
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        other_id = await create_verified_user(
            other_client, unique_email("wellwisher"), "Well Wisher"
        )

    async with SessionFactory() as db:
        db.add(
            Membership(
                group_id=home_id,
                user_id=other_id,
                role=Role.adult_member,
                relationship=HouseholdRelationship.partner,
                permission_profile=PermissionProfile.standard_partner,
            )
        )
        await db.commit()

    today = datetime.now(UTC).date()
    async with SessionFactory() as db:
        user = await db.get(User, birthday_user_id)
        assert user is not None
        user.birth_month = today.month
        user.birth_day = today.day
        await db.commit()

        await deliver_birthday_reminder(
            db, get_settings(), "user", str(birthday_user_id), today.year
        )
        await db.commit()

        self_notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == birthday_user_id)
        )
        other_notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == other_id)
        )
        assert self_notification is not None
        assert "Happy Birthday" in self_notification.title
        assert other_notification is not None
        assert "birthday" in other_notification.title.lower()
        assert other_notification.body == f"Today is {user.display_name}'s birthday."


@pytest.mark.asyncio
async def test_deliver_is_idempotent_per_recipient(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("idembday"), "Idem Owner")
    await create_home(client)
    today = datetime.now(UTC).date()
    async with SessionFactory() as db:
        user = await db.get(User, user_id)
        assert user is not None
        user.birth_month = today.month
        user.birth_day = today.day
        await db.commit()

        await deliver_birthday_reminder(db, get_settings(), "user", str(user_id), today.year)
        await deliver_birthday_reminder(db, get_settings(), "user", str(user_id), today.year)
        await db.commit()
        notifications = (
            await db.scalars(select(Notification).where(Notification.recipient_user_id == user_id))
        ).all()
        assert len(notifications) == 1


@pytest.mark.asyncio
async def test_deliver_child_birthday_respects_visibility_toggle(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("guardian2"), "Guardian")
    home_id = await create_home(client)
    members = await client.get(f"/api/v1/groups/{home_id}/members")
    owner_membership_id = members.json()[0]["membership_id"]
    child = await unsafe(
        client,
        "POST",
        f"/api/v1/groups/{home_id}/children",
        json={
            "display_name": "Kid",
            "age_band": "under_13",
            "guardian_membership_ids": [owner_membership_id],
        },
    )
    child_row = child.json()
    today = datetime.now(UTC).date()
    await unsafe(
        client,
        "PUT",
        f"/api/v1/groups/{home_id}/children/{child_row['membership_id']}/birthday",
        json={
            "birth_month": today.month,
            "birth_day": today.day,
            "birthday_visible": False,
            "reason": "Not visible yet",
            "confirmed": True,
        },
    )

    async with SessionFactory() as db:
        profile = await db.scalar(
            select(ChildProfile).where(
                ChildProfile.membership_id == uuid.UUID(child_row["membership_id"])
            )
        )
        assert profile is not None
        await deliver_birthday_reminder(db, get_settings(), "child", str(profile.id), today.year)
        await db.commit()
        notification = await db.scalar(
            select(Notification).where(Notification.related_entity_id == profile.id)
        )
        assert notification is None  # not visible — nothing sent


# --- briefing integration --------------------------------------------------


@pytest.mark.asyncio
async def test_briefing_includes_own_birthday_phrase(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("briefbday"), "Briefing Birthday")
    await create_home(client)
    today = datetime.now(UTC).date()
    async with SessionFactory() as db:
        user = await db.get(User, user_id)
        assert user is not None
        user.birth_month = today.month
        user.birth_day = today.day
        await db.commit()

        phrases = await _birthdays_for_user_today(db, user_id, today)
        assert phrases == ["it's your birthday"]


@pytest.mark.asyncio
async def test_briefing_excludes_hidden_child_birthday(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("briefhidden"), "Owner")
    home_id = await create_home(client)
    members = await client.get(f"/api/v1/groups/{home_id}/members")
    owner_membership_id = members.json()[0]["membership_id"]
    child = await unsafe(
        client,
        "POST",
        f"/api/v1/groups/{home_id}/children",
        json={
            "display_name": "Kid",
            "age_band": "under_13",
            "guardian_membership_ids": [owner_membership_id],
        },
    )
    child_row = child.json()
    today = datetime.now(UTC).date()
    await unsafe(
        client,
        "PUT",
        f"/api/v1/groups/{home_id}/children/{child_row['membership_id']}/birthday",
        json={
            "birth_month": today.month,
            "birth_day": today.day,
            "birthday_visible": False,
            "reason": "Not visible",
            "confirmed": True,
        },
    )

    async with SessionFactory() as db:
        phrases = await _birthdays_for_user_today(db, user_id, today)
        assert phrases == []
