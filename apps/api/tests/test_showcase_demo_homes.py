# Fixtures shared with test_free_family_demo_qa are imported by name and then
# requested as test parameters, which is how pytest resolves them.
# ruff: noqa: F811
"""Family Demo / Ultimate Demo showcase Homes, end to end through the real
PCC API and the real household API.

Every test provisions its own uniquely-keyed managed Home with a fresh
operator and deletes both in teardown (fixtures shared with
test_free_family_demo_qa.py). Ultimate tests pin a mid-month reference date
so Budget volumes are deterministic regardless of the day the suite runs.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from test_free_family_demo_qa import (  # noqa: F401  (pytest fixtures)
    ADMIN_ORIGIN,
    FIXTURE_PASSWORD,
    admin_client,
    admin_factory,
    admin_login,
    demo_keys,
    household_client,
    login_as_owner,
    unsafe,
)

from mykhaya import driveway_mot
from mykhaya.db import SessionFactory
from mykhaya.entitlements import effective_plan, get_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    AuthIdentity,
    ChildProfile,
    FeatureFlag,
    FeatureKey,
    GuardianAssignment,
    HouseholdList,
    HouseholdRelationship,
    HouseholdRoutine,
    HouseholdRoutineCompletion,
    ManagedDemoHome,
    Membership,
    PlatformRole,
    Reminder,
    SubscriptionPlan,
    SubscriptionProvider,
    Todo,
    User,
)
from mykhaya.showcase import parker
from mykhaya.showcase.registry import modules_for_plan

# A Wednesday in the middle of a month: Budget's current period then holds
# roughly half a month of activity on top of a full previous month.
PINNED = date(2026, 10, 14)
SHOWCASE_FLAGS = (
    FeatureKey.calendar,
    FeatureKey.shopping,
    FeatureKey.meals,
    FeatureKey.wish_lists,
    FeatureKey.nudges,
    FeatureKey.budget,
    FeatureKey.driveway,
)


@pytest.fixture(autouse=True)
async def platform_modules_released() -> AsyncIterator[None]:
    """PCC's global module flags are authoritative and independent of the
    plan; release the showcase modules for this suite and restore after."""
    previous: dict[FeatureKey, bool | None] = {}
    async with SessionFactory() as db:
        for key in SHOWCASE_FLAGS:
            flag = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == key))
            previous[key] = None if flag is None else flag.enabled
            if flag is None:
                db.add(FeatureFlag(key=key, enabled=True))
            else:
                flag.enabled = True
        await db.commit()
    yield
    async with SessionFactory() as db:
        for key, enabled in previous.items():
            flag = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == key))
            if flag is not None and enabled is not None:
                flag.enabled = enabled
        await db.commit()


async def provision(
    admin_client: AsyncClient,
    admin: Any,
    demo_keys: list[str],
    *,
    fixture_type: str,
    **options: Any,
) -> dict[str, Any]:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    fixture_key = f"showcase-{fixture_type.replace('_', '-')}-{suffix}"
    await admin_login(admin_client, admin)
    body: dict[str, Any] = {
        "fixture_key": fixture_key,
        "display_name": "The Parker Family",
        "fixture_type": fixture_type,
        "email": f"{fixture_key}@demo.mykhaya.app",
        "password": FIXTURE_PASSWORD,
        "enabled": True,
        **options,
    }
    response = await unsafe(admin_client, "POST", "/api/v1/platform/demo-test-homes", json=body)
    assert response.status_code == 201, response.text
    demo_keys.append(fixture_key)
    return response.json()


Factory = Callable[[PlatformRole], Awaitable[Any]]


# --- Provisioning and entitlements ---------------------------------------------------


@pytest.mark.asyncio
async def test_family_demo_provisions_a_populated_family_home(
    admin_client: AsyncClient,
    household_client: AsyncClient,
    admin_factory: Factory,
    demo_keys: list[str],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    created = await provision(admin_client, admin, demo_keys, fixture_type="demo")

    assert created["access"] == "family"
    assert created["showcase"] is True
    assert created["showcase_populated"] is True
    assert created["showcase_date_mode"] == "rolling"
    counts = created["showcase_counts"]
    assert counts["members"] == 4
    assert counts["calendar_events"] == len(parker.EVENTS)
    assert counts["routines"] == len(parker.ROUTINES)
    assert counts["reminders"] == len(parker.REMINDERS)
    assert counts["todos"] == len(parker.TODOS)
    assert counts["meals"] == len(parker.RECIPES) == 20
    assert counts["lists"] == len(parker.LISTS)
    assert counts["wishlists"] == len(parker.WISHLISTS)
    # Ultimate-only modules are absent from a Family Home.
    assert counts["budget_transactions"] == 0
    assert counts["vehicles"] == 0

    home_id = created["home_id"]
    await login_as_owner(household_client, created["account_email"])
    me = await household_client.get("/api/v1/users/me")
    assert me.status_code == 200
    assert me.json()["display_name"] == "Emma Parker"

    # Real Family entitlements: Family modules open, Ultimate modules closed.
    meals = await household_client.get(f"/api/v1/homes/{home_id}/meals")
    assert meals.status_code == 200
    assert len(meals.json()["items"]) == 20
    budget = await household_client.get(f"/api/v1/homes/{home_id}/budget")
    assert budget.status_code == 403
    assert budget.json()["detail"]["code"] == "plan_feature_unavailable"
    vehicles = await household_client.get(f"/api/v1/homes/{home_id}/vehicles")
    assert vehicles.status_code in (403, 404)


@pytest.mark.asyncio
async def test_primary_account_landing_views_are_populated_and_mostly_on_track(
    admin_client: AsyncClient,
    admin_factory: Factory,
    demo_keys: list[str],
) -> None:
    """Nudges and Lists open on the signed-in member's Personal tab, so Emma
    must own personal items there; and the dashboard must not open on a run
    of overdue weekly chores."""
    admin = await admin_factory(PlatformRole.owner)
    created = await provision(
        admin_client, admin, demo_keys, fixture_type="demo", showcase_reference_date=str(PINNED)
    )
    home_id = uuid.UUID(created["home_id"])
    async with SessionFactory() as db:
        owner_id = await db.scalar(
            select(ManagedDemoHome.owner_user_id).where(ManagedDemoHome.home_id == home_id)
        )
        personal_reminders = await db.scalar(
            select(func.count())
            .select_from(Reminder)
            .where(Reminder.group_id == home_id, Reminder.owner_user_id == owner_id)
        )
        personal_todos = await db.scalar(
            select(func.count())
            .select_from(Todo)
            .where(Todo.group_id == home_id, Todo.owner_user_id == owner_id)
        )
        personal_lists = await db.scalar(
            select(func.count())
            .select_from(HouseholdList)
            .where(HouseholdList.group_id == home_id, HouseholdList.scope == "personal")
        )
        assert personal_reminders == sum(1 for r in parker.REMINDERS if r.personal_owner)
        assert personal_reminders and personal_reminders >= 3
        assert personal_todos and personal_todos >= 3
        assert personal_lists == 1

        weekly = (
            await db.scalars(
                select(HouseholdRoutine).where(
                    HouseholdRoutine.group_id == home_id,
                    HouseholdRoutine.repeat_unit == "weekly",
                )
            )
        ).all()
        assert weekly
        for routine in weekly:
            yesterday = PINNED - timedelta(days=1)
            spec = next(s for s in parker.ROUTINES if s.title == routine.title)
            assert spec.weekday is not None
            latest = yesterday - timedelta(days=(yesterday.weekday() - spec.weekday) % 7)
            done = await db.scalar(
                select(HouseholdRoutineCompletion.id).where(
                    HouseholdRoutineCompletion.routine_id == routine.id,
                    HouseholdRoutineCompletion.occurrence_date == latest,
                )
            )
            assert done is not None, f"{routine.title} is overdue on the showcase dashboard"


@pytest.mark.asyncio
async def test_ultimate_demo_adds_budget_and_driveway_on_genuine_ultimate_access(
    admin_client: AsyncClient,
    household_client: AsyncClient,
    admin_factory: Factory,
    demo_keys: list[str],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    created = await provision(
        admin_client,
        admin,
        demo_keys,
        fixture_type="ultimate_demo",
        showcase_reference_date=PINNED.isoformat(),
    )
    assert created["access"] == "ultimate"
    assert created["showcase_date_mode"] == "pinned"
    assert created["showcase_reference_date"] == PINNED.isoformat()
    counts = created["showcase_counts"]
    # The same Family base dataset...
    assert counts["meals"] == 20
    assert counts["lists"] == len(parker.LISTS)
    # ...plus Ultimate modules (and the vehicles' own reminders/events).
    assert counts["vehicles"] == 3
    assert counts["calendar_events"] == len(parker.EVENTS) + sum(
        1 for vehicle in parker.VEHICLES if vehicle.calendar_event
    )
    assert counts["reminders"] == len(parker.REMINDERS) + sum(
        len(vehicle.reminders) for vehicle in parker.VEHICLES
    )
    assert 90 <= counts["budget_transactions"] <= 120

    home_id = uuid.UUID(created["home_id"])
    async with SessionFactory() as db:
        assert await effective_plan(db, home_id) == SubscriptionPlan.ultimate
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        # No Stripe: complimentary access through the normal subscription row.
        assert subscription.provider == SubscriptionProvider.complimentary
        assert subscription.external_customer_id is None
        assert subscription.external_subscription_id is None

    await login_as_owner(household_client, created["account_email"])
    assert (await household_client.get(f"/api/v1/homes/{home_id}/budget")).status_code == 200
    listed = await household_client.get(f"/api/v1/homes/{home_id}/vehicles")
    assert listed.status_code == 200
    assert {row["model"] for row in listed.json()["items"]} == {"i4", "Tiguan", "Cooper"}


@pytest.mark.asyncio
async def test_template_catalogue_derives_modules_from_plan_entitlements(
    admin_client: AsyncClient, admin_factory: Factory
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    response = await admin_client.get("/api/v1/platform/demo-test-homes/templates")
    assert response.status_code == 200
    templates = {row["fixture_type"]: row for row in response.json()}
    assert list(templates) == ["apple_review", "demo", "ultimate_demo", "free_demo"]
    family_modules = {m["key"] for m in templates["demo"]["showcase_modules"]}
    ultimate_modules = {m["key"] for m in templates["ultimate_demo"]["showcase_modules"]}
    assert {"budget", "driveway"}.isdisjoint(family_modules)
    assert {"budget", "driveway"} <= ultimate_modules
    assert family_modules < ultimate_modules
    assert templates["apple_review"]["showcase"] is False
    assert templates["free_demo"]["access"] == "free"
    # Registry gating mirrors the plan definitions exactly.
    assert {m.key for m in modules_for_plan(SubscriptionPlan.family)} == family_modules


@pytest.mark.asyncio
async def test_showcase_options_are_rejected_for_non_showcase_templates(
    admin_client: AsyncClient, admin_factory: Factory, demo_keys: list[str]
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, admin)
    response = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/demo-test-homes",
        json={
            "fixture_key": "showcase-apple-options",
            "display_name": "Apple options",
            "fixture_type": "apple_review",
            "email": "showcase-apple-options@demo.mykhaya.app",
            "password": FIXTURE_PASSWORD,
            "populate_showcase": True,
        },
    )
    assert response.status_code == 422


# --- Household relationships ---------------------------------------------------------


@pytest.mark.asyncio
async def test_household_membership_and_credentials_follow_the_data_model(
    admin_client: AsyncClient, admin_factory: Factory, demo_keys: list[str]
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    created = await provision(admin_client, admin, demo_keys, fixture_type="demo")
    home_id = uuid.UUID(created["home_id"])
    async with SessionFactory() as db:
        rows = (
            await db.execute(
                select(Membership, User)
                .join(User, User.id == Membership.user_id)
                .where(Membership.group_id == home_id)
            )
        ).all()
        by_name = {user.display_name: (membership, user) for membership, user in rows}
        assert set(by_name) == {"Emma Parker", "James Parker", "Sophie Parker", "Oliver Parker"}
        emma, _ = by_name["Emma Parker"]
        assert emma.relationship == HouseholdRelationship.home_admin
        assert by_name["James Parker"][0].relationship == HouseholdRelationship.partner
        for child in ("Sophie Parker", "Oliver Parker"):
            membership, user = by_name[child]
            assert membership.relationship == HouseholdRelationship.child
            profile = await db.scalar(
                select(ChildProfile).where(ChildProfile.membership_id == membership.id)
            )
            assert profile is not None and profile.birthday_visible
            guardians = await db.scalar(
                select(func.count())
                .select_from(GuardianAssignment)
                .where(GuardianAssignment.child_profile_id == profile.id)
            )
            assert guardians == 2
            assert not profile.login_enabled  # no invented child sign-in
        # Only the primary demo account has credentials.
        identities = await db.scalar(
            select(func.count())
            .select_from(AuthIdentity)
            .where(AuthIdentity.user_id.in_([user.id for _, user in rows]))
        )
        assert identities == 1
        # Fixture members use reserved, undeliverable domains — never real inboxes.
        for membership, user in rows:
            if membership.relationship == HouseholdRelationship.child:
                assert user.email.endswith("@managed.mykhaya.invalid")
            elif user.display_name == "James Parker":
                assert user.email.endswith("@example.com")
            assert user.avatar_key is not None


# --- Budget --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_periods_and_transactions_are_consistent(
    admin_client: AsyncClient,
    household_client: AsyncClient,
    admin_factory: Factory,
    demo_keys: list[str],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    created = await provision(
        admin_client,
        admin,
        demo_keys,
        fixture_type="ultimate_demo",
        showcase_reference_date=PINNED.isoformat(),
    )
    home_id = created["home_id"]
    await login_as_owner(household_client, created["account_email"])

    async def month(year: int, number: int) -> dict[str, Any]:
        response = await household_client.get(
            f"/api/v1/homes/{home_id}/budget/months/{year}/{number}"
        )
        assert response.status_code == 200, response.text
        return response.json()

    previous, current, upcoming = await month(2026, 9), await month(2026, 10), await month(2026, 11)
    planned = {row["category_name"]: row["planned_amount"] for row in current["categories"]}
    assert planned == {spec.name: float(spec.planned) for spec in parker.BUDGET_CATEGORIES}
    assert sum(row["expected_amount"] for row in current["income"]) == 6100

    # Previous month: full history, every commitment paid, Groceries close to
    # its limit and a modest Eating Out overspend.
    prev = {row["category_name"]: row for row in previous["categories"]}
    assert all(
        item["payment_status"] == "paid"
        for row in previous["categories"]
        for item in row["items"]
        if item["item_type"] == "fixed"
    )
    groceries = prev["Groceries"]
    assert (
        0.85 * groceries["planned_amount"]
        <= groceries["actual_amount"]
        <= groceries["planned_amount"]
    )
    eating_out = prev["Eating Out"]
    assert (
        eating_out["planned_amount"]
        < eating_out["actual_amount"]
        <= 1.25 * eating_out["planned_amount"]
    )
    assert prev["Entertainment"]["actual_amount"] < 0.9 * prev["Entertainment"]["planned_amount"]
    assert all(row["received_amount"] == row["expected_amount"] for row in previous["income"])

    # Current month: activity up to the reference day only, upcoming
    # commitments still unpaid, payday still ahead.
    statuses = [
        item["payment_status"]
        for row in current["categories"]
        for item in row["items"]
        if item["item_type"] == "fixed"
    ]
    assert "paid" in statuses and "not_paid" in statuses
    assert all(row["received_amount"] == 0 for row in current["income"])

    # Next month: planned, nothing spent or paid yet.
    assert all(row["actual_amount"] == 0 for row in upcoming["categories"])
    assert len(upcoming["categories"]) == len(parker.BUDGET_CATEGORIES)

    entries = await household_client.get(f"/api/v1/homes/{home_id}/budget/entries")
    assert entries.status_code == 200
    assert all(date.fromisoformat(row["spent_on"]) <= PINNED for row in entries.json())


# --- Driveway ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_driveway_ownership_and_status_never_reach_government_services(
    admin_client: AsyncClient,
    household_client: AsyncClient,
    admin_factory: Factory,
    demo_keys: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def provider_must_not_be_called(*_: object) -> object:
        raise AssertionError("A showcase vehicle was sent to the MOT provider")

    async def provider_available(*_: object) -> bool:
        return True

    # Even with DVSA fully configured and enabled, showcase Homes refuse.
    monkeypatch.setattr(driveway_mot, "build_provider", provider_must_not_be_called)
    monkeypatch.setattr(driveway_mot, "mot_provider_available", provider_available)

    admin = await admin_factory(PlatformRole.owner)
    created = await provision(admin_client, admin, demo_keys, fixture_type="ultimate_demo")
    home_id = created["home_id"]
    await login_as_owner(household_client, created["account_email"])

    vehicles = (await household_client.get(f"/api/v1/homes/{home_id}/vehicles")).json()["items"]
    members = (await household_client.get(f"/api/v1/groups/{home_id}/members")).json()
    names = {row["user_id"]: row["display_name"] for row in members}
    owners = {row["model"]: names[row["owner_user_id"]] for row in vehicles}
    assert owners == {"i4": "Emma Parker", "Tiguan": "James Parker", "Cooper": "Emma Parker"}
    for vehicle in vehicles:
        # Fictional "Z" area registrations, locally-seeded status.
        assert vehicle["registration"].startswith("Z")
        mot = await household_client.get(f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}/mot")
        assert mot.status_code == 200
        assert mot.json()["provider_available"] is False
        assert mot.json()["summary"]["source"] is None
        refresh = await unsafe(
            household_client,
            "POST",
            f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}/mot/refresh",
            json={"mode": "force"},
        )
        assert refresh.status_code == 503
    tiguan = next(row for row in vehicles if row["model"] == "Tiguan")
    assert date.fromisoformat(tiguan["inspection_due_date"]) - date.today() < timedelta(days=30)
    lookup = await unsafe(
        household_client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/lookup",
        json={"registration": "ZM22 PKR", "country_code": "GB"},
    )
    assert lookup.status_code == 200
    assert lookup.json()["manual_entry_required"] is True


# --- Images --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seeded_images_load_through_the_real_media_endpoints(
    admin_client: AsyncClient,
    household_client: AsyncClient,
    admin_factory: Factory,
    demo_keys: list[str],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    created = await provision(admin_client, admin, demo_keys, fixture_type="ultimate_demo")
    home_id = created["home_id"]
    await login_as_owner(household_client, created["account_email"])

    meals = (await household_client.get(f"/api/v1/homes/{home_id}/meals")).json()["items"]
    assert all(meal["image_url"] for meal in meals)
    for meal in meals:
        image = await household_client.get(f"/api/v1{meal['image_url']}")
        assert image.status_code == 200, meal["name"]
        assert image.headers["content-type"] == "image/webp"
        assert len(image.content) > 2_000
    for vehicle in (await household_client.get(f"/api/v1/homes/{home_id}/vehicles")).json()[
        "items"
    ]:
        photo = await household_client.get(
            f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}/photo"
        )
        assert photo.status_code == 200
        assert photo.headers["content-type"] == "image/webp"
    for member in (await household_client.get(f"/api/v1/groups/{home_id}/members")).json():
        avatar = await household_client.get(f"/api/v1/users/{member['user_id']}/avatar")
        assert avatar.status_code == 200, member["display_name"]


# --- Repeatability, reset and protection ---------------------------------------------


@pytest.mark.asyncio
async def test_provisioning_is_repeatable_without_duplicates(
    admin_client: AsyncClient, admin_factory: Factory, demo_keys: list[str]
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    first = await provision(admin_client, admin, demo_keys, fixture_type="demo")
    second = await provision(admin_client, admin, demo_keys, fixture_type="demo")
    assert first["home_id"] != second["home_id"]
    assert first["showcase_counts"] == second["showcase_counts"]
    duplicate = await unsafe(
        admin_client,
        "POST",
        "/api/v1/platform/demo-test-homes",
        json={
            "fixture_key": first["fixture_key"],
            "display_name": "The Parker Family",
            "fixture_type": "demo",
            "email": "another-parker@demo.mykhaya.app",
            "password": FIXTURE_PASSWORD,
        },
    )
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_showcase_reset_restores_curated_state_and_keeps_identity(
    admin_client: AsyncClient,
    household_client: AsyncClient,
    admin_factory: Factory,
    demo_keys: list[str],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    created = await provision(admin_client, admin, demo_keys, fixture_type="ultimate_demo")
    home_id = created["home_id"]
    original = created["showcase_counts"]

    # A tester changes things.
    await login_as_owner(household_client, created["account_email"])
    meals = (await household_client.get(f"/api/v1/homes/{home_id}/meals")).json()["items"]
    removed = await unsafe(
        household_client, "DELETE", f"/api/v1/homes/{home_id}/meals/{meals[0]['id']}"
    )
    assert removed.status_code in (200, 204)
    added = await unsafe(
        household_client, "POST", f"/api/v1/homes/{home_id}/lists", json={"name": "Tester list"}
    )
    assert added.status_code == 201

    reset = await unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/demo-test-homes/{created['id']}/showcase-reset",
        json={
            "reference_date": PINNED.isoformat(),
            "reason": "Reset before screenshot capture",
            "confirmed": True,
        },
    )
    assert reset.status_code == 200, reset.text
    body = reset.json()
    assert body["home_id"] == home_id
    assert body["account_email"] == created["account_email"]
    assert body["showcase_date_mode"] == "pinned"
    assert body["showcase_reference_date"] == PINNED.isoformat()
    assert body["access"] == "ultimate"
    assert {k: v for k, v in body["showcase_counts"].items() if k != "budget_transactions"} == {
        k: v for k, v in original.items() if k != "budget_transactions"
    }

    # Credentials survive; the reseeded content is anchored to the pinned date.
    await login_as_owner(household_client, created["account_email"])
    start = datetime.combine(PINNED, datetime.min.time(), tzinfo=UTC)
    events = await household_client.get(
        f"/api/v1/homes/{home_id}/events",
        params={"start_at": start.isoformat(), "end_at": (start + timedelta(days=1)).isoformat()},
    )
    assert events.status_code == 200
    assert "Dentist appointment" in {row["title"] for row in events.json()["items"]}

    # A second identical reset is idempotent.
    again = await unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/demo-test-homes/{created['id']}/showcase-reset",
        json={
            "reference_date": PINNED.isoformat(),
            "reason": "Reset before screenshot capture",
            "confirmed": True,
        },
    )
    assert again.status_code == 200
    assert again.json()["showcase_counts"] == body["showcase_counts"]


@pytest.mark.asyncio
async def test_clean_showcase_home_has_plan_access_but_no_content(
    admin_client: AsyncClient, admin_factory: Factory, demo_keys: list[str]
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    created = await provision(
        admin_client, admin, demo_keys, fixture_type="ultimate_demo", populate_showcase=False
    )
    assert created["access"] == "ultimate"
    assert created["showcase_populated"] is False
    counts = created["showcase_counts"]
    assert counts["members"] == 1
    assert sum(value for key, value in counts.items() if key != "members") == 0
    reset = await unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/demo-test-homes/{created['id']}/showcase-reset",
        json={"reason": "Reset clean engineering Home", "confirmed": True},
    )
    assert reset.status_code == 200
    assert reset.json()["showcase_populated"] is False
    assert reset.json()["showcase_counts"] == counts


@pytest.mark.asyncio
async def test_reset_refuses_everything_that_is_not_a_showcase_home(
    admin_client: AsyncClient,
    household_client: AsyncClient,
    admin_factory: Factory,
    demo_keys: list[str],
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    apple = await provision(admin_client, admin, demo_keys, fixture_type="apple_review")
    free = await provision(admin_client, admin, demo_keys, fixture_type="free_demo")
    body = {"reason": "Attempted reset of a non-showcase Home", "confirmed": True}
    for fixture in (apple, free):
        refused = await unsafe(
            admin_client,
            "POST",
            f"/api/v1/platform/demo-test-homes/{fixture['id']}/showcase-reset",
            json=body,
        )
        assert refused.status_code == 409
    # An ordinary Home has no managed record, so neither its Home id nor any
    # other id resolves to something resettable.
    for unknown in (free["home_id"], str(uuid.uuid4())):
        missing = await unsafe(
            admin_client,
            "POST",
            f"/api/v1/platform/demo-test-homes/{unknown}/showcase-reset",
            json=body,
        )
        assert missing.status_code == 404
    # The household API offers no path to it either.
    await login_as_owner(household_client, free["account_email"])
    household_attempt = await unsafe(
        household_client,
        "POST",
        f"/api/v1/platform/demo-test-homes/{free['id']}/showcase-reset",
        json=body,
    )
    assert household_attempt.status_code in (401, 403, 404)


@pytest.mark.asyncio
async def test_support_role_cannot_reset_showcase_data(
    admin_client: AsyncClient, admin_factory: Factory, demo_keys: list[str]
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    created = await provision(admin_client, owner, demo_keys, fixture_type="demo")
    support = await admin_factory(PlatformRole.support)
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("172.16.0.4", 44300)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN, "X-Forwarded-For": "127.0.0.1"},
    ) as support_client:
        await admin_login(support_client, support)
        listed = await support_client.get("/api/v1/platform/demo-test-homes")
        assert listed.status_code == 200  # Support may view...
        response = await unsafe(
            support_client,
            "POST",
            f"/api/v1/platform/demo-test-homes/{created['id']}/showcase-reset",
            json={"reason": "Support attempting a reset", "confirmed": True},
        )
    assert response.status_code == 403  # ...but never reset.


@pytest.mark.asyncio
async def test_reset_and_create_are_audited(
    admin_client: AsyncClient, admin_factory: Factory, demo_keys: list[str]
) -> None:
    from mykhaya.models import AdministrativeAuditEvent

    admin = await admin_factory(PlatformRole.owner)
    created = await provision(admin_client, admin, demo_keys, fixture_type="demo")
    reset = await unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/demo-test-homes/{created['id']}/showcase-reset",
        json={"reason": "Audit coverage reset", "confirmed": True},
    )
    assert reset.status_code == 200
    async with SessionFactory() as db:
        actions = list(
            await db.scalars(
                select(AdministrativeAuditEvent.action).where(
                    AdministrativeAuditEvent.administrator_id == admin.id,
                    AdministrativeAuditEvent.target_id == uuid.UUID(created["id"]),
                )
            )
        )
        managed = await db.scalar(
            select(ManagedDemoHome).where(ManagedDemoHome.id == uuid.UUID(created["id"]))
        )
    assert "managed_demo.created" in actions
    assert "managed_demo.showcase_reset" in actions
    assert managed is not None and managed.refreshed_at is not None
