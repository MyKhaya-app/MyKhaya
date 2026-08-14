"""Event categories are CalendarEventLabel, not HomeCalendar — the actual
user-facing resource shown on Settings -> Home settings' "Calendars &
categories" page ("Every event belongs to one of these — its colour...
is what shows on Calendar"). A Free Home was previously seeded with all 7
default labels active simultaneously, so despite calendar.max_categories
being enforced against HomeCalendar creation, a Free Home could freely use
Family/School/Work/Appointment/Birthday/Activity/Other as fully active,
manageable categories on this exact screen. See
docs/architecture/commercial-entitlements.md "Event categories are
CalendarEventLabel, not HomeCalendar".
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import get_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    CalendarEventLabel,
    FeatureKey,
    FeatureOverride,
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
    home_id = uuid.UUID(group.json()["id"])
    async with SessionFactory() as db:
        db.add(FeatureOverride(feature_key=FeatureKey.calendar, group_id=home_id, enabled=True))
        await db.commit()
    return home_id


async def _set_subscription(home_id: uuid.UUID, **fields: object) -> None:
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        for key, value in fields.items():
            setattr(subscription, key, value)
        await db.commit()


async def _label_rows(home_id: uuid.UUID) -> list[CalendarEventLabel]:
    async with SessionFactory() as db:
        return list(
            (
                await db.scalars(
                    select(CalendarEventLabel)
                    .where(CalendarEventLabel.group_id == home_id)
                    .order_by(CalendarEventLabel.sort_order)
                )
            ).all()
        )


def _suffix() -> str:
    return datetime.now(UTC).strftime("%H%M%S%f")


def _event_body(**overrides: object) -> dict:
    start = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)
    body = {
        "title": "Something",
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(hours=1)).isoformat(),
        "timezone": "Europe/London",
        "is_all_day": False,
        "member_ids": [],
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Free: exactly one usable category, seeded or created
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_free_home_has_exactly_one_active_seeded_category(client: AsyncClient) -> None:
    home_id = await _make_home(client, _suffix())
    rows = await _label_rows(home_id)
    assert len(rows) == 7, "all 7 default categories are still seeded, just not all active"
    active = [row for row in rows if row.is_active]
    assert len(active) == 1
    assert active[0].name == "Family"  # first seeded default stays the one active category


@pytest.mark.asyncio
async def test_settings_page_endpoint_shows_one_normal_category_and_the_rest_locked(
    client: AsyncClient,
) -> None:
    home_id = await _make_home(client, _suffix())
    response = await unsafe(
        client, "GET", f"/api/v1/homes/{home_id}/event-labels", params={"include_inactive": "true"}
    )
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 7
    normal = [row for row in items if row["commercial_access"] == "normal"]
    locked = [row for row in items if row["commercial_access"] == "read_only_due_to_plan"]
    assert len(normal) == 1
    assert len(locked) == 6
    assert normal[0]["is_active"] is True
    assert all(not row["is_active"] for row in locked)


@pytest.mark.asyncio
async def test_free_home_cannot_create_a_second_category(client: AsyncClient) -> None:
    home_id = await _make_home(client, _suffix())
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/event-labels",
        json={"name": "Sport", "color": "emerald"},
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "plan_limit_reached"
    assert detail["entitlement"] == "calendar.max_categories"


@pytest.mark.asyncio
async def test_free_home_cannot_activate_a_second_seeded_category(client: AsyncClient) -> None:
    home_id = await _make_home(client, _suffix())
    rows = await _label_rows(home_id)
    inactive = next(row for row in rows if not row.is_active)
    response = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/event-labels/{inactive.id}",
        json={"is_active": True},
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "plan_limit_reached"
    assert detail["entitlement"] == "calendar.max_categories"


@pytest.mark.asyncio
async def test_free_home_can_rename_and_recolour_its_one_usable_category(
    client: AsyncClient,
) -> None:
    home_id = await _make_home(client, _suffix())
    rows = await _label_rows(home_id)
    active = next(row for row in rows if row.is_active)
    response = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/event-labels/{active.id}",
        json={"name": "Our Household", "color": "rose"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Our Household"
    assert response.json()["color"] == "rose"


# ---------------------------------------------------------------------------
# Family: unlimited active categories
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_family_home_can_activate_multiple_seeded_categories(client: AsyncClient) -> None:
    home_id = await _make_home(client, _suffix())
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    rows = await _label_rows(home_id)
    for row in rows:
        response = await unsafe(
            client,
            "PATCH",
            f"/api/v1/homes/{home_id}/event-labels/{row.id}",
            json={"is_active": True},
        )
        assert response.status_code == 200, response.text

    async with SessionFactory() as db:
        active_count = await db.scalar(
            select(func.count())
            .select_from(CalendarEventLabel)
            .where(CalendarEventLabel.group_id == home_id, CalendarEventLabel.is_active.is_(True))
        )
    assert active_count == 7


@pytest.mark.asyncio
async def test_family_home_can_create_new_categories(client: AsyncClient) -> None:
    home_id = await _make_home(client, _suffix())
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    for name in ("Sport", "Holidays", "Volunteering"):
        response = await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/event-labels",
            json={"name": name, "color": "emerald"},
        )
        assert response.status_code == 201, response.text


# ---------------------------------------------------------------------------
# Downgrade: preserve historical data, only one usable category going forward
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_downgrade_preserves_categories_but_only_one_remains_usable(
    client: AsyncClient,
) -> None:
    home_id = await _make_home(client, _suffix())
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    rows = await _label_rows(home_id)
    for row in rows[:3]:
        activated = await unsafe(
            client,
            "PATCH",
            f"/api/v1/homes/{home_id}/event-labels/{row.id}",
            json={"is_active": True},
        )
        assert activated.status_code == 200

    await _set_subscription(home_id, plan=SubscriptionPlan.free)

    # Nothing was deleted or deactivated by the downgrade itself.
    after = await _label_rows(home_id)
    assert len(after) == 7
    assert sum(1 for row in after if row.is_active) == 3

    listing = await unsafe(
        client, "GET", f"/api/v1/homes/{home_id}/event-labels", params={"include_inactive": "true"}
    )
    items = listing.json()
    normal = [row for row in items if row["commercial_access"] == "normal"]
    assert len(normal) == 1
    assert normal[0]["id"] == str(rows[0].id)

    # Cannot create another.
    blocked_create = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/event-labels",
        json={"name": "New One", "color": "blue"},
    )
    assert blocked_create.status_code == 403

    # Cannot reactivate/newly activate the 6 that were never active either.
    inactive = next(row for row in after if not row.is_active)
    blocked_activate = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/event-labels/{inactive.id}",
        json={"is_active": True},
    )
    assert blocked_activate.status_code == 403


@pytest.mark.asyncio
async def test_downgraded_home_cannot_assign_a_locked_category_to_a_new_event(
    client: AsyncClient,
) -> None:
    home_id = await _make_home(client, _suffix())
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    rows = await _label_rows(home_id)
    second = rows[1]
    activated = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/event-labels/{second.id}",
        json={"is_active": True},
    )
    assert activated.status_code == 200

    await _set_subscription(home_id, plan=SubscriptionPlan.free)

    blocked = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body(label_id=str(second.id)),
    )
    assert blocked.status_code == 403
    detail = blocked.json()["detail"]
    assert detail["code"] == "resource_restricted_by_plan"
    assert detail["entitlement"] == "calendar.max_categories"


@pytest.mark.asyncio
async def test_downgraded_home_can_still_use_the_one_normal_category_for_a_new_event(
    client: AsyncClient,
) -> None:
    home_id = await _make_home(client, _suffix())
    rows = await _label_rows(home_id)
    normal = next(row for row in rows if row.is_active)

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body(label_id=str(normal.id)),
    )
    assert created.status_code == 201, created.text


@pytest.mark.asyncio
async def test_existing_historical_event_keeps_rendering_after_downgrade(
    client: AsyncClient,
) -> None:
    home_id = await _make_home(client, _suffix())
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    rows = await _label_rows(home_id)
    second = rows[1]
    await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/event-labels/{second.id}",
        json={"is_active": True},
    )
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body(label_id=str(second.id)),
    )
    assert created.status_code == 201
    event_id = created.json()["event_id"]

    await _set_subscription(home_id, plan=SubscriptionPlan.free)

    detail = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/events/{event_id}")
    assert detail.status_code == 200
    assert detail.json()["event"]["label"]["id"] == str(second.id)
    assert detail.json()["event"]["label"]["color"] == second.color.value

    # Resaving the event with the same (locked) category, only changing an
    # unrelated field, must still work — never destroy historical rendering.
    event = detail.json()["event"]
    resaved = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/events/{event_id}",
        json=_event_body(
            label_id=str(second.id),
            title="Renamed",
            expected_updated_at=event["updated_at"],
        ),
    )
    assert resaved.status_code == 200, resaved.text
    assert resaved.json()["label"]["id"] == str(second.id)


@pytest.mark.asyncio
async def test_free_to_family_restores_full_access_to_preserved_categories(
    client: AsyncClient,
) -> None:
    home_id = await _make_home(client, _suffix())
    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    rows = await _label_rows(home_id)
    for row in rows[:3]:
        await unsafe(
            client,
            "PATCH",
            f"/api/v1/homes/{home_id}/event-labels/{row.id}",
            json={"is_active": True},
        )

    await _set_subscription(home_id, plan=SubscriptionPlan.free)
    blocked = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body(label_id=str(rows[1].id)),
    )
    assert blocked.status_code == 403

    await _set_subscription(home_id, plan=SubscriptionPlan.family)
    restored = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/events",
        json=_event_body(label_id=str(rows[1].id)),
    )
    assert restored.status_code == 201, restored.text
