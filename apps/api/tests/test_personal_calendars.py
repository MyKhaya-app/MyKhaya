"""Personal Calendar: a genuinely private, per-user calendar within a Home.

Reuses test_calendar's client/create_verified_user/unsafe fixtures rather than
re-declaring the whole harness. See docs/security/threat-model.md on
cross-member data leakage — this file is the regression suite for exactly
that risk applied to Personal Calendars.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_calendar import (  # noqa: F401
    ORIGIN,
    PASSWORD,
    client,
    create_verified_user,
    unsafe,
)

from mykhaya.calendar_provisioning import ensure_personal_calendar
from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import get_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    FeatureKey,
    FeatureOverride,
    HomeCalendar,
    HouseholdRelationship,
    Membership,
    Notification,
    PermissionProfile,
    Role,
    SubscriptionPlan,
    User,
)
from mykhaya.notifications.reminders import deliver_event_reminder


def unique_email(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%H%M%S%f')}@example.com"


async def _home_with_calendar(
    client: AsyncClient, name: str, plan: SubscriptionPlan = SubscriptionPlan.free
) -> str:
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert group.status_code == 201
    home_id = group.json()["id"]
    async with SessionFactory() as db:
        db.add(
            FeatureOverride(
                feature_key=FeatureKey.calendar, group_id=uuid.UUID(home_id), enabled=True
            )
        )
        if plan != SubscriptionPlan.free:
            subscription = await get_home_subscription(db, uuid.UUID(home_id))
            assert subscription is not None
            subscription.plan = plan
        await db.commit()
    return home_id


async def _user_id(email: str) -> uuid.UUID:
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        return user.id


async def _join_home_as_partner(home_id: str, email: str) -> uuid.UUID:
    """Registers a second adult and joins them to home_id as a
    standard_partner — a profile that (like home_admin) is granted
    calendar_view_all automatically, which is exactly the bypass Personal
    Calendar privacy must hold up against. Bypasses the invitation HTTP flow
    (orthogonal to what's under test) but does NOT provision a Personal
    Calendar — that's the eager-provisioning path this file tests
    separately; most tests trigger it via GET /calendars, same as the real
    frontend does on load."""
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


async def _login_client(email: str) -> AsyncClient:
    session = AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    )
    login = await session.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    return session


async def _personal_calendar_id(client: AsyncClient, home_id: str) -> str:
    listing = await client.get(f"/api/v1/homes/{home_id}/calendars")
    assert listing.status_code == 200
    body = listing.json()
    assert body["personal_calendar"] is not None
    return body["personal_calendar"]["id"]


def _event_body(**overrides: object) -> dict:
    start_at = datetime(2026, 6, 1, 18, 0, tzinfo=UTC)
    body: dict = {
        "title": "Doctor's appointment",
        "start_at": start_at.isoformat(),
        "end_at": (start_at + timedelta(hours=1)).isoformat(),
        "timezone": "Europe/London",
        "member_ids": [],
    }
    body.update(overrides)
    return body


# --------------------------------------------------------------------------
# Personal calendar creation / idempotency
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_home_admin_gets_exactly_one_personal_calendar(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("owner"), "Owner")
    home_id = await _home_with_calendar(client, "Solo Home")
    async with SessionFactory() as db:
        rows = (
            await db.scalars(
                select(HomeCalendar).where(
                    HomeCalendar.group_id == uuid.UUID(home_id),
                    HomeCalendar.owner_user_id.isnot(None),
                )
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].name == "Personal calendar"


@pytest.mark.asyncio
async def test_list_calendars_lazily_provisions_and_is_idempotent(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("lazy"), "Lazy Owner")
    home_id = await _home_with_calendar(client, "Lazy Home")

    first = await _personal_calendar_id(client, home_id)
    second = await _personal_calendar_id(client, home_id)
    assert first == second

    async with SessionFactory() as db:
        rows = (
            await db.scalars(
                select(HomeCalendar).where(
                    HomeCalendar.group_id == uuid.UUID(home_id),
                    HomeCalendar.owner_user_id.isnot(None),
                )
            )
        ).all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_ensure_personal_calendar_helper_is_idempotent_under_repeated_calls(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("repeat"), "Repeat Owner")
    home_id = await _home_with_calendar(client, "Repeat Home")
    user_id = await _user_id((await client.get("/api/v1/users/me")).json()["email"])

    async with SessionFactory() as db:
        first = await ensure_personal_calendar(db, uuid.UUID(home_id), user_id)
        second = await ensure_personal_calendar(db, uuid.UUID(home_id), user_id)
        third = await ensure_personal_calendar(db, uuid.UUID(home_id), user_id)
        await db.commit()
        assert first.id == second.id == third.id

        rows = (
            await db.scalars(
                select(HomeCalendar).where(
                    HomeCalendar.group_id == uuid.UUID(home_id),
                    HomeCalendar.owner_user_id == user_id,
                )
            )
        ).all()
        assert len(rows) == 1


# --------------------------------------------------------------------------
# Privacy: the core requirement
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_other_member_cannot_see_your_personal_event_in_list_events(
    client: AsyncClient,
) -> None:
    anthony_email = unique_email("anthony")
    await create_verified_user(client, anthony_email, "Anthony")
    home_id = await _home_with_calendar(client, "Hales Home", plan=SubscriptionPlan.family)
    anthony_personal = await _personal_calendar_id(client, home_id)

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body(calendar_id=anthony_personal),
    )
    assert created.status_code == 201
    event_id = created.json()["event_id"]

    megan_email = unique_email("megan")
    await _join_home_as_partner(home_id, megan_email)
    megan_client = await _login_client(megan_email)
    try:
        # Megan is a standard_partner — calendar_view_all — yet must not see
        # Anthony's personal event via the list endpoint.
        listed = await megan_client.get(
            f"/api/v1/homes/{home_id}/events",
            params={
                "start_at": "2026-05-01T00:00:00Z",
                "end_at": "2026-07-01T00:00:00Z",
            },
        )
        assert listed.status_code == 200
        assert event_id not in {item["event_id"] for item in listed.json()["items"]}

        # Nor via direct event_detail lookup by (guessed/enumerated) id.
        detail = await megan_client.get(f"/api/v1/homes/{home_id}/events/{event_id}")
        assert detail.status_code == 404
    finally:
        await megan_client.aclose()


@pytest.mark.asyncio
async def test_upcoming_events_endpoint_hides_another_members_personal_event(
    client: AsyncClient,
) -> None:
    """Home -> "Coming up" (GET /events/upcoming) must respect the exact
    same Personal Calendar privacy boundary as list_events — including
    against a standard_partner who otherwise holds calendar_view_all."""
    anthony_email = unique_email("anthony")
    await create_verified_user(client, anthony_email, "Anthony")
    home_id = await _home_with_calendar(
        client, "Upcoming Privacy Home", plan=SubscriptionPlan.family
    )
    anthony_personal = await _personal_calendar_id(client, home_id)

    future_start = datetime.now(UTC) + timedelta(days=7)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body(
            calendar_id=anthony_personal,
            start_at=future_start.isoformat(),
            end_at=(future_start + timedelta(hours=1)).isoformat(),
        ),
    )
    assert created.status_code == 201
    event_id = created.json()["event_id"]

    after = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

    # Anthony sees his own personal event in "Coming up".
    own = await client.get(
        f"/api/v1/homes/{home_id}/events/upcoming", params={"after": after, "limit": 5}
    )
    assert own.status_code == 200
    assert event_id in {item["event_id"] for item in own.json()["items"]}

    megan_email = unique_email("megan")
    await _join_home_as_partner(home_id, megan_email)
    megan_client = await _login_client(megan_email)
    try:
        theirs = await megan_client.get(
            f"/api/v1/homes/{home_id}/events/upcoming", params={"after": after, "limit": 5}
        )
        assert theirs.status_code == 200
        assert event_id not in {item["event_id"] for item in theirs.json()["items"]}
    finally:
        await megan_client.aclose()


@pytest.mark.asyncio
async def test_owner_can_see_their_own_personal_event(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("owner2"), "Owner Two")
    home_id = await _home_with_calendar(client, "Owner Home")
    personal_id = await _personal_calendar_id(client, home_id)

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body(calendar_id=personal_id, title="My own thing"),
    )
    assert created.status_code == 201
    event_id = created.json()["event_id"]

    listed = await client.get(
        f"/api/v1/homes/{home_id}/events",
        params={"start_at": "2026-05-01T00:00:00Z", "end_at": "2026-07-01T00:00:00Z"},
    )
    assert event_id in {item["event_id"] for item in listed.json()["items"]}

    detail = await client.get(f"/api/v1/homes/{home_id}/events/{event_id}")
    assert detail.status_code == 200


@pytest.mark.asyncio
async def test_home_admin_cannot_see_a_partners_personal_event(client: AsyncClient) -> None:
    """The Home creator is home_admin — ALL_CAPABILITIES, including
    calendar_view_all. Confirms admin status specifically (not just
    "some calendar_view_all role") never bypasses another adult's privacy."""
    admin_email = unique_email("admin")
    await create_verified_user(client, admin_email, "Home Admin")
    home_id = await _home_with_calendar(client, "Admin Home", plan=SubscriptionPlan.family)

    megan_email = unique_email("megan2")
    megan_id = await _join_home_as_partner(home_id, megan_email)
    megan_client = await _login_client(megan_email)
    try:
        megan_personal = await _personal_calendar_id(megan_client, home_id)
        created = await unsafe(
            megan_client,
            "POST",
            f"/api/v1/homes/{home_id}/events",
            json=_event_body(calendar_id=megan_personal, title="Megan's secret"),
        )
        assert created.status_code == 201
        event_id = created.json()["event_id"]
    finally:
        await megan_client.aclose()

    listed = await client.get(
        f"/api/v1/homes/{home_id}/events",
        params={"start_at": "2026-05-01T00:00:00Z", "end_at": "2026-07-01T00:00:00Z"},
    )
    assert event_id not in {item["event_id"] for item in listed.json()["items"]}
    detail = await client.get(f"/api/v1/homes/{home_id}/events/{event_id}")
    assert detail.status_code == 404

    # Admin also cannot edit or delete it by guessing/enumerating the id.
    # EventUpdate has no calendar_id field (an event's calendar is immutable
    # after creation), so this override only ever touches title.
    update = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        json=_event_body(title="Overwritten", expected_updated_at="2000-01-01T00:00:00+00:00"),
    )
    assert update.status_code == 404
    delete = await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/events/{event_id}")
    assert delete.status_code == 404
    assert megan_id  # sanity: id was actually resolved above


@pytest.mark.asyncio
async def test_cannot_create_an_event_directly_on_another_members_personal_calendar(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("a"), "A")
    home_id = await _home_with_calendar(client, "Cross Home", plan=SubscriptionPlan.family)

    b_email = unique_email("b")
    await _join_home_as_partner(home_id, b_email)
    b_client = await _login_client(b_email)
    try:
        b_personal = await _personal_calendar_id(b_client, home_id)
    finally:
        await b_client.aclose()

    # Back as A: try to create an event directly on B's Personal Calendar id.
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body(calendar_id=b_personal),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_personal_calendar_event_cannot_be_assigned_to_other_members(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("solo"), "Solo")
    home_id = await _home_with_calendar(client, "Solo Share Home", plan=SubscriptionPlan.family)
    personal_id = await _personal_calendar_id(client, home_id)

    other_email = unique_email("other")
    other_id = await _join_home_as_partner(home_id, other_email)

    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body(calendar_id=personal_id, member_ids=[str(other_id)]),
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Never entitlement-gated
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_free_user_can_use_personal_calendar_despite_category_limit(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("free"), "Free User")
    home_id = await _home_with_calendar(client, "Free Home", plan=SubscriptionPlan.free)
    personal_id = await _personal_calendar_id(client, home_id)

    # Free's calendar.max_categories is 1 — already "used" by the primary
    # Home calendar (see _ensure_home_calendar) — the Personal Calendar must
    # still be fully usable.
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body(calendar_id=personal_id),
    )
    assert created.status_code == 201
    event_id = created.json()["event_id"]

    updated = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        json=_event_body(
            title="Updated",
            expected_updated_at=created.json()["updated_at"],
        ),
    )
    assert updated.status_code == 200


@pytest.mark.asyncio
async def test_personal_calendar_not_counted_against_calendar_max_categories(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("count"), "Count Owner")
    home_id = await _home_with_calendar(client, "Count Home", plan=SubscriptionPlan.free)
    await _personal_calendar_id(client, home_id)  # provisions it

    # Free's one shared-calendar allowance is still available for a genuine
    # *shared* second calendar attempt to correctly report "at the limit"
    # against the primary alone, not primary+personal.
    blocked = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/calendars", json={"name": "Second shared"}
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "plan_limit_reached"

    listing = await client.get(f"/api/v1/homes/{home_id}/calendars")
    body = listing.json()
    # Only the primary shared calendar in `items` — Personal Calendar is
    # surfaced solely via `personal_calendar`.
    assert len(body["items"]) == 1
    assert all(item["owner_user_id"] is None for item in body["items"])
    assert body["personal_calendar"]["owner_user_id"] is not None


@pytest.mark.asyncio
async def test_personal_calendar_cannot_be_deleted_via_the_calendar_endpoint(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("nodel"), "No Delete")
    home_id = await _home_with_calendar(client, "No Delete Home")
    personal_id = await _personal_calendar_id(client, home_id)

    response = await unsafe(
        client,
        "DELETE",
        f"/api/v1/homes/{home_id}/calendars/{personal_id}",
        json={"confirmed": True},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_personal_calendar_colour_cannot_be_changed_via_the_calendar_endpoint(
    client: AsyncClient,
) -> None:
    """The Home calendar colour endpoint (routers.calendar.update_calendar)
    is for shared household structure — a Personal Calendar is nobody's to
    administer but its own owner, and no UI exposes changing its colour, so
    the endpoint 404s the same way it already does for delete."""
    await create_verified_user(client, unique_email("nocolour"), "No Colour")
    home_id = await _home_with_calendar(client, "No Colour Home")
    personal_id = await _personal_calendar_id(client, home_id)

    response = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/calendars/{personal_id}",
        json={"color": "amber"},
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Regression: shared/Home calendar behaviour is unchanged
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shared_event_still_visible_to_partner_with_calendar_view_all(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("shareowner"), "Share Owner")
    home_id = await _home_with_calendar(client, "Share Home", plan=SubscriptionPlan.family)

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body(title="Family BBQ"),  # default (primary, shared) calendar
    )
    assert created.status_code == 201
    event_id = created.json()["event_id"]

    partner_email = unique_email("partner")
    await _join_home_as_partner(home_id, partner_email)
    partner_client = await _login_client(partner_email)
    try:
        listed = await partner_client.get(
            f"/api/v1/homes/{home_id}/events",
            params={"start_at": "2026-05-01T00:00:00Z", "end_at": "2026-07-01T00:00:00Z"},
        )
        assert event_id in {item["event_id"] for item in listed.json()["items"]}
        detail = await partner_client.get(f"/api/v1/homes/{home_id}/events/{event_id}")
        assert detail.status_code == 200
    finally:
        await partner_client.aclose()


# --------------------------------------------------------------------------
# Notifications
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_personal_event_reminder_notifies_only_its_owner(client: AsyncClient) -> None:
    owner_email = unique_email("remind")
    await create_verified_user(client, owner_email, "Remind Owner")
    owner_id = await _user_id(owner_email)
    home_id = await _home_with_calendar(client, "Remind Home", plan=SubscriptionPlan.family)
    personal_id = await _personal_calendar_id(client, home_id)

    # A calendar_view_all partner in the same Home — the exact profile that
    # must never be notified about a Personal Calendar event they aren't
    # (and structurally can't be) a member of.
    partner_email = unique_email("bystander")
    partner_id = await _join_home_as_partner(home_id, partner_email)

    start_at = datetime.now(UTC) + timedelta(minutes=10)
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json={
            "title": "Therapy",
            "start_at": start_at.isoformat(),
            "end_at": (start_at + timedelta(hours=1)).isoformat(),
            "timezone": "Europe/London",
            "reminder_minutes": 10,
            "member_ids": [],
            "calendar_id": personal_id,
        },
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["event_id"]

    async with SessionFactory() as db:
        await deliver_event_reminder(db, get_settings(), event_id, start_at.isoformat(), 10)
        await db.commit()

    async with SessionFactory() as db:
        owner_notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == owner_id)
        )
        partner_notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == partner_id)
        )
    assert owner_notification is not None, "the owner's own reminder must still fire"
    assert partner_notification is None, "a Personal Calendar event must never notify anyone else"
