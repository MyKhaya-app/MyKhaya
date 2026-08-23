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
    PermissionProfile,
    Role,
    SubscriptionPlan,
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
        for key in (FeatureKey.calendar, FeatureKey.external_sharing):
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
