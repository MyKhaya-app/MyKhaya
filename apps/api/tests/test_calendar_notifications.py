"""Calendar event participant notifications — the actual bug this file
regression-tests: selecting a household member on an event never notified
them at all, because mykhaya.routers.calendar never called
mykhaya.notifications.engine.notify() for CalendarEventMember changes.

Reuses test_calendar.py's client/unsafe/create_verified_user fixtures rather
than re-declaring the whole calendar test harness.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_calendar import (  # noqa: F401
    ORIGIN,
    client,
    create_verified_user,
    unsafe,
)

from mykhaya.db import SessionFactory
from mykhaya.entitlements import get_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    FeatureKey,
    FeatureOverride,
    HouseholdRelationship,
    Membership,
    Notification,
    NotificationChannel,
    NotificationDelivery,
    NotificationPreferences,
    OutboxEvent,
    PermissionProfile,
    PushSubscription,
    Role,
    SubscriptionPlan,
    User,
)


def unique_email(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%H%M%S%f')}@example.com"


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
        # This file is about participant-notification delivery, not
        # commercial gating — every test here assigns other members to
        # events, which is the events.shared.enabled capability, so every
        # Home created through this helper needs Family.
        subscription = await get_home_subscription(db, uuid.UUID(home_id))
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()
    return home_id


async def _user_id(email: str) -> uuid.UUID:
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        return user.id


async def _join_home(home_id: str, email: str) -> uuid.UUID:
    """Registers and verifies a second user, then joins them to home_id as a
    standard adult member directly (bypassing the invitation-acceptance
    HTTP flow, which is orthogonal to what's under test here)."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as second_client:
        await create_verified_user(second_client, email, "Second Member")
    user_id = await _user_id(email)
    async with SessionFactory() as db:
        db.add(
            Membership(
                group_id=uuid.UUID(home_id),
                user_id=user_id,
                role=Role.adult_member,
                relationship=HouseholdRelationship.partner,
                permission_profile=PermissionProfile.standard_partner,
            )
        )
        await db.commit()
    return user_id


async def _notifications_for(recipient_id: uuid.UUID) -> list[Notification]:
    async with SessionFactory() as db:
        rows = (
            await db.scalars(
                select(Notification).where(Notification.recipient_user_id == recipient_id)
            )
        ).all()
        return list(rows)


async def _event_body(home_id: str, member_ids: list[str], **overrides: object) -> dict:
    # A fixed anchor, not datetime.now() re-evaluated on every call — so that
    # two calls with the same intent (e.g. re-saving "unchanged") actually
    # produce byte-identical start_at/end_at, rather than differing by
    # whatever real time elapsed between them and being misdetected as a
    # material change.
    start_at = datetime(2026, 6, 1, 18, 0, tzinfo=UTC)
    body = {
        "title": "Family dinner",
        "start_at": start_at.isoformat(),
        "end_at": (start_at + timedelta(hours=1)).isoformat(),
        "timezone": "Europe/London",
        "member_ids": member_ids,
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_creating_event_with_a_member_notifies_exactly_that_member(
    client: AsyncClient,
) -> None:
    creator_email = unique_email("creator")
    await create_verified_user(client, creator_email, "Creator")
    home_id = await _home_with_calendar(client, "Notify Home")
    creator_id = await _user_id(creator_email)

    member_id = await _join_home(home_id, unique_email("member"))

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=await _event_body(home_id, [str(member_id)]),
    )
    assert created.status_code == 201, created.text

    member_notifications = await _notifications_for(member_id)
    assert len(member_notifications) == 1
    assert member_notifications[0].notification_type == "event_invitation"
    assert member_notifications[0].deep_link == {
        "type": "calendar_event",
        "id": created.json()["event_id"],
    }

    # The creator never gets an "added to an event" notification for their
    # own action, even though they're also a CalendarEventMember row.
    creator_notifications = await _notifications_for(creator_id)
    assert creator_notifications == []


@pytest.mark.asyncio
async def test_creating_event_with_multiple_members_notifies_each_one(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("creator"), "Creator")
    home_id = await _home_with_calendar(client, "Multi Notify Home")
    member_a = await _join_home(home_id, unique_email("membera"))
    member_b = await _join_home(home_id, unique_email("memberb"))

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=await _event_body(home_id, [str(member_a), str(member_b)]),
    )
    assert created.status_code == 201, created.text

    assert len(await _notifications_for(member_a)) == 1
    assert len(await _notifications_for(member_b)) == 1


@pytest.mark.asyncio
async def test_resaving_an_event_unchanged_does_not_duplicate_the_added_notification(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("creator"), "Creator")
    home_id = await _home_with_calendar(client, "Resave Home")
    member_id = await _join_home(home_id, unique_email("member"))

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=await _event_body(home_id, [str(member_id)]),
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["event_id"]
    updated_at = created.json()["updated_at"]

    resaved = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        json=await _event_body(
            home_id, [str(member_id)], expected_updated_at=updated_at, description="Same plan"
        ),
    )
    assert resaved.status_code == 200, resaved.text

    assert len(await _notifications_for(member_id)) == 1


@pytest.mark.asyncio
async def test_title_only_edit_does_not_notify_assigned_members(client: AsyncClient) -> None:
    """A wording/typo fix to the title alone is deliberately excluded from
    "material change" — it shouldn't notify every assigned member the way an
    actual date/time/location change should."""
    await create_verified_user(client, unique_email("creator"), "Creator")
    home_id = await _home_with_calendar(client, "Title Only Edit Home")
    member_id = await _join_home(home_id, unique_email("member"))

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=await _event_body(home_id, [str(member_id)]),
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["event_id"]
    updated_at = created.json()["updated_at"]
    assert len(await _notifications_for(member_id)) == 1  # the initial "added" notification

    retitled = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        json=await _event_body(
            home_id,
            [str(member_id)],
            expected_updated_at=updated_at,
            title="Family dinner (corrected spelling)",
        ),
    )
    assert retitled.status_code == 200, retitled.text
    assert retitled.json()["title"] == "Family dinner (corrected spelling)"

    # Still just the one "added" notification — no "event updated" for a
    # title-only change.
    member_notifications = await _notifications_for(member_id)
    assert len(member_notifications) == 1
    assert member_notifications[0].notification_type == "event_invitation"


@pytest.mark.asyncio
async def test_editing_to_add_a_second_member_only_notifies_the_new_one(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("creator"), "Creator")
    home_id = await _home_with_calendar(client, "Add During Edit Home")
    member_a = await _join_home(home_id, unique_email("membera"))
    member_b = await _join_home(home_id, unique_email("memberb"))

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=await _event_body(home_id, [str(member_a)]),
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["event_id"]
    updated_at = created.json()["updated_at"]
    assert len(await _notifications_for(member_a)) == 1

    edited = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        json=await _event_body(
            home_id, [str(member_a), str(member_b)], expected_updated_at=updated_at
        ),
    )
    assert edited.status_code == 200, edited.text

    # member_a already had their one notification and gets no second one;
    # member_b, newly added, gets exactly one.
    assert len(await _notifications_for(member_a)) == 1
    assert len(await _notifications_for(member_b)) == 1


@pytest.mark.asyncio
async def test_removing_a_member_notifies_them_and_updating_details_notifies_remaining_members(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("creator"), "Creator")
    home_id = await _home_with_calendar(client, "Remove And Update Home")
    member_a = await _join_home(home_id, unique_email("membera"))
    member_b = await _join_home(home_id, unique_email("memberb"))

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=await _event_body(home_id, [str(member_a), str(member_b)]),
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["event_id"]
    updated_at = created.json()["updated_at"]

    new_start = datetime.now(UTC) + timedelta(days=2)
    edited = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        json=await _event_body(
            home_id,
            [str(member_a)],
            expected_updated_at=updated_at,
            start_at=new_start.isoformat(),
            end_at=(new_start + timedelta(hours=1)).isoformat(),
        ),
    )
    assert edited.status_code == 200, edited.text

    # member_b was removed: one "added" notification (from creation) plus
    # one "removed" notification, both type-tagged distinctly.
    member_b_notifications = await _notifications_for(member_b)
    assert len(member_b_notifications) == 2
    types = {n.notification_type for n in member_b_notifications}
    assert types == {"event_invitation", "event_updated"}
    removed = next(n for n in member_b_notifications if "removed" in n.title.lower())
    assert removed.body.startswith("Creator removed you from")

    # member_a stayed assigned and the time materially changed: one "added"
    # plus one "event updated" notification, not a third "added" duplicate.
    member_a_notifications = await _notifications_for(member_a)
    assert len(member_a_notifications) == 2
    assert {n.notification_type for n in member_a_notifications} == {
        "event_invitation",
        "event_updated",
    }


@pytest.mark.asyncio
async def test_deleting_an_event_notifies_remaining_assigned_members(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("creator"), "Creator")
    home_id = await _home_with_calendar(client, "Delete Notify Home")
    member_id = await _join_home(home_id, unique_email("member"))

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=await _event_body(home_id, [str(member_id)]),
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["event_id"]

    deleted = await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/events/{event_id}")
    assert deleted.status_code == 204

    notifications = await _notifications_for(member_id)
    types = {n.notification_type for n in notifications}
    assert "event_cancelled" in types


@pytest.mark.asyncio
async def test_notification_preferences_suppress_the_added_notification(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("creator"), "Creator")
    home_id = await _home_with_calendar(client, "Preferences Home")
    member_id = await _join_home(home_id, unique_email("member"))

    async with SessionFactory() as db:
        # create_verified_user's own email_verification send already lazily
        # created a default-settings row for this user (get_or_create_preferences),
        # so this must update it, not insert a second one.
        prefs = await db.scalar(
            select(NotificationPreferences).where(NotificationPreferences.user_id == member_id)
        )
        if prefs is None:
            db.add(NotificationPreferences(user_id=member_id, event_invitations_enabled=False))
        else:
            prefs.event_invitations_enabled = False
        await db.commit()

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=await _event_body(home_id, [str(member_id)]),
    )
    assert created.status_code == 201, created.text

    assert await _notifications_for(member_id) == []


@pytest.mark.asyncio
async def test_cross_household_user_cannot_be_added_as_a_member(client: AsyncClient) -> None:
    """A user with no Membership in the target home cannot be assigned to
    one of its events, and (belt-and-braces) receives no notification even
    if that guard were ever bypassed."""
    outsider_email = unique_email("outsider")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as outsider_client:
        await create_verified_user(outsider_client, outsider_email, "Outsider")
    outsider_id = await _user_id(outsider_email)

    await create_verified_user(client, unique_email("owner"), "Owner")
    home_id = await _home_with_calendar(client, "Isolated Home")
    rejected = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=await _event_body(home_id, [str(outsider_id)]),
    )
    assert rejected.status_code == 422

    assert await _notifications_for(outsider_id) == []


@pytest.mark.asyncio
async def test_push_fan_out_targets_the_added_members_own_devices(client: AsyncClient) -> None:
    creator_email = unique_email("creator")
    await create_verified_user(client, creator_email, "Creator")
    creator_id = await _user_id(creator_email)
    home_id = await _home_with_calendar(client, "Push Fan-out Home")
    member_id = await _join_home(home_id, unique_email("member"))

    suffix = uuid.uuid4().hex
    async with SessionFactory() as db:
        db.add(
            PushSubscription(
                user_id=member_id,
                endpoint=f"https://push.example.com/member-device-{suffix}",
                p256dh_key="member-p256dh",
                auth_key="member-auth",
            )
        )
        # The actor also has a device — fan-out must not target it too, only
        # the newly-added member's own registrations.
        db.add(
            PushSubscription(
                user_id=creator_id,
                endpoint=f"https://push.example.com/creator-device-{suffix}",
                p256dh_key="creator-p256dh",
                auth_key="creator-auth",
            )
        )
        await db.commit()

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=await _event_body(home_id, [str(member_id)]),
    )
    assert created.status_code == 201, created.text

    async with SessionFactory() as db:
        push_events = (
            await db.scalars(select(OutboxEvent).where(OutboxEvent.topic == "notification.push"))
        ).all()
        recipients = {e.payload.get("recipient_user_id") for e in push_events}
        assert str(member_id) in recipients
        assert str(creator_id) not in recipients

        deliveries = (
            await db.scalars(
                select(NotificationDelivery).where(
                    NotificationDelivery.recipient_user_id == member_id,
                    NotificationDelivery.channel == NotificationChannel.push,
                )
            )
        ).all()
        assert len(deliveries) == 1
