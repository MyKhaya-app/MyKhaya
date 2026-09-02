"""Tests for the Notification Engine core (Stage 2): preferences, in-app notifications,
idempotency, category gating, and ownership. Push/email channels are added in later
stages and are not exercised here.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.main import app
from mykhaya.models import ActionToken, Notification, NotificationDelivery, TokenPurpose, User
from mykhaya.notifications.deep_links import resolve_path, target
from mykhaya.notifications.engine import get_or_create_preferences, notify
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


def unique_email(prefix: str) -> str:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    return f"{prefix}-{suffix}@example.com"


@pytest.mark.asyncio
async def test_preferences_default_on_first_read(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("prefs"), "Prefs User")
    response = await client.get("/api/v1/notifications/preferences")
    assert response.status_code == 200
    body = response.json()
    assert body["push_enabled"] is True
    assert body["in_app_enabled"] is True
    assert body["daily_briefing_enabled"] is False
    assert body["briefing_time"] == "07:30"
    assert body["briefing_days"] == "daily"
    assert body["lock_screen_preview_level"] == "title_only"


@pytest.mark.asyncio
async def test_preferences_update_round_trips(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("prefs2"), "Prefs User")
    response = await unsafe(
        client,
        "PUT",
        "/api/v1/notifications/preferences",
        json={
            "push_enabled": False,
            "in_app_enabled": True,
            "email_enabled": True,
            "event_reminders_enabled": False,
            "event_invitations_enabled": True,
            "event_changes_enabled": True,
            "household_reminders_enabled": True,
            "daily_briefing_enabled": True,
            "briefing_time": "08:15",
            "briefing_days": "weekdays",
            "empty_day_briefing_enabled": False,
            "lock_screen_preview_level": "hidden",
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "07:00",
            "quiet_hours_critical_only": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["push_enabled"] is False
    assert body["event_reminders_enabled"] is False
    assert body["briefing_time"] == "08:15"
    assert body["briefing_days"] == "weekdays"
    assert body["lock_screen_preview_level"] == "hidden"
    assert body["quiet_hours_start"] == "22:00"
    assert body["quiet_hours_end"] == "07:00"


@pytest.mark.asyncio
async def test_notify_writes_in_app_notification_and_delivery() -> None:
    async with SessionFactory() as db:
        user = User(email=unique_email("notify"), display_name="Notify User")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id

    async with SessionFactory() as db:
        key = f"test:{uuid.uuid4()}"
        notification = await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="test",
            title="Hello",
            body="This is a test notification.",
            idempotency_key=key,
            deep_link=target("settings"),
        )
        await db.commit()
        assert notification is not None
        assert resolve_path(notification.deep_link) == "/settings/notifications"
        assert resolve_path(target("calendar_today")) == "/calendar"

    async with SessionFactory() as db:
        stored = await db.scalar(select(Notification).where(Notification.id == notification.id))
        assert stored is not None
        assert stored.title == "Hello"
        delivery = await db.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.idempotency_key == f"{key}:in_app"
            )
        )
        assert delivery is not None
        assert delivery.status.value == "sent"


@pytest.mark.asyncio
async def test_notify_is_idempotent() -> None:
    async with SessionFactory() as db:
        user = User(email=unique_email("idem"), display_name="Idem User")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id

    key = f"idem:{uuid.uuid4()}"
    async with SessionFactory() as db:
        first = await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="test",
            title="First",
            body="Body",
            idempotency_key=key,
        )
        await db.commit()
        assert first is not None

    async with SessionFactory() as db:
        second = await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="test",
            title="Second attempt, should not duplicate",
            body="Body",
            idempotency_key=key,
        )
        await db.commit()
        assert second is None

    async with SessionFactory() as db:
        count = len(
            (
                await db.scalars(
                    select(NotificationDelivery).where(
                        NotificationDelivery.idempotency_key == f"{key}:in_app"
                    )
                )
            ).all()
        )
        assert count == 1
        stored = (
            await db.scalars(select(Notification).where(Notification.recipient_user_id == user_id))
        ).all()
        assert len(stored) == 1
        assert stored[0].title == "First"


@pytest.mark.asyncio
async def test_notify_respects_category_preference_gate() -> None:
    async with SessionFactory() as db:
        user = User(email=unique_email("gate"), display_name="Gate User")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id
        prefs = await get_or_create_preferences(db, user_id)
        prefs.event_reminders_enabled = False
        await db.commit()

    async with SessionFactory() as db:
        result = await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="event_reminder",
            title="Swimming",
            body="Starts soon",
            idempotency_key=f"gate:{uuid.uuid4()}",
        )
        await db.commit()
        assert result is None

    async with SessionFactory() as db:
        stored = (
            await db.scalars(select(Notification).where(Notification.recipient_user_id == user_id))
        ).all()
        assert stored == []


def test_lists_and_wishlists_have_explicit_preference_gates_and_links() -> None:
    from mykhaya.models import NotificationPreferences
    from mykhaya.notifications.engine import _category_enabled

    prefs = NotificationPreferences(
        user_id=uuid.uuid4(), list_assignments_enabled=True, wishlist_sharing_enabled=True
    )
    assert _category_enabled(prefs, "list_item_assigned") is True
    assert _category_enabled(prefs, "wishlist_share_created") is True
    prefs.list_assignments_enabled = False
    prefs.wishlist_sharing_enabled = False
    assert _category_enabled(prefs, "list_item_assigned") is False
    assert _category_enabled(prefs, "wishlist_share_revoked") is False
    assert resolve_path(target("list", uuid.UUID(int=1))) == "/lists/00000000-0000-0000-0000-000000000001"
    assert resolve_path(target("wishlist", uuid.UUID(int=1))) == "/wish-lists/00000000-0000-0000-0000-000000000001"


@pytest.mark.asyncio
async def test_list_read_and_mark_all_read(client: AsyncClient) -> None:
    user_id = await create_verified_user(client, unique_email("list"), "List User")
    async with SessionFactory() as db:
        first_key = f"list1:{uuid.uuid4()}"
        second_key = f"list2:{uuid.uuid4()}"
        await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="test",
            title="First",
            body="Body one",
            idempotency_key=first_key,
        )
        await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="test",
            title="Second",
            body="Body two",
            idempotency_key=second_key,
        )
        await db.commit()

    listed = await client.get("/api/v1/notifications")
    assert listed.status_code == 200
    body = listed.json()
    assert body["unread_count"] == 2
    assert len(body["items"]) == 2
    notification_id = body["items"][0]["id"]

    read = await unsafe(client, "POST", f"/api/v1/notifications/{notification_id}/read")
    assert read.status_code == 200

    after_one_read = await client.get("/api/v1/notifications")
    assert after_one_read.json()["unread_count"] == 1

    mark_all = await unsafe(client, "POST", "/api/v1/notifications/read-all")
    assert mark_all.status_code == 200

    after_all_read = await client.get("/api/v1/notifications")
    assert after_all_read.json()["unread_count"] == 0


@pytest.mark.asyncio
async def test_cannot_read_another_users_notification(client: AsyncClient) -> None:
    other_user_id = await create_verified_user(client, unique_email("owner"), "Owner User")
    async with SessionFactory() as db:
        await notify(
            db,
            settings=get_settings(),
            recipient_user_id=other_user_id,
            notification_type="test",
            title="Not yours",
            body="Body",
            idempotency_key=f"priv:{uuid.uuid4()}",
        )
        await db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as second_client:
        await create_verified_user(second_client, unique_email("intruder"), "Intruder")
        listed = await second_client.get("/api/v1/notifications")
        assert listed.json()["items"] == []

        async with SessionFactory() as db:
            other_notification = await db.scalar(
                select(Notification).where(Notification.recipient_user_id == other_user_id)
            )
        assert other_notification is not None
        denied = await unsafe(
            second_client, "POST", f"/api/v1/notifications/{other_notification.id}/read"
        )
        assert denied.status_code == 404
