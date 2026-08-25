"""External Calendar Sharing — lifecycle, permission enforcement, cross-Home
isolation, Free-plan recipient behaviour, and notification/briefing integration.
See mykhaya.routers.calendar_sharing and docs on the external-sharing model.
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
from mykhaya.household_permissions import Capability, capabilities_for
from mykhaya.main import app
from mykhaya.models import (
    FeatureKey,
    FeatureOverride,
    HouseholdRelationship,
    Membership,
    Notification,
    PermissionProfile,
    Role,
    SubscriptionPlan,
    User,
)
from mykhaya.notifications.briefing import _events_for_user_today
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
    return f"{prefix}-{datetime.now(UTC).strftime('%H%M%S%f')}@example.com"


async def create_verified_user(client: AsyncClient, email: str, name: str) -> None:
    response = await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": name, "password": PASSWORD},
    )
    assert response.status_code == 202, response.text
    from mykhaya.models import ActionToken, TokenPurpose

    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        token = await db.scalar(
            select(ActionToken)
            .where(ActionToken.user_id == user.id, ActionToken.purpose == TokenPurpose.verify_email)
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


async def _enable_home(home_id: str, *, family: bool = True) -> None:
    async with SessionFactory() as db:
        for key in (FeatureKey.calendar, FeatureKey.external_sharing, FeatureKey.notifications):
            db.add(FeatureOverride(feature_key=key, group_id=uuid.UUID(home_id), enabled=True))
        if family:
            subscription = await get_home_subscription(db, uuid.UUID(home_id))
            assert subscription is not None
            subscription.plan = SubscriptionPlan.family
        await db.commit()


async def _create_home_with_calendar(
    client: AsyncClient, name: str, *, family: bool = True
) -> tuple[str, str]:
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert group.status_code == 201, group.text
    home_id = group.json()["id"]
    await _enable_home(home_id, family=family)
    calendars = await client.get(f"/api/v1/homes/{home_id}/calendars")
    assert calendars.status_code == 200, calendars.text
    calendar_id = calendars.json()["items"][0]["id"]
    return home_id, calendar_id


async def _share_token(share_id: str) -> str:
    return derived_token(
        uuid.UUID(share_id), "calendar_share", get_settings().secret_key.get_secret_value()
    )


@pytest.mark.asyncio
async def test_home_admin_can_share_directly_and_recipient_must_accept(client: AsyncClient) -> None:
    owner_email = unique_email("owner")
    recipient_email = unique_email("grandma")
    await create_verified_user(client, owner_email, "Home Owner")
    home_id, calendar_id = await _create_home_with_calendar(client, "Hales Home")

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/calendar-shares",
        json={"calendar_id": calendar_id, "recipient_email": recipient_email, "permission": "view"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "pending_recipient"
    share_id = body["id"]

    # No access exists yet — the recipient hasn't accepted.
    recipient_client_probe = await unsafe(
        client,
        "GET",
        f"/api/v1/calendar-shares/{share_id}/events",
        params={
            "start_at": datetime.now(UTC).isoformat(),
            "end_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert recipient_client_probe.status_code in (401, 403, 404)

    # A separate client for the recipient, signing in with their own session.
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as recipient_client:
        await create_verified_user(recipient_client, recipient_email, "Grandma")
        token = await _share_token(share_id)

        preview = await recipient_client.get(
            "/api/v1/calendar-shares/preview", params={"token": token}
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["calendar_name"]

        accept = await unsafe(
            recipient_client,
            "POST",
            "/api/v1/calendar-shares/accept",
            json={"token": token, "notification_preference": "all", "include_in_briefing": True},
        )
        assert accept.status_code == 200, accept.text

        mine = await recipient_client.get("/api/v1/calendar-shares/mine")
        assert mine.status_code == 200
        assert any(item["id"] == share_id for item in mine.json()["items"])

        events = await recipient_client.get(
            f"/api/v1/calendar-shares/{share_id}/events",
            params={
                "start_at": datetime.now(UTC).isoformat(),
                "end_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
        )
        assert events.status_code == 200


@pytest.mark.asyncio
async def test_upcoming_shared_events_visible_once_accepted_and_hidden_before(
    client: AsyncClient,
) -> None:
    """Home -> "Coming up" must include a future event from a calendar
    shared into the viewer's Home once they've accepted, and must not be
    reachable at all — same as every other calendar-shares endpoint — before
    acceptance or after decline/revoke."""
    owner_email = unique_email("owner")
    recipient_email = unique_email("recipient")
    await create_verified_user(client, owner_email, "Home Owner")
    home_id, calendar_id = await _create_home_with_calendar(client, "Shared Coming Up Home")

    created_share = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/calendar-shares",
        json={"calendar_id": calendar_id, "recipient_email": recipient_email, "permission": "view"},
    )
    assert created_share.status_code == 201, created_share.text
    share_id = created_share.json()["id"]

    future_start = datetime.now(UTC) + timedelta(days=10)
    created_event = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Grandkids visit",
            "start_at": future_start.isoformat(),
            "end_at": (future_start + timedelta(hours=2)).isoformat(),
            "timezone": "UTC",
            "is_all_day": False,
            "member_ids": [],
            "recurrence": "none",
            "recurrence_interval": 1,
        },
    )
    assert created_event.status_code == 201, created_event.text

    after = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as recipient_client:
        await create_verified_user(recipient_client, recipient_email, "Recipient")

        # Not yet accepted — no access, matching the other share-scoped
        # endpoints (see test_home_admin_can_share_directly_and_recipient_must_accept).
        before_accept = await unsafe(
            recipient_client,
            "GET",
            f"/api/v1/calendar-shares/{share_id}/events/upcoming",
            params={"after": after},
        )
        assert before_accept.status_code in (401, 403, 404)

        token = await _share_token(share_id)
        accept = await unsafe(
            recipient_client,
            "POST",
            "/api/v1/calendar-shares/accept",
            json={"token": token, "notification_preference": "all", "include_in_briefing": True},
        )
        assert accept.status_code == 200, accept.text

        after_accept = await recipient_client.get(
            f"/api/v1/calendar-shares/{share_id}/events/upcoming", params={"after": after}
        )
        assert after_accept.status_code == 200
        titles = [item["title"] for item in after_accept.json()["items"]]
        assert titles == ["Grandkids visit"]

        leave = await unsafe(
            recipient_client, "POST", f"/api/v1/calendar-shares/{share_id}/leave"
        )
        assert leave.status_code == 200, leave.text

        after_leave = await unsafe(
            recipient_client,
            "GET",
            f"/api/v1/calendar-shares/{share_id}/events/upcoming",
            params={"after": after},
        )
        assert after_leave.status_code == 404


@pytest.mark.asyncio
async def test_member_requested_share_needs_admin_approval(client: AsyncClient) -> None:
    admin_email = unique_email("admin")
    partner_email = unique_email("partner")
    recipient_email = unique_email("friend")
    await create_verified_user(client, admin_email, "Admin")
    home_id, calendar_id = await _create_home_with_calendar(client, "Smith Home")

    invite = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={"group_id": home_id, "email": partner_email, "relationship": "partner"},
    )
    assert invite.status_code == 201, invite.text
    invitation_token = derived_token(
        uuid.UUID(invite.json()["id"]), "invitation", get_settings().secret_key.get_secret_value()
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as partner_client:
        await create_verified_user(partner_client, partner_email, "Partner")
        accepted = await unsafe(
            partner_client, "POST", "/api/v1/invitations/accept", json={"token": invitation_token}
        )
        assert accepted.status_code == 200, accepted.text

        requested = await unsafe(
            partner_client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares",
            json={
                "calendar_id": calendar_id,
                "recipient_email": recipient_email,
                "permission": "view",
            },
        )
        assert requested.status_code == 201, requested.text
        share = requested.json()
        assert share["status"] == "pending_admin_approval"
        share_id = share["id"]

    # No invitation email/token exists yet (still pending admin approval) —
    # a decode against a share in this state must fail even with a
    # correctly-derived token (it's the *status* gate, not just the token).
    token = await _share_token(share_id)
    premature_preview = await client.get("/api/v1/calendar-shares/preview", params={"token": token})
    assert premature_preview.status_code == 400

    approved = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/calendar-shares/{share_id}/approve"
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "pending_recipient"

    now_preview = await client.get("/api/v1/calendar-shares/preview", params={"token": token})
    assert now_preview.status_code == 200


@pytest.mark.asyncio
async def test_view_only_recipient_cannot_write_and_manage_recipient_can(
    client: AsyncClient,
) -> None:
    owner_email = unique_email("owner")
    view_email = unique_email("viewonly")
    manage_email = unique_email("manager")
    await create_verified_user(client, owner_email, "Owner")
    home_id, calendar_id = await _create_home_with_calendar(client, "Family Home")

    view_share = (
        await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares",
            json={"calendar_id": calendar_id, "recipient_email": view_email, "permission": "view"},
        )
    ).json()
    manage_share = (
        await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares",
            json={
                "calendar_id": calendar_id,
                "recipient_email": manage_email,
                "permission": "manage",
            },
        )
    ).json()

    async def _accept_as(email: str, name: str, share_id: str) -> AsyncClient:
        recipient_client = AsyncClient(
            transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
        )
        await recipient_client.__aenter__()
        await create_verified_user(recipient_client, email, name)
        token = await _share_token(share_id)
        accept = await unsafe(
            recipient_client,
            "POST",
            "/api/v1/calendar-shares/accept",
            json={"token": token, "notification_preference": "all", "include_in_briefing": True},
        )
        assert accept.status_code == 200, accept.text
        return recipient_client

    view_client = await _accept_as(view_email, "Viewer", view_share["id"])
    manage_client = await _accept_as(manage_email, "Manager", manage_share["id"])
    try:
        event_body = {
            "title": "Sports day",
            "start_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "end_at": (datetime.now(UTC) + timedelta(days=1, hours=1)).isoformat(),
            "timezone": "Europe/London",
            "is_all_day": False,
        }
        denied = await unsafe(
            view_client,
            "POST",
            f"/api/v1/calendar-shares/{view_share['id']}/events",
            json=event_body,
        )
        assert denied.status_code == 403

        created = await unsafe(
            manage_client,
            "POST",
            f"/api/v1/calendar-shares/{manage_share['id']}/events",
            json=event_body,
        )
        assert created.status_code == 201, created.text
        event_id = created.json()["event_id"]

        # The view-only recipient can still see it (calendar-wide view).
        listed = await view_client.get(
            f"/api/v1/calendar-shares/{view_share['id']}/events",
            params={
                "start_at": datetime.now(UTC).isoformat(),
                "end_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
            },
        )
        assert listed.status_code == 200
        assert any(item["event_id"] == event_id for item in listed.json()["items"])

        # Neither external recipient can reach the Home's own member-scoped
        # calendar API at all (no Membership row for this Home).
        home_scoped = await unsafe(view_client, "GET", f"/api/v1/homes/{home_id}/calendars")
        assert home_scoped.status_code == 404
    finally:
        await view_client.__aexit__(None, None, None)
        await manage_client.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_declined_and_revoked_shares_grant_no_access(client: AsyncClient) -> None:
    owner_email = unique_email("owner")
    recipient_email = unique_email("declines")
    await create_verified_user(client, owner_email, "Owner")
    home_id, calendar_id = await _create_home_with_calendar(client, "Quiet Home")

    share = (
        await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares",
            json={
                "calendar_id": calendar_id,
                "recipient_email": recipient_email,
                "permission": "view",
            },
        )
    ).json()
    token = await _share_token(share["id"])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as recipient_client:
        await create_verified_user(recipient_client, recipient_email, "Declines")
        declined = await unsafe(
            recipient_client, "POST", "/api/v1/calendar-shares/decline", json={"token": token}
        )
        assert declined.status_code == 200

        events = await unsafe(
            recipient_client,
            "GET",
            f"/api/v1/calendar-shares/{share['id']}/events",
            params={
                "start_at": datetime.now(UTC).isoformat(),
                "end_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
        )
        assert events.status_code == 404

    # Revocation of an accepted share.
    recipient_email_2 = unique_email("revoked")
    share2 = (
        await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares",
            json={
                "calendar_id": calendar_id,
                "recipient_email": recipient_email_2,
                "permission": "view",
            },
        )
    ).json()
    token2 = await _share_token(share2["id"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as recipient_client2:
        await create_verified_user(recipient_client2, recipient_email_2, "Revoked Later")
        accepted = await unsafe(
            recipient_client2,
            "POST",
            "/api/v1/calendar-shares/accept",
            json={"token": token2, "notification_preference": "all", "include_in_briefing": True},
        )
        assert accepted.status_code == 200

        revoke = await unsafe(
            client, "POST", f"/api/v1/homes/{home_id}/calendar-shares/{share2['id']}/revoke"
        )
        assert revoke.status_code == 200, revoke.text

        events = await unsafe(
            recipient_client2,
            "GET",
            f"/api/v1/calendar-shares/{share2['id']}/events",
            params={
                "start_at": datetime.now(UTC).isoformat(),
                "end_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
        )
        assert events.status_code == 404


@pytest.mark.asyncio
async def test_free_recipient_can_accept_without_upgrading(client: AsyncClient) -> None:
    owner_email = unique_email("owner")
    recipient_email = unique_email("free")
    await create_verified_user(client, owner_email, "Owner")
    home_id, calendar_id = await _create_home_with_calendar(client, "Generous Home", family=True)

    share = (
        await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares",
            json={
                "calendar_id": calendar_id,
                "recipient_email": recipient_email,
                "permission": "view",
            },
        )
    ).json()
    token = await _share_token(share["id"])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as recipient_client:
        await create_verified_user(recipient_client, recipient_email, "Free Recipient")
        # Their own Home (auto-created or not) is never touched/upgraded —
        # confirm no Family entitlement leaks onto the recipient's side by
        # checking accept succeeds with zero entitlement checks in the path.
        accept = await unsafe(
            recipient_client,
            "POST",
            "/api/v1/calendar-shares/accept",
            json={"token": token, "notification_preference": "all", "include_in_briefing": True},
        )
        assert accept.status_code == 200, accept.text


@pytest.mark.asyncio
async def test_free_home_cannot_initiate_share(client: AsyncClient) -> None:
    owner_email = unique_email("free-owner")
    recipient_email = unique_email("recipient")
    await create_verified_user(client, owner_email, "Free Owner")
    home_id, calendar_id = await _create_home_with_calendar(client, "Free Home", family=False)

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/calendar-shares",
        json={"calendar_id": calendar_id, "recipient_email": recipient_email, "permission": "view"},
    )
    assert created.status_code == 403


@pytest.mark.asyncio
async def test_external_recipient_cannot_reshare_or_reach_other_calendars(
    client: AsyncClient,
) -> None:
    owner_email = unique_email("owner")
    recipient_email = unique_email("noreshare")
    other_email = unique_email("outsider")
    await create_verified_user(client, owner_email, "Owner")
    home_id, calendar_id = await _create_home_with_calendar(client, "Locked Home")

    share = (
        await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares",
            json={
                "calendar_id": calendar_id,
                "recipient_email": recipient_email,
                "permission": "manage",
            },
        )
    ).json()
    token = await _share_token(share["id"])

    # A second, unrelated Home + calendar the recipient must never reach.
    other_home_id, other_calendar_id = await _create_home_with_calendar(client, "Other Home")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as recipient_client:
        await create_verified_user(recipient_client, recipient_email, "No Reshare")
        await unsafe(
            recipient_client,
            "POST",
            "/api/v1/calendar-shares/accept",
            json={"token": token, "notification_preference": "all", "include_in_briefing": True},
        )

        # Cannot re-share the calendar onward (no Membership => 404 on the
        # Home-scoped create-share endpoint).
        reshare = await unsafe(
            recipient_client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares",
            json={"calendar_id": calendar_id, "recipient_email": other_email, "permission": "view"},
        )
        assert reshare.status_code == 404

        # Cannot reach an unrelated Home's calendar-share administration.
        unrelated = await unsafe(
            recipient_client,
            "GET",
            f"/api/v1/homes/{other_home_id}/calendar-shares/calendar/{other_calendar_id}",
        )
        assert unrelated.status_code == 404


@pytest.mark.asyncio
async def test_new_extended_family_friend_invitations_are_rejected(client: AsyncClient) -> None:
    owner_email = unique_email("legacyowner")
    invitee_email = unique_email("legacyinvitee")
    await create_verified_user(client, owner_email, "Legacy Owner")
    home_id, _calendar_id = await _create_home_with_calendar(client, "Legacy Home")

    for relationship in ("extended_family", "friend"):
        response = await unsafe(
            client,
            "POST",
            "/api/v1/invitations",
            json={"group_id": home_id, "email": invitee_email, "relationship": relationship},
        )
        assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_existing_extended_family_membership_still_resolves_capabilities(
    client: AsyncClient,
) -> None:
    """Regression: rows created before this feature (or seeded directly, as
    a stand-in for "existing installs") must keep working unchanged — this
    feature only blocks *new* creation, never touches existing data."""
    owner_email = unique_email("grandfathered-owner")
    await create_verified_user(client, owner_email, "Grandfathered Owner")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Old Home"})
    home_id = uuid.UUID(group.json()["id"])

    async with SessionFactory() as db:
        owner = await db.scalar(select(User).where(User.email == owner_email))
        assert owner is not None
        legacy_user = User(
            email=unique_email("legacy-friend"),
            display_name="Legacy Friend",
            is_active=True,
        )
        db.add(legacy_user)
        await db.flush()
        db.add(
            Membership(
                group_id=home_id,
                user_id=legacy_user.id,
                role=Role.guest,
                relationship=HouseholdRelationship.friend,
                permission_profile=PermissionProfile.explicit_sharing,
                shared_resources=["calendar"],
            )
        )
        await db.commit()

    async with SessionFactory() as db:
        membership = await db.scalar(
            select(Membership).where(
                Membership.group_id == home_id,
                Membership.relationship == HouseholdRelationship.friend,
            )
        )
        assert membership is not None
        capabilities = await capabilities_for(db, membership)
        assert Capability.calendar_view in capabilities
        assert Capability.calendar_view_all in capabilities


async def _accept_as(email: str, name: str, share_id: str) -> AsyncClient:
    recipient_client = AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    )
    await recipient_client.__aenter__()
    await create_verified_user(recipient_client, email, name)
    token = await _share_token(share_id)
    accept = await unsafe(
        recipient_client,
        "POST",
        "/api/v1/calendar-shares/accept",
        json={"token": token, "notification_preference": "all", "include_in_briefing": True},
    )
    assert accept.status_code == 200, accept.text
    return recipient_client


async def _notifications_for(recipient_id: uuid.UUID) -> list[Notification]:
    async with SessionFactory() as db:
        rows = (
            await db.scalars(
                select(Notification).where(Notification.recipient_user_id == recipient_id)
            )
        ).all()
        return list(rows)


@pytest.mark.asyncio
async def test_permission_downgrade_blocks_write_immediately_no_reinvite_needed_on_upgrade(
    client: AsyncClient,
) -> None:
    owner_email = unique_email("owner")
    recipient_email = unique_email("flexible")
    await create_verified_user(client, owner_email, "Owner")
    home_id, calendar_id = await _create_home_with_calendar(client, "Flexible Home")

    share = (
        await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares",
            json={
                "calendar_id": calendar_id,
                "recipient_email": recipient_email,
                "permission": "manage",
            },
        )
    ).json()
    recipient_client = await _accept_as(recipient_email, "Flexible", share["id"])
    try:
        event_body = {
            "title": "Practice",
            "start_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "end_at": (datetime.now(UTC) + timedelta(days=1, hours=1)).isoformat(),
            "timezone": "Europe/London",
            "is_all_day": False,
        }
        created = await unsafe(
            recipient_client,
            "POST",
            f"/api/v1/calendar-shares/{share['id']}/events",
            json=event_body,
        )
        assert created.status_code == 201, created.text

        downgrade = await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares/{share['id']}/permission",
            json={"permission": "view"},
        )
        assert downgrade.status_code == 200, downgrade.text

        # Same session, no new invitation — the downgrade must be visible on
        # the very next request.
        denied = await unsafe(
            recipient_client,
            "POST",
            f"/api/v1/calendar-shares/{share['id']}/events",
            json=event_body,
        )
        assert denied.status_code == 403

        upgrade = await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares/{share['id']}/permission",
            json={"permission": "manage"},
        )
        assert upgrade.status_code == 200, upgrade.text

        allowed_again = await unsafe(
            recipient_client,
            "POST",
            f"/api/v1/calendar-shares/{share['id']}/events",
            json=event_body,
        )
        assert allowed_again.status_code == 201, allowed_again.text
    finally:
        await recipient_client.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_permission_change_never_alters_notification_or_briefing_preferences(
    client: AsyncClient,
) -> None:
    owner_email = unique_email("owner")
    recipient_email = unique_email("prefs")
    await create_verified_user(client, owner_email, "Owner")
    home_id, calendar_id = await _create_home_with_calendar(client, "Prefs Home")

    share = (
        await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares",
            json={
                "calendar_id": calendar_id,
                "recipient_email": recipient_email,
                "permission": "view",
            },
        )
    ).json()
    recipient_client = await _accept_as(recipient_email, "Prefs", share["id"])
    try:
        prefs = await unsafe(
            recipient_client,
            "PATCH",
            f"/api/v1/calendar-shares/{share['id']}",
            json={"notification_preference": "important", "include_in_briefing": False},
        )
        assert prefs.status_code == 200, prefs.text

        changed = await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares/{share['id']}/permission",
            json={"permission": "manage"},
        )
        assert changed.status_code == 200
        assert changed.json()["notification_preference"] == "important"
        assert changed.json()["include_in_briefing"] is False
    finally:
        await recipient_client.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_event_notifications_reach_active_share_recipients_and_respect_preference(
    client: AsyncClient,
) -> None:
    owner_email = unique_email("owner")
    all_email = unique_email("wantsall")
    off_email = unique_email("wantsoff")
    await create_verified_user(client, owner_email, "Owner")
    home_id, calendar_id = await _create_home_with_calendar(client, "Notify Home")

    share_all = (
        await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares",
            json={"calendar_id": calendar_id, "recipient_email": all_email, "permission": "view"},
        )
    ).json()
    share_off = (
        await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares",
            json={"calendar_id": calendar_id, "recipient_email": off_email, "permission": "view"},
        )
    ).json()

    async def _accept_with_pref(
        email: str, name: str, share_id: str, preference: str
    ) -> tuple[AsyncClient, str]:
        recipient_client = AsyncClient(
            transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
        )
        await recipient_client.__aenter__()
        await create_verified_user(recipient_client, email, name)
        me = await recipient_client.get("/api/v1/users/me")
        recipient_id = me.json()["id"]
        token = await _share_token(share_id)
        accept = await unsafe(
            recipient_client,
            "POST",
            "/api/v1/calendar-shares/accept",
            json={
                "token": token,
                "notification_preference": preference,
                "include_in_briefing": True,
            },
        )
        assert accept.status_code == 200, accept.text
        return recipient_client, recipient_id

    all_client, all_id = await _accept_with_pref(all_email, "Wants All", share_all["id"], "all")
    off_client, off_id = await _accept_with_pref(off_email, "Wants Off", share_off["id"], "off")
    try:
        created = await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/events",
            json={
                "title": "Sports day",
                "start_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                "end_at": (datetime.now(UTC) + timedelta(days=1, hours=1)).isoformat(),
                "timezone": "Europe/London",
                "is_all_day": False,
            },
        )
        assert created.status_code == 201, created.text

        all_notifications = await _notifications_for(uuid.UUID(all_id))
        assert any(n.notification_type == "event_invitation" for n in all_notifications)
        off_notifications = await _notifications_for(uuid.UUID(off_id))
        assert not any(n.notification_type == "event_invitation" for n in off_notifications)
    finally:
        await all_client.__aexit__(None, None, None)
        await off_client.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_revoked_share_stops_future_notifications(client: AsyncClient) -> None:
    owner_email = unique_email("owner")
    recipient_email = unique_email("soon-revoked")
    await create_verified_user(client, owner_email, "Owner")
    home_id, calendar_id = await _create_home_with_calendar(client, "Stop Notify Home")

    share = (
        await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares",
            json={
                "calendar_id": calendar_id,
                "recipient_email": recipient_email,
                "permission": "view",
            },
        )
    ).json()

    recipient_client = AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    )
    await recipient_client.__aenter__()
    try:
        await create_verified_user(recipient_client, recipient_email, "Soon Revoked")
        me = await recipient_client.get("/api/v1/users/me")
        recipient_id = uuid.UUID(me.json()["id"])
        token = await _share_token(share["id"])
        await unsafe(
            recipient_client,
            "POST",
            "/api/v1/calendar-shares/accept",
            json={"token": token, "notification_preference": "all", "include_in_briefing": True},
        )

        revoke = await unsafe(
            client, "POST", f"/api/v1/homes/{home_id}/calendar-shares/{share['id']}/revoke"
        )
        assert revoke.status_code == 200, revoke.text

        created = await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/events",
            json={
                "title": "After revoke",
                "start_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                "end_at": (datetime.now(UTC) + timedelta(days=1, hours=1)).isoformat(),
                "timezone": "Europe/London",
                "is_all_day": False,
            },
        )
        assert created.status_code == 201, created.text

        notifications = await _notifications_for(recipient_id)
        assert not any(n.notification_type == "event_invitation" for n in notifications)
    finally:
        await recipient_client.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_briefing_respects_include_in_briefing_and_revocation(client: AsyncClient) -> None:
    owner_email = unique_email("owner")
    included_email = unique_email("included")
    excluded_email = unique_email("excluded")
    await create_verified_user(client, owner_email, "Owner")
    home_id, calendar_id = await _create_home_with_calendar(client, "Briefing Home")

    share_in = (
        await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares",
            json={
                "calendar_id": calendar_id,
                "recipient_email": included_email,
                "permission": "view",
            },
        )
    ).json()
    share_out = (
        await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares",
            json={
                "calendar_id": calendar_id,
                "recipient_email": excluded_email,
                "permission": "view",
            },
        )
    ).json()

    async def _accept_with_briefing(
        email: str, name: str, share_id: str, include_in_briefing: bool
    ) -> tuple[AsyncClient, uuid.UUID]:
        recipient_client = AsyncClient(
            transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
        )
        await recipient_client.__aenter__()
        await create_verified_user(recipient_client, email, name)
        me = await recipient_client.get("/api/v1/users/me")
        recipient_id = uuid.UUID(me.json()["id"])
        token = await _share_token(share_id)
        accept = await unsafe(
            recipient_client,
            "POST",
            "/api/v1/calendar-shares/accept",
            json={
                "token": token,
                "notification_preference": "all",
                "include_in_briefing": include_in_briefing,
            },
        )
        assert accept.status_code == 200, accept.text
        return recipient_client, recipient_id

    included_client, included_id = await _accept_with_briefing(
        included_email, "Included", share_in["id"], True
    )
    excluded_client, excluded_id = await _accept_with_briefing(
        excluded_email, "Excluded", share_out["id"], False
    )
    try:
        today = datetime.now(UTC).date()
        event_body = {
            "title": "Briefing event",
            "start_at": datetime.now(UTC)
            .replace(hour=10, minute=0, second=0, microsecond=0)
            .isoformat(),
            "end_at": datetime.now(UTC)
            .replace(hour=11, minute=0, second=0, microsecond=0)
            .isoformat(),
            "timezone": "UTC",
            "is_all_day": False,
        }
        created = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/events", json=event_body)
        assert created.status_code == 201, created.text

        async with SessionFactory() as db:
            included_occurrences = await _events_for_user_today(db, included_id, today, UTC)
            excluded_occurrences = await _events_for_user_today(db, excluded_id, today, UTC)
        assert any(o.title == "Briefing event" for o in included_occurrences)
        assert not any(o.title == "Briefing event" for o in excluded_occurrences)

        # Revoke the included recipient's share — their next briefing must no
        # longer include it either.
        revoke = await unsafe(
            client, "POST", f"/api/v1/homes/{home_id}/calendar-shares/{share_in['id']}/revoke"
        )
        assert revoke.status_code == 200, revoke.text
        async with SessionFactory() as db:
            after_revoke = await _events_for_user_today(db, included_id, today, UTC)
        assert not any(o.title == "Briefing event" for o in after_revoke)
    finally:
        await included_client.__aexit__(None, None, None)
        await excluded_client.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_recipient_leaves_share_source_home_unaffected(client: AsyncClient) -> None:
    owner_email = unique_email("owner")
    recipient_email = unique_email("leaver")
    await create_verified_user(client, owner_email, "Owner")
    home_id, calendar_id = await _create_home_with_calendar(client, "Leave Home")

    share = (
        await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares",
            json={
                "calendar_id": calendar_id,
                "recipient_email": recipient_email,
                "permission": "view",
            },
        )
    ).json()
    recipient_client = await _accept_as(recipient_email, "Leaver", share["id"])
    try:
        leave = await unsafe(
            recipient_client, "POST", f"/api/v1/calendar-shares/{share['id']}/leave"
        )
        assert leave.status_code == 200, leave.text

        # Recipient loses access.
        events = await unsafe(
            recipient_client,
            "GET",
            f"/api/v1/calendar-shares/{share['id']}/events",
            params={
                "start_at": datetime.now(UTC).isoformat(),
                "end_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
        )
        assert events.status_code == 404

        # Source Home's own calendar/events remain completely unaffected.
        still_there = await client.get(f"/api/v1/homes/{home_id}/calendars")
        assert still_there.status_code == 200

        # Source-side sharing management correctly reflects "revoked" (the
        # recipient-initiated terminal state reuses the same status).
        listed = await client.get(f"/api/v1/homes/{home_id}/calendar-shares/calendar/{calendar_id}")
        assert listed.status_code == 200
        matching = next(item for item in listed.json()["items"] if item["id"] == share["id"])
        assert matching["status"] == "revoked"
    finally:
        await recipient_client.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# Category-scoped Home calendar sharing — a share can optionally filter to
# specific CalendarEventLabel categories instead of exposing the entire
# calendar. See CalendarShare.category_ids and
# notifications.visibility.event_matches_share.
# ---------------------------------------------------------------------------


async def _create_label(client: AsyncClient, home_id: str, name: str) -> str:
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/event-labels",
        json={"name": name, "color": "teal"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_event(
    client: AsyncClient, home_id: str, title: str, label_id: str | None = None
) -> str:
    body = {
        "title": title,
        "start_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "end_at": (datetime.now(UTC) + timedelta(days=1, hours=1)).isoformat(),
        "timezone": "Europe/London",
        "is_all_day": False,
        "label_id": label_id,
    }
    response = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/events", json=body)
    assert response.status_code == 201, response.text
    return response.json()["event_id"]


@pytest.mark.asyncio
async def test_category_scoped_share_exposes_only_selected_categories(client: AsyncClient) -> None:
    owner_email = unique_email("owner")
    recipient_email = unique_email("category-scoped")
    await create_verified_user(client, owner_email, "Owner")
    home_id, calendar_id = await _create_home_with_calendar(client, "Category Home")

    family_label = await _create_label(client, home_id, "Family Events")
    private_label = await _create_label(client, home_id, "Private Adult Stuff")

    family_event_id = await _create_event(client, home_id, "Family picnic", family_label)
    private_event_id = await _create_event(client, home_id, "Adult only", private_label)
    uncategorised_event_id = await _create_event(client, home_id, "No category")

    share = (
        await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares",
            json={
                "calendar_id": calendar_id,
                "recipient_email": recipient_email,
                "permission": "view",
                "category_ids": [family_label],
            },
        )
    ).json()
    assert share["category_ids"] == [family_label]

    recipient_client = await _accept_as(recipient_email, "Category Scoped", share["id"])
    try:
        events = await recipient_client.get(
            f"/api/v1/calendar-shares/{share['id']}/events",
            params={
                "start_at": datetime.now(UTC).isoformat(),
                "end_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
            },
        )
        assert events.status_code == 200
        event_ids = {item["event_id"] for item in events.json()["items"]}
        assert family_event_id in event_ids
        assert private_event_id not in event_ids
        assert uncategorised_event_id not in event_ids

        # Direct reads of the excluded categories' events are just as
        # inaccessible as if they didn't exist — the boundary is enforced
        # server-side, not by the list endpoint quietly omitting them.
        from mykhaya.models import CalendarEvent
        from mykhaya.notifications.visibility import can_view_event

        async with SessionFactory() as db:
            me = await recipient_client.get("/api/v1/users/me")
            recipient_id = uuid.UUID(me.json()["id"])
            private_event = await db.get(CalendarEvent, uuid.UUID(private_event_id))
            assert private_event is not None
            assert await can_view_event(db, private_event, recipient_id) is False
    finally:
        await recipient_client.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_category_scoped_share_can_be_changed_without_reinvite(client: AsyncClient) -> None:
    owner_email = unique_email("owner")
    recipient_email = unique_email("switching")
    await create_verified_user(client, owner_email, "Owner")
    home_id, calendar_id = await _create_home_with_calendar(client, "Switching Home")

    family_label = await _create_label(client, home_id, "Family Events")
    activity_label = await _create_label(client, home_id, "Football Club")
    activity_event_id = await _create_event(client, home_id, "Football", activity_label)

    share = (
        await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares",
            json={
                "calendar_id": calendar_id,
                "recipient_email": recipient_email,
                "permission": "view",
                "category_ids": [family_label],
            },
        )
    ).json()
    recipient_client = await _accept_as(recipient_email, "Switching", share["id"])
    try:
        before = await recipient_client.get(
            f"/api/v1/calendar-shares/{share['id']}/events",
            params={
                "start_at": datetime.now(UTC).isoformat(),
                "end_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
            },
        )
        assert activity_event_id not in {item["event_id"] for item in before.json()["items"]}

        changed = await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/calendar-shares/{share['id']}/categories",
            json={"category_ids": [family_label, activity_label]},
        )
        assert changed.status_code == 200, changed.text

        after = await recipient_client.get(
            f"/api/v1/calendar-shares/{share['id']}/events",
            params={
                "start_at": datetime.now(UTC).isoformat(),
                "end_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
            },
        )
        assert activity_event_id in {item["event_id"] for item in after.json()["items"]}
    finally:
        await recipient_client.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_personal_calendar_cannot_be_shared_with_category_filter(client: AsyncClient) -> None:
    owner_email = unique_email("owner")
    recipient_email = unique_email("nopersonalcategories")
    await create_verified_user(client, owner_email, "Owner")
    home_id, _calendar_id = await _create_home_with_calendar(client, "Personal Category Home")

    calendars = await client.get(f"/api/v1/homes/{home_id}/calendars")
    personal_calendar_id = calendars.json()["personal_calendar"]["id"]

    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/calendar-shares",
        json={
            "calendar_id": personal_calendar_id,
            "recipient_email": recipient_email,
            "permission": "view",
            "category_ids": [],
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_home_admin_cannot_share_another_members_personal_calendar(
    client: AsyncClient,
) -> None:
    """The Personal Calendar privacy boundary is absolute everywhere else in
    the app (a Home Admin's calendar_view_all never reaches into it) —
    sharing authority must respect that same boundary: only the calendar's
    own owner may ever request/send/approve/revoke a share of it, Home
    Admin status notwithstanding. See
    routers.calendar_sharing._has_authority_over_calendar."""
    admin_email = unique_email("admin")
    partner_email = unique_email("partner")
    outsider_email = unique_email("outsider")
    await create_verified_user(client, admin_email, "Admin")
    home_id, _calendar_id = await _create_home_with_calendar(client, "Boundary Home")

    invite = await unsafe(
        client,
        "POST",
        "/api/v1/invitations",
        json={"group_id": home_id, "email": partner_email, "relationship": "partner"},
    )
    assert invite.status_code == 201, invite.text
    invitation_token = derived_token(
        uuid.UUID(invite.json()["id"]), "invitation", get_settings().secret_key.get_secret_value()
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as partner_client:
        await create_verified_user(partner_client, partner_email, "Partner")
        accepted = await unsafe(
            partner_client, "POST", "/api/v1/invitations/accept", json={"token": invitation_token}
        )
        assert accepted.status_code == 200, accepted.text

        calendars = await partner_client.get(f"/api/v1/homes/{home_id}/calendars")
        partner_personal_calendar_id = calendars.json()["personal_calendar"]["id"]

    # The Home Admin — not the Partner themselves — tries to share the
    # Partner's Personal Calendar. Must 404 (behaves as if it doesn't
    # exist), the same as every other cross-member Personal Calendar
    # access attempt in this app.
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/calendar-shares",
        json={
            "calendar_id": partner_personal_calendar_id,
            "recipient_email": outsider_email,
            "permission": "view",
        },
    )
    assert response.status_code == 404
