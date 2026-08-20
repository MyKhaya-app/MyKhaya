"""Meal Plans (Family-only): entitlement gating, cross-Home authorisation,
Meals library CRUD, the planner (quick meals, saved meals, participants,
cook assignment, leftovers flag), and day/week retrieval.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

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
            token.id, TokenPurpose.verify_email.value, get_settings().secret_key.get_secret_value()
        )
    verified = await unsafe(client, "POST", "/api/v1/auth/verify-email", json={"token": raw})
    assert verified.status_code == 200
    login = await unsafe(
        client, "POST", "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200
    return user_id


async def create_home(
    client: AsyncClient, name: str, *, plan: SubscriptionPlan = SubscriptionPlan.family
) -> uuid.UUID:
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert group.status_code == 201
    home_id = uuid.UUID(group.json()["id"])
    async with SessionFactory() as db:
        db.add(FeatureOverride(feature_key=FeatureKey.meals, group_id=home_id, enabled=True))
        # Lists (FeatureKey.shopping) too — the ingredients-to-list flow
        # this test module also covers needs both modules released.
        db.add(FeatureOverride(feature_key=FeatureKey.shopping, group_id=home_id, enabled=True))
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        subscription.plan = plan
        await db.commit()
    return home_id


async def add_partner(client: AsyncClient, home_id: uuid.UUID, email: str, name: str) -> uuid.UUID:
    """A second adult member with standard_partner permissions (has
    meals.view/meals.manage — see household_permissions.py)."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as partner_client:
        user_id = await create_verified_user(partner_client, email, name)
    async with SessionFactory() as db:
        db.add(
            Membership(
                group_id=home_id,
                user_id=user_id,
                role=Role.adult_member,
                relationship=HouseholdRelationship.partner,
                permission_profile=PermissionProfile.standard_partner,
            )
        )
        await db.commit()
    return user_id


def meal_body(**overrides: object) -> dict:
    body = {
        "name": "Spaghetti Bolognese",
        "meal_type": "dinner",
        "ingredients": [
            {"text": "beef mince", "quantity": "500", "unit": "g"},
            {"text": "onion", "quantity": "1"},
        ],
    }
    body.update(overrides)
    return body


def entry_body(**overrides: object) -> dict:
    body = {
        "quick_meal_name": "Takeaway",
        "date": date.today().isoformat(),
        "meal_slot": "dinner",
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Entitlements
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_family_user_can_access_meal_plans(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("family"), "Family User")
    home_id = await create_home(client, "Family Meals Home")

    created = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/meals", json=meal_body()
    )
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "Spaghetti Bolognese"


@pytest.mark.asyncio
async def test_free_user_cannot_use_protected_meal_endpoints(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("free"), "Free User")
    home_id = await create_home(client, "Free Meals Home", plan=SubscriptionPlan.free)

    create = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/meals", json=meal_body())
    assert create.status_code == 403
    detail = create.json()["detail"]
    assert detail["code"] == "plan_feature_unavailable"
    assert detail["entitlement"] == "meals.enabled"

    listed = await client.get(f"/api/v1/homes/{home_id}/meals")
    assert listed.status_code == 403

    plan_entry = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/meal-plan/entries", json=entry_body()
    )
    assert plan_entry.status_code == 403

    day = await client.get(
        f"/api/v1/homes/{home_id}/meal-plan/day", params={"date": date.today().isoformat()}
    )
    assert day.status_code == 403


@pytest.mark.asyncio
async def test_meal_plans_feature_off_returns_404_even_on_family(client: AsyncClient) -> None:
    """The module_registry/FeatureOverride gate is independent of the
    commercial entitlement — a Family Home whose Platform Admin hasn't
    switched the feature on yet sees a plain 404, matching Calendar's
    require_feature behaviour."""
    await create_verified_user(client, unique_email("nofeature"), "No Feature User")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "No Feature Home"})
    home_id = uuid.UUID(group.json()["id"])
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()

    response = await client.get(f"/api/v1/homes/{home_id}/meals")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Authorisation / IDOR
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_cannot_read_or_modify_another_homes_meal(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("owner"), "Owner")
    home_id = await create_home(client, "Owner Home")
    created = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/meals", json=meal_body())
    meal_id = created.json()["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as outsider:
        await create_verified_user(outsider, unique_email("outsider"), "Outsider")
        outsider_home = await create_home(outsider, "Outsider Home")

        read = await outsider.get(f"/api/v1/homes/{outsider_home}/meals/{meal_id}")
        assert read.status_code == 404

        update = await unsafe(
            outsider,
            "PATCH",
            f"/api/v1/homes/{outsider_home}/meals/{meal_id}",
            json={**meal_body(), "expected_updated_at": "2000-01-01T00:00:00+00:00"},
        )
        assert update.status_code == 404

        delete = await unsafe(
            outsider, "DELETE", f"/api/v1/homes/{outsider_home}/meals/{meal_id}"
        )
        assert delete.status_code == 404

        # Cannot even reference the other Home's meal from within their own
        # (properly entitled) Home — not just "wrong home_id in the URL".
        cross_plan = await unsafe(
            outsider,
            "POST",
            f"/api/v1/homes/{outsider_home}/meal-plan/entries",
            json={
                "meal_id": meal_id,
                "date": date.today().isoformat(),
                "meal_slot": "dinner",
            },
        )
        assert cross_plan.status_code == 404


@pytest.mark.asyncio
async def test_user_cannot_assign_a_member_from_another_home(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("home-a"), "Home A Owner")
    home_a = await create_home(client, "Home A")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other:
        other_user_id = await create_verified_user(other, unique_email("home-b"), "Home B Owner")
        await create_home(other, "Home B")

    bad_participant = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_a}/meal-plan/entries",
        json={**entry_body(), "member_ids": [str(other_user_id)]},
    )
    assert bad_participant.status_code == 422

    bad_cook = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_a}/meal-plan/entries",
        json={**entry_body(), "cook_member_id": str(other_user_id)},
    )
    assert bad_cook.status_code == 422


# ---------------------------------------------------------------------------
# Meals library
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_meal_create_read_update_delete_favourite_and_ingredients(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("library"), "Library User")
    home_id = await create_home(client, "Library Home")

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meals",
        json=meal_body(
            description="Midweek favourite",
            prep_minutes=15,
            cook_minutes=30,
            servings=4,
            tags=["family favourite", "midweek"],
        ),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    meal_id = body["id"]
    assert body["is_favourite"] is False
    assert len(body["ingredients"]) == 2
    assert body["ingredients"][0]["text"] == "beef mince"
    assert body["ingredients"][0]["quantity"] == "500"
    assert body["ingredients"][0]["unit"] == "g"
    assert body["tags"] == ["family favourite", "midweek"]

    fetched = await client.get(f"/api/v1/homes/{home_id}/meals/{meal_id}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Spaghetti Bolognese"

    listed = await client.get(f"/api/v1/homes/{home_id}/meals")
    assert listed.status_code == 200
    assert any(item["id"] == meal_id for item in listed.json()["items"])

    updated = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/meals/{meal_id}",
        json={
            **meal_body(
                name="Spaghetti Bolognese (family size)",
                ingredients=[{"text": "beef mince", "quantity": "750", "unit": "g"}],
            ),
            "expected_updated_at": body["updated_at"],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Spaghetti Bolognese (family size)"
    assert len(updated.json()["ingredients"]) == 1
    assert updated.json()["ingredients"][0]["quantity"] == "750"

    favourited = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/meals/{meal_id}/favourite",
        json={"is_favourite": True},
    )
    assert favourited.status_code == 200
    assert favourited.json()["is_favourite"] is True

    favourites_only = await client.get(
        f"/api/v1/homes/{home_id}/meals", params={"favourite": "true"}
    )
    assert any(item["id"] == meal_id for item in favourites_only.json()["items"])

    deleted = await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/meals/{meal_id}")
    assert deleted.status_code == 204

    after_delete = await client.get(f"/api/v1/homes/{home_id}/meals")
    assert not any(item["id"] == meal_id for item in after_delete.json()["items"])

    still_readable_directly = await client.get(f"/api/v1/homes/{home_id}/meals/{meal_id}")
    assert still_readable_directly.status_code == 404


@pytest.mark.asyncio
async def test_meal_only_name_is_required(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("minimal"), "Minimal User")
    home_id = await create_home(client, "Minimal Home")

    created = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/meals", json={"name": "Leftovers"}
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["description"] is None
    assert body["ingredients"] == []
    assert body["meal_type"] == "dinner"


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quick_meal_does_not_require_a_saved_meal(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("quick"), "Quick User")
    home_id = await create_home(client, "Quick Meal Home")

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meal-plan/entries",
        json=entry_body(quick_meal_name="Takeaway"),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["meal_id"] is None
    assert body["quick_meal_name"] == "Takeaway"

    listed = await client.get(f"/api/v1/homes/{home_id}/meals")
    # A quick meal never pollutes the reusable Meals library.
    assert listed.json()["items"] == []


@pytest.mark.asyncio
async def test_entry_must_reference_exactly_one_of_meal_or_quick_name(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("neither"), "Neither User")
    home_id = await create_home(client, "Neither Home")

    neither = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meal-plan/entries",
        json={"date": date.today().isoformat(), "meal_slot": "dinner"},
    )
    assert neither.status_code == 422

    meal = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/meals", json=meal_body())
    meal_id = meal.json()["id"]
    both = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meal-plan/entries",
        json={
            "meal_id": meal_id,
            "quick_meal_name": "Also takeaway",
            "date": date.today().isoformat(),
            "meal_slot": "dinner",
        },
    )
    assert both.status_code == 422


@pytest.mark.asyncio
async def test_saved_meal_can_be_planned_with_time_participants_and_cook(
    client: AsyncClient,
) -> None:
    owner_id = await create_verified_user(client, unique_email("plan"), "Plan Owner")
    home_id = await create_home(client, "Plan Home")
    partner_id = await add_partner(client, home_id, unique_email("partner"), "Partner")

    meal = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/meals", json=meal_body())
    meal_id = meal.json()["id"]

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meal-plan/entries",
        json={
            "meal_id": meal_id,
            "date": date.today().isoformat(),
            "meal_slot": "dinner",
            "time": "18:30:00",
            "member_ids": [str(owner_id), str(partner_id)],
            "cook_member_id": str(partner_id),
            "makes_leftovers": True,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["meal_name"] == "Spaghetti Bolognese"
    assert body["time"] == "18:30:00"
    assert sorted(body["member_ids"]) == sorted([str(owner_id), str(partner_id)])
    assert body["cook_member_id"] == str(partner_id)
    assert body["makes_leftovers"] is True
    assert body["is_favourite"] is False


@pytest.mark.asyncio
async def test_omitted_participants_default_to_the_whole_household(client: AsyncClient) -> None:
    owner_id = await create_verified_user(client, unique_email("default"), "Default Owner")
    home_id = await create_home(client, "Default Participants Home")
    partner_id = await add_partner(client, home_id, unique_email("default-partner"), "Partner")

    created = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/meal-plan/entries", json=entry_body()
    )
    assert created.status_code == 201
    assert sorted(created.json()["member_ids"]) == sorted([str(owner_id), str(partner_id)])


@pytest.mark.asyncio
async def test_explicit_empty_participants_means_nobody(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("empty"), "Empty Owner")
    home_id = await create_home(client, "Empty Participants Home")

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meal-plan/entries",
        json={**entry_body(), "member_ids": []},
    )
    assert created.status_code == 201
    assert created.json()["member_ids"] == []


@pytest.mark.asyncio
async def test_all_three_slots_and_optional_time(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("slots"), "Slots User")
    home_id = await create_home(client, "Slots Home")

    slots = (
        ("breakfast", "Overnight oats"),
        ("lunch", "Chicken salad"),
        ("dinner", "Lasagne"),
    )
    for slot, name in slots:
        created = await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/meal-plan/entries",
            json=entry_body(quick_meal_name=name, meal_slot=slot),
        )
        assert created.status_code == 201, created.text
        assert created.json()["meal_slot"] == slot
        assert created.json()["time"] is None  # a meal without a time remains valid


@pytest.mark.asyncio
async def test_entry_update_and_soft_delete(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("update"), "Update User")
    home_id = await create_home(client, "Update Home")

    created = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/meal-plan/entries", json=entry_body()
    )
    entry = created.json()

    updated = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/meal-plan/entries/{entry['id']}",
        json={
            **entry_body(quick_meal_name="School lunch"),
            "expected_updated_at": entry["updated_at"],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["quick_meal_name"] == "School lunch"

    stale = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/meal-plan/entries/{entry['id']}",
        json={**entry_body(), "expected_updated_at": entry["updated_at"]},
    )
    assert stale.status_code == 409

    deleted = await unsafe(
        client, "DELETE", f"/api/v1/homes/{home_id}/meal-plan/entries/{entry['id']}"
    )
    assert deleted.status_code == 204

    gone = await client.get(f"/api/v1/homes/{home_id}/meal-plan/entries/{entry['id']}")
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_day_and_week_retrieval(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("week"), "Week User")
    home_id = await create_home(client, "Week Home")

    today = date.today()
    tomorrow = today + timedelta(days=1)
    await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meal-plan/entries",
        json=entry_body(
            quick_meal_name="Tonight's dinner", date=today.isoformat(), meal_slot="dinner"
        ),
    )
    await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meal-plan/entries",
        json=entry_body(
            quick_meal_name="Tomorrow's breakfast", date=tomorrow.isoformat(), meal_slot="breakfast"
        ),
    )

    day = await client.get(
        f"/api/v1/homes/{home_id}/meal-plan/day", params={"date": today.isoformat()}
    )
    assert day.status_code == 200
    assert len(day.json()["entries"]) == 1
    assert day.json()["entries"][0]["quick_meal_name"] == "Tonight's dinner"

    week = await client.get(
        f"/api/v1/homes/{home_id}/meal-plan/week", params={"start_date": today.isoformat()}
    )
    assert week.status_code == 200
    days = week.json()["days"]
    assert len(days) == 7
    assert days[0]["date"] == today.isoformat()
    assert len(days[0]["entries"]) == 1
    assert len(days[1]["entries"]) == 1
    assert days[1]["entries"][0]["quick_meal_name"] == "Tomorrow's breakfast"
    assert all(not d["entries"] for d in days[2:])


@pytest.mark.asyncio
async def test_removed_member_does_not_corrupt_the_meal_plan(client: AsyncClient) -> None:
    """Membership changing later (a member being removed) must fail safe —
    the plan entry keeps existing, simply no longer counting that user as
    an active participant in the household's current member list."""
    owner_id = await create_verified_user(client, unique_email("safe"), "Safe Owner")
    home_id = await create_home(client, "Safe Home")
    partner_id = await add_partner(client, home_id, unique_email("safe-partner"), "Partner")

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meal-plan/entries",
        json={**entry_body(), "member_ids": [str(owner_id), str(partner_id)]},
    )
    entry_id = created.json()["id"]

    async with SessionFactory() as db:
        membership = await db.scalar(
            select(Membership).where(
                Membership.group_id == home_id, Membership.user_id == partner_id
            )
        )
        assert membership is not None
        membership.removed_at = datetime.now(UTC)
        await db.commit()

    fetched = await client.get(f"/api/v1/homes/{home_id}/meal-plan/entries/{entry_id}")
    assert fetched.status_code == 200, fetched.text


# ---------------------------------------------------------------------------
# Timezone: a meal's date/time is a plain wall-clock value, never converted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planned_meal_time_round_trips_exactly_regardless_of_timezone(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("tz"), "Timezone User")
    home_id = await create_home(client, "Timezone Home")

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meal-plan/entries",
        json=entry_body(time="18:30:00"),
    )
    assert created.status_code == 201
    entry_id = created.json()["id"]
    assert created.json()["time"] == "18:30:00"

    # No UTC conversion happens anywhere — the same 18:30 comes back
    # whichever "now" the read happens at, unlike a datetime+timezone
    # instant which would need to be re-localised.
    fetched = await client.get(f"/api/v1/homes/{home_id}/meal-plan/entries/{entry_id}")
    assert fetched.json()["time"] == "18:30:00"
    assert fetched.json()["date"] == date.today().isoformat()


@pytest.mark.asyncio
async def test_billing_status_exposes_meals_enabled_for_the_frontend_locked_state(
    client: AsyncClient,
) -> None:
    """The Meal Plans nav entry's locked state (FamilyUpsell) reads this
    directly rather than inferring it from effective_plan — same pattern
    as household_routines_enabled/shared_events_enabled."""
    await create_verified_user(client, unique_email("billing"), "Billing User")
    home_id = await create_home(client, "Billing Free Home", plan=SubscriptionPlan.free)
    free_status = await client.get(f"/api/v1/groups/{home_id}/billing")
    assert free_status.status_code == 200
    assert free_status.json()["meals_enabled"] is False

    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()

    family_status = await client.get(f"/api/v1/groups/{home_id}/billing")
    assert family_status.status_code == 200
    assert family_status.json()["meals_enabled"] is True


@pytest.mark.asyncio
async def test_billing_status_exposes_lists_enabled(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("lists-billing"), "Lists Billing User")
    home_id = await create_home(client, "Lists Billing Free Home", plan=SubscriptionPlan.free)
    free_status = await client.get(f"/api/v1/groups/{home_id}/billing")
    assert free_status.json()["lists_enabled"] is False

    home_id_family = await create_home(client, "Lists Billing Family Home")
    family_status = await client.get(f"/api/v1/groups/{home_id_family}/billing")
    assert family_status.json()["lists_enabled"] is True


# ---------------------------------------------------------------------------
# Meals library list shape (lightweight, batched) and recently-used
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_meal_list_response_omits_ingredients_but_reports_a_count(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("summary"), "Summary User")
    home_id = await create_home(client, "Summary Home")
    created = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/meals", json=meal_body())
    assert created.status_code == 201

    listed = await client.get(f"/api/v1/homes/{home_id}/meals")
    assert listed.status_code == 200
    row = listed.json()["items"][0]
    assert "ingredients" not in row
    assert row["ingredient_count"] == 2


@pytest.mark.asyncio
async def test_recently_used_meals_derived_from_plan_history(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("recent"), "Recent User")
    home_id = await create_home(client, "Recent Home")
    meal = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/meals", json=meal_body())
    meal_id = meal.json()["id"]

    empty = await client.get(f"/api/v1/homes/{home_id}/meals/recent")
    assert empty.json()["items"] == []

    await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meal-plan/entries",
        json=entry_body(meal_id=meal_id, quick_meal_name=None),
    )
    recent = await client.get(f"/api/v1/homes/{home_id}/meals/recent")
    assert recent.status_code == 200
    assert len(recent.json()["items"]) == 1
    assert recent.json()["items"][0]["meal"]["id"] == meal_id
    assert recent.json()["items"][0]["last_planned"] == date.today().isoformat()


# ---------------------------------------------------------------------------
# Save a quick meal to the library
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_quick_meal_to_library(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("save-quick"), "Save Quick User")
    home_id = await create_home(client, "Save Quick Home")
    entry = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meal-plan/entries",
        json=entry_body(quick_meal_name="Fajitas"),
    )
    entry_id = entry.json()["id"]

    saved = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/meal-plan/entries/{entry_id}/save-as-meal"
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["quick_meal_name"] is None
    assert body["meal_id"] is not None
    assert body["meal_name"] == "Fajitas"

    library = await client.get(f"/api/v1/homes/{home_id}/meals")
    assert any(row["name"] == "Fajitas" for row in library.json()["items"])

    again = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/meal-plan/entries/{entry_id}/save-as-meal"
    )
    assert again.status_code == 409


# ---------------------------------------------------------------------------
# Household Lists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lists_crud_and_items(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("lists-crud"), "Lists Crud User")
    home_id = await create_home(client, "Lists Crud Home")

    created = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/lists", json={"name": "Groceries"}
    )
    assert created.status_code == 201
    list_id = created.json()["id"]
    assert created.json()["items"] == []

    listed = await client.get(f"/api/v1/homes/{home_id}/lists")
    assert listed.status_code == 200
    assert any(row["id"] == list_id and row["item_count"] == 0 for row in listed.json()["items"])

    item = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/lists/{list_id}/items",
        json={"text": "Milk"},
    )
    assert item.status_code == 201
    item_id = item.json()["items"][0]["id"]
    assert item.json()["items"][0]["is_checked"] is False

    toggled = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/lists/{list_id}/items/{item_id}",
        json={"is_checked": True},
    )
    assert toggled.json()["items"][0]["is_checked"] is True

    removed = await unsafe(
        client, "DELETE", f"/api/v1/homes/{home_id}/lists/{list_id}/items/{item_id}"
    )
    assert removed.status_code == 200
    assert removed.json()["items"] == []

    deleted = await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/lists/{list_id}")
    assert deleted.status_code == 204
    after_delete = await client.get(f"/api/v1/homes/{home_id}/lists/{list_id}")
    assert after_delete.status_code == 404


@pytest.mark.asyncio
async def test_user_cannot_read_or_write_another_homes_list(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("lists-a"), "Lists Home A")
    home_a = await create_home(client, "Lists Home A")
    created = await unsafe(client, "POST", f"/api/v1/homes/{home_a}/lists", json={"name": "A"})
    list_id = created.json()["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        await create_verified_user(other_client, unique_email("lists-b"), "Lists Home B")
        home_b = await create_home(other_client, "Lists Home B")

        read = await other_client.get(f"/api/v1/homes/{home_b}/lists/{list_id}")
        assert read.status_code == 404

        write = await unsafe(
            other_client,
            "POST",
            f"/api/v1/homes/{home_b}/lists/{list_id}/items",
            json={"text": "Sneaky"},
        )
        assert write.status_code == 404


# ---------------------------------------------------------------------------
# Ingredients -> Lists integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_meal_ingredients_to_list(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("add-ing"), "Add Ingredients User")
    home_id = await create_home(client, "Add Ingredients Home")
    meal = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/meals", json=meal_body())
    meal_id = meal.json()["id"]
    target_list = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/lists", json={"name": "Groceries"}
    )
    list_id = target_list.json()["id"]

    result = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meals/{meal_id}/add-ingredients-to-list",
        json={"list_id": list_id},
    )
    assert result.status_code == 200
    body = result.json()
    assert body["requires_confirmation"] is False
    assert body["added_count"] == 2

    fetched_list = await client.get(f"/api/v1/homes/{home_id}/lists/{list_id}")
    texts = {row["text"] for row in fetched_list.json()["items"]}
    assert texts == {"500 g beef mince", "1 onion"}


@pytest.mark.asyncio
async def test_add_ingredients_to_list_warns_then_skips_duplicates(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("dupe"), "Dupe User")
    home_id = await create_home(client, "Dupe Home")
    meal = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/meals", json=meal_body())
    meal_id = meal.json()["id"]
    target_list = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/lists", json={"name": "Groceries"}
    )
    list_id = target_list.json()["id"]
    # Pre-seed one duplicate (case-insensitive exact text match).
    await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/lists/{list_id}/items",
        json={"text": "500 G BEEF MINCE"},
    )

    first_call = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meals/{meal_id}/add-ingredients-to-list",
        json={"list_id": list_id},
    )
    assert first_call.status_code == 200
    body = first_call.json()
    assert body["requires_confirmation"] is True
    assert body["added_count"] == 0
    assert body["duplicate_count"] == 1

    fetched_list = await client.get(f"/api/v1/homes/{home_id}/lists/{list_id}")
    assert len(fetched_list.json()["items"]) == 1  # nothing added yet

    confirmed = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meals/{meal_id}/add-ingredients-to-list",
        json={"list_id": list_id, "confirm": True},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["added_count"] == 1  # only the non-duplicate

    fetched_list = await client.get(f"/api/v1/homes/{home_id}/lists/{list_id}")
    assert len(fetched_list.json()["items"]) == 2


@pytest.mark.asyncio
async def test_add_ingredients_to_list_rejects_a_meal_with_no_ingredients(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("no-ing"), "No Ingredients User")
    home_id = await create_home(client, "No Ingredients Home")
    meal = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/meals", json={"name": "Cereal"}
    )
    meal_id = meal.json()["id"]
    target_list = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/lists", json={"name": "Groceries"}
    )
    result = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meals/{meal_id}/add-ingredients-to-list",
        json={"list_id": target_list.json()["id"]},
    )
    assert result.status_code == 422


@pytest.mark.asyncio
async def test_add_ingredients_to_list_rejects_cross_home_list_and_deleted_meal(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("cross-add"), "Cross Add User")
    home_id = await create_home(client, "Cross Add Home")
    meal = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/meals", json=meal_body())
    meal_id = meal.json()["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        await create_verified_user(other_client, unique_email("cross-add-b"), "Other Home")
        other_home = await create_home(other_client, "Other Home")
        other_list = await unsafe(
            other_client, "POST", f"/api/v1/homes/{other_home}/lists", json={"name": "Theirs"}
        )
        other_list_id = other_list.json()["id"]

        # Same Home's meal, but a List belonging to a different Home.
        cross = await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/meals/{meal_id}/add-ingredients-to-list",
            json={"list_id": other_list_id},
        )
        assert cross.status_code == 404

    # A deleted Meal must also be rejected, not silently resurrected.
    own_list = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/lists", json={"name": "Own"}
    )
    await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/meals/{meal_id}")
    deleted_meal = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meals/{meal_id}/add-ingredients-to-list",
        json={"list_id": own_list.json()["id"]},
    )
    assert deleted_meal.status_code == 404


@pytest.mark.asyncio
async def test_add_ingredients_to_list_requires_meals_and_lists_entitlement(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("free-add"), "Free Add User")
    home_id = await create_home(client, "Free Add Home", plan=SubscriptionPlan.free)
    result = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meals/{uuid.uuid4()}/add-ingredients-to-list",
        json={"list_id": str(uuid.uuid4())},
    )
    assert result.status_code == 403
    assert result.json()["detail"]["code"] == "plan_feature_unavailable"


# ---------------------------------------------------------------------------
# Copy previous week
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_copy_previous_week_copies_and_skips_existing(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("copy"), "Copy User")
    home_id = await create_home(client, "Copy Home")
    partner_id = await add_partner(client, home_id, unique_email("copy-partner"), "Partner")

    source_start = date.today() - timedelta(days=date.today().weekday())
    target_start = source_start + timedelta(days=7)

    meal = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/meals", json=meal_body())
    meal_id = meal.json()["id"]

    await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meal-plan/entries",
        json=entry_body(
            meal_id=meal_id,
            quick_meal_name=None,
            date=source_start.isoformat(),
            meal_slot="dinner",
            time="18:30:00",
            member_ids=[str(partner_id)],
            cook_member_id=str(partner_id),
            makes_leftovers=True,
        ),
    )
    await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meal-plan/entries",
        json=entry_body(date=source_start.isoformat(), meal_slot="lunch"),
    )
    # Target already has a Tuesday breakfast planned — must be left alone.
    already_there = source_start + timedelta(days=1)
    await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meal-plan/entries",
        json=entry_body(
            date=already_there.isoformat(), meal_slot="breakfast", quick_meal_name="Existing"
        ),
    )
    await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meal-plan/entries",
        json=entry_body(
            date=(already_there + timedelta(days=7)).isoformat(),
            meal_slot="breakfast",
            quick_meal_name="Don't touch me",
        ),
    )

    preview = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meal-plan/week/copy",
        json={
            "source_start_date": source_start.isoformat(),
            "target_start_date": target_start.isoformat(),
            "dry_run": True,
        },
    )
    assert preview.status_code == 200
    assert preview.json() == {"copied_count": 2, "skipped_count": 1}

    # A dry run must not have written anything.
    target_week = await client.get(
        f"/api/v1/homes/{home_id}/meal-plan/week?start_date={target_start.isoformat()}"
    )
    total_target_entries = sum(len(day["entries"]) for day in target_week.json()["days"])
    assert total_target_entries == 1  # only the pre-seeded "Don't touch me"

    committed = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meal-plan/week/copy",
        json={
            "source_start_date": source_start.isoformat(),
            "target_start_date": target_start.isoformat(),
        },
    )
    assert committed.status_code == 200
    assert committed.json() == {"copied_count": 2, "skipped_count": 1}

    target_week = await client.get(
        f"/api/v1/homes/{home_id}/meal-plan/week?start_date={target_start.isoformat()}"
    )
    days_by_date = {day["date"]: day["entries"] for day in target_week.json()["days"]}
    dinner = next(e for e in days_by_date[target_start.isoformat()] if e["meal_slot"] == "dinner")
    assert dinner["meal_id"] == meal_id
    assert dinner["time"] == "18:30:00"
    assert dinner["member_ids"] == [str(partner_id)]
    assert dinner["cook_member_id"] == str(partner_id)
    assert dinner["makes_leftovers"] is True

    # The pre-existing breakfast the following week was never overwritten.
    untouched_date = (already_there + timedelta(days=7)).isoformat()
    breakfast = next(e for e in days_by_date[untouched_date] if e["meal_slot"] == "breakfast")
    assert breakfast["quick_meal_name"] == "Don't touch me"


@pytest.mark.asyncio
async def test_copy_previous_week_omits_removed_participants_and_deleted_meals(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("copy-safe"), "Copy Safe User")
    home_id = await create_home(client, "Copy Safe Home")
    partner_id = await add_partner(client, home_id, unique_email("copy-safe-p"), "Partner")

    source_start = date.today() - timedelta(days=date.today().weekday())
    target_start = source_start + timedelta(days=14)

    meal = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/meals", json=meal_body())
    meal_id = meal.json()["id"]
    await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meal-plan/entries",
        json=entry_body(
            meal_id=meal_id,
            quick_meal_name=None,
            date=source_start.isoformat(),
            meal_slot="dinner",
            member_ids=[str(partner_id)],
            cook_member_id=str(partner_id),
        ),
    )

    # The Meal gets soft-deleted, and the partner leaves the Home, before
    # the copy happens.
    await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/meals/{meal_id}")
    async with SessionFactory() as db:
        membership = await db.scalar(
            select(Membership).where(
                Membership.group_id == home_id, Membership.user_id == partner_id
            )
        )
        assert membership is not None
        membership.removed_at = datetime.now(UTC)
        await db.commit()

    result = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meal-plan/week/copy",
        json={
            "source_start_date": source_start.isoformat(),
            "target_start_date": target_start.isoformat(),
        },
    )
    assert result.status_code == 200
    assert result.json()["copied_count"] == 1

    target_week = await client.get(
        f"/api/v1/homes/{home_id}/meal-plan/week?start_date={target_start.isoformat()}"
    )
    days_by_date = {day["date"]: day["entries"] for day in target_week.json()["days"]}
    dinner = next(e for e in days_by_date[target_start.isoformat()] if e["meal_slot"] == "dinner")
    # The deleted Meal falls back to its name as a quick meal, not a
    # resurrected reference; the removed partner is simply omitted.
    assert dinner["meal_id"] is None
    assert dinner["quick_meal_name"] == "Spaghetti Bolognese"
    assert dinner["member_ids"] == []
    assert dinner["cook_member_id"] is None


@pytest.mark.asyncio
async def test_copy_previous_week_cross_home_isolation(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("copy-x"), "Copy X User")
    home_id = await create_home(client, "Copy X Home")
    source_start = date.today() - timedelta(days=date.today().weekday())
    await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meal-plan/entries",
        json=entry_body(date=source_start.isoformat(), meal_slot="dinner"),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        await create_verified_user(other_client, unique_email("copy-y"), "Copy Y User")
        other_home = await create_home(other_client, "Copy Y Home")
        # Another Home cannot use a source week to read/copy this Home's
        # entries into itself just by naming the same date range — the
        # source range is always read scoped to the *caller's* home_id.
        result = await unsafe(
            other_client,
            "POST",
            f"/api/v1/homes/{other_home}/meal-plan/week/copy",
            json={
                "source_start_date": source_start.isoformat(),
                "target_start_date": (source_start + timedelta(days=7)).isoformat(),
            },
        )
        assert result.status_code == 200
        assert result.json()["copied_count"] == 0
