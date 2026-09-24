"""Tests for Phase 4: Driveway -> Nudges reminder integration. Driveway never
builds a parallel reminder system — every assertion here is really about the
ordinary Reminder/TodoCategory rows (mykhaya.routers.reminders/todos) that
Driveway links to via the additive source_type/source_id/source_event
columns (mykhaya.driveway_reminders). Mirrors tests/test_reminders.py's
httpx + real-Postgres structure and helpers.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.db import SessionFactory
from mykhaya.driveway_reminders import (
    DRIVEWAY_SOURCE_TYPE,
    DrivewayReminderEventType,
    ensure_vehicles_category,
    upsert_driveway_reminder,
)
from mykhaya.entitlements import get_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    FeatureFlag,
    FeatureKey,
    FeatureOverride,
    Reminder,
    RoutineScope,
    SubscriptionPlan,
    TodoCategory,
    TokenPurpose,
    User,
    Vehicle,
)
from mykhaya.security import derived_token
from mykhaya.config import get_settings

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
    return user_id


async def create_driveway_home(client: AsyncClient, name: str = "Driveway Test Home") -> uuid.UUID:
    """A Home on the Ultimate plan with Driveway and Nudges both switched
    on — the minimum state either module's routes require."""
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert group.status_code == 201
    home_id = uuid.UUID(group.json()["id"])
    async with SessionFactory() as db:
        # Driveway's global platform FeatureFlag is disabled-by-default
        # (Phase 1.5) — a Home override alone can never re-enable a
        # platform-off feature (see mykhaya.features.is_feature_enabled),
        # so this suite explicitly opts the platform in, exactly as a PCC
        # operator promoting the module would, mirroring
        # test_calendar_sharing.py's identical pattern for external_sharing.
        for key in (FeatureKey.driveway, FeatureKey.nudges):
            flag = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == key))
            if flag is None:
                db.add(FeatureFlag(key=key, enabled=True))
            else:
                flag.enabled = True
        db.add(FeatureOverride(feature_key=FeatureKey.driveway, group_id=home_id, enabled=True))
        db.add(FeatureOverride(feature_key=FeatureKey.nudges, group_id=home_id, enabled=True))
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        subscription.plan = SubscriptionPlan.ultimate
        await db.commit()
    return home_id


async def create_vehicle(
    client: AsyncClient, home_id: uuid.UUID, *, scope: str = "household", nickname: str = "BMW i4"
) -> dict:
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles",
        json={"nickname": nickname, "scope": scope, "country_code": "GB", "registration": "AP22 OOJ"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def db_reminder(reminder_id: str) -> Reminder:
    async with SessionFactory() as db:
        row = await db.get(Reminder, uuid.UUID(reminder_id))
        assert row is not None
        return row


# --- Vehicles category -------------------------------------------------------


@pytest.mark.asyncio
async def test_vehicles_category_created_on_first_driveway_reminder(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("cat-first"), "Owner")
    home_id = await create_driveway_home(client)
    vehicle = await create_vehicle(client, home_id)
    today = datetime.now(UTC).date().isoformat()

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}/reminders",
        json={"title": "MOT due", "due_date": today},
    )
    assert created.status_code == 201, created.text
    assert created.json()["category"]["name"] == "Vehicles"

    categories = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/todo-categories")
    names = [row["name"] for row in categories.json()["items"]]
    assert names.count("Vehicles") == 1


@pytest.mark.asyncio
async def test_vehicles_category_reused_not_duplicated_on_second_reminder(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("cat-second"), "Owner")
    home_id = await create_driveway_home(client)
    vehicle = await create_vehicle(client, home_id)
    today = datetime.now(UTC).date().isoformat()

    first = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}/reminders",
        json={"title": "MOT due", "due_date": today},
    )
    second = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}/reminders",
        json={"title": "Insurance renewal", "due_date": today},
    )
    assert first.json()["category"]["id"] == second.json()["category"]["id"]

    async with SessionFactory() as db:
        rows = (
            await db.scalars(
                select(TodoCategory).where(TodoCategory.group_id == home_id, TodoCategory.name == "Vehicles")
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].managed_source == DRIVEWAY_SOURCE_TYPE


@pytest.mark.asyncio
async def test_vehicles_category_persists_after_last_managed_reminder_deleted(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("cat-persist"), "Owner")
    home_id = await create_driveway_home(client)
    vehicle = await create_vehicle(client, home_id)
    today = datetime.now(UTC).date().isoformat()

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}/reminders",
        json={"title": "MOT due", "due_date": today},
    )
    category_id = created.json()["category"]["id"]
    deleted = await unsafe(
        client, "DELETE", f"/api/v1/homes/{home_id}/reminders/{created.json()['id']}"
    )
    assert deleted.status_code == 204

    async with SessionFactory() as db:
        category = await db.get(TodoCategory, uuid.UUID(category_id))
        assert category is not None


@pytest.mark.asyncio
async def test_managed_category_deletion_blocked_while_in_use(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("cat-protect"), "Owner")
    home_id = await create_driveway_home(client)
    vehicle = await create_vehicle(client, home_id)
    today = datetime.now(UTC).date().isoformat()

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}/reminders",
        json={"title": "MOT due", "due_date": today},
    )
    category_id = created.json()["category"]["id"]
    blocked = await unsafe(
        client, "DELETE", f"/api/v1/homes/{home_id}/todo-categories/{category_id}"
    )
    assert blocked.status_code == 409

    await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/reminders/{created.json()['id']}")
    allowed = await unsafe(
        client, "DELETE", f"/api/v1/homes/{home_id}/todo-categories/{category_id}"
    )
    assert allowed.status_code == 204


# --- Create -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_personal_vehicle_creates_personal_reminder_with_source_metadata(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("personal-veh"), "Owner")
    home_id = await create_driveway_home(client)
    vehicle = await create_vehicle(client, home_id, scope="personal")
    today = datetime.now(UTC).date().isoformat()

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}/reminders",
        json={"title": "MOT due", "due_date": today},
    )
    assert created.status_code == 201, created.text
    assert created.json()["scope"] == "personal"
    assert created.json()["owner_user_id"] == vehicle["owner_user_id"]

    row = await db_reminder(created.json()["id"])
    assert row.source_type == DRIVEWAY_SOURCE_TYPE
    assert str(row.source_id) == vehicle["id"]
    assert row.source_event == DrivewayReminderEventType.manual.value


@pytest.mark.asyncio
async def test_household_vehicle_creates_household_reminder(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("household-veh"), "Owner")
    home_id = await create_driveway_home(client)
    vehicle = await create_vehicle(client, home_id, scope="household")
    today = datetime.now(UTC).date().isoformat()

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}/reminders",
        json={"title": "Insurance renewal", "due_date": today},
    )
    assert created.status_code == 201, created.text
    assert created.json()["scope"] == "household"
    assert created.json()["owner_user_id"] is None


@pytest.mark.asyncio
async def test_driveway_reminder_appears_in_existing_nudges_query(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("nudges-query"), "Owner")
    home_id = await create_driveway_home(client)
    vehicle = await create_vehicle(client, home_id, nickname="BMW i4")
    today = datetime.now(UTC).date().isoformat()

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}/reminders",
        json={"title": "BMW i4 MOT due", "due_date": today},
    )
    assert created.status_code == 201

    nudges = await unsafe(client, "GET", f"/api/v1/homes/{home_id}/reminders")
    assert nudges.status_code == 200
    titles = [row["title"] for row in nudges.json()["items"]]
    assert "BMW i4 MOT due" in titles
    matching = next(row for row in nudges.json()["items"] if row["title"] == "BMW i4 MOT due")
    assert matching["category"]["name"] == "Vehicles"


# --- Idempotency ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_does_not_duplicate_for_same_source_event() -> None:
    async with SessionFactory() as db:
        home_id, user_id, vehicle = await _seed_home_and_vehicle(db)
        due = date.today() + timedelta(days=30)
        first, created_first = await upsert_driveway_reminder(
            db,
            group_id=home_id,
            vehicle=vehicle,
            event_type=DrivewayReminderEventType.inspection,
            due_date=due,
            title="Inspection due",
            created_by=user_id,
        )
        await db.commit()
        second, created_second = await upsert_driveway_reminder(
            db,
            group_id=home_id,
            vehicle=vehicle,
            event_type=DrivewayReminderEventType.inspection,
            due_date=due,
            title="Inspection due",
            created_by=user_id,
        )
        await db.commit()
        assert created_first is True
        assert created_second is False
        assert first.id == second.id

        count = await db.scalar(
            select(Reminder).where(
                Reminder.source_type == DRIVEWAY_SOURCE_TYPE, Reminder.source_id == vehicle.id
            )
        )
        assert count is not None
        all_rows = (
            await db.scalars(
                select(Reminder).where(
                    Reminder.source_type == DRIVEWAY_SOURCE_TYPE, Reminder.source_id == vehicle.id
                )
            )
        ).all()
        assert len(all_rows) == 1


@pytest.mark.asyncio
async def test_upsert_updates_due_date_and_title() -> None:
    async with SessionFactory() as db:
        home_id, user_id, vehicle = await _seed_home_and_vehicle(db)
        first_due = date.today() + timedelta(days=30)
        second_due = date.today() + timedelta(days=60)
        reminder, _ = await upsert_driveway_reminder(
            db,
            group_id=home_id,
            vehicle=vehicle,
            event_type=DrivewayReminderEventType.registration,
            due_date=first_due,
            title="Registration renewal",
            created_by=user_id,
        )
        await db.commit()
        reminder_id = reminder.id
        updated, created_again = await upsert_driveway_reminder(
            db,
            group_id=home_id,
            vehicle=vehicle,
            event_type=DrivewayReminderEventType.registration,
            due_date=second_due,
            title="Registration renewal (updated)",
            created_by=user_id,
        )
        await db.commit()
        assert created_again is False
        assert updated.id == reminder_id
        assert updated.due_date == second_due
        assert updated.title == "Registration renewal (updated)"


@pytest.mark.asyncio
async def test_manual_event_type_always_creates_a_new_row() -> None:
    """Unlike structured events, 'manual' has no natural (vehicle, event)
    key — a vehicle may have any number of independent manual reminders."""
    async with SessionFactory() as db:
        home_id, user_id, vehicle = await _seed_home_and_vehicle(db)
        due = date.today() + timedelta(days=10)
        first, created_first = await upsert_driveway_reminder(
            db,
            group_id=home_id,
            vehicle=vehicle,
            event_type=DrivewayReminderEventType.manual,
            due_date=due,
            title="Tyre replacement",
            created_by=user_id,
        )
        await db.commit()
        second, created_second = await upsert_driveway_reminder(
            db,
            group_id=home_id,
            vehicle=vehicle,
            event_type=DrivewayReminderEventType.manual,
            due_date=due,
            title="Parking permit",
            created_by=user_id,
        )
        await db.commit()
        assert created_first is True
        assert created_second is True
        assert first.id != second.id


async def _seed_home_and_vehicle(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, Vehicle]:
    """Direct-DB fixture for the pure-helper tests above — avoids a second
    full HTTP registration/login/group-create round trip per test."""
    from mykhaya.ids import uuid7
    from mykhaya.models import Group

    user = User(email=f"seed-{uuid7()}@example.com", display_name="Seed Owner", is_active=True)
    db.add(user)
    await db.flush()
    group = Group(name="Seed Home", created_by=user.id)
    db.add(group)
    await db.flush()
    vehicle = Vehicle(
        group_id=group.id,
        owner_user_id=user.id,
        scope=RoutineScope.household,
        nickname="Seed Vehicle",
        country_code="GB",
    )
    db.add(vehicle)
    await db.flush()
    return group.id, user.id, vehicle


# --- Edit / delete --------------------------------------------------------------


@pytest.mark.asyncio
async def test_editing_via_generic_reminder_patch_keeps_source_metadata(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("edit-keeps"), "Owner")
    home_id = await create_driveway_home(client)
    vehicle = await create_vehicle(client, home_id)
    today = datetime.now(UTC).date().isoformat()

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}/reminders",
        json={"title": "MOT due", "due_date": today},
    )
    reminder_id = created.json()["id"]
    updated = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/reminders/{reminder_id}",
        json={
            "title": "MOT due (rescheduled)",
            "scope": "household",
            "due_date": today,
            "due_time": "10:00:00",
            "expected_updated_at": created.json()["updated_at"],
        },
    )
    assert updated.status_code == 200, updated.text

    row = await db_reminder(reminder_id)
    assert row.source_type == DRIVEWAY_SOURCE_TYPE
    assert str(row.source_id) == vehicle["id"]
    assert row.title == "MOT due (rescheduled)"


@pytest.mark.asyncio
async def test_deleting_from_nudges_removes_it_from_driveway(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("delete-nudges"), "Owner")
    home_id = await create_driveway_home(client)
    vehicle = await create_vehicle(client, home_id)
    today = datetime.now(UTC).date().isoformat()

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}/reminders",
        json={"title": "MOT due", "due_date": today},
    )
    reminder_id = created.json()["id"]
    deleted = await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/reminders/{reminder_id}")
    assert deleted.status_code == 204

    listing = await unsafe(
        client, "GET", f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}/reminders"
    )
    assert listing.json()["items"] == []


@pytest.mark.asyncio
async def test_deleting_vehicle_cleans_up_linked_managed_reminders(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("delete-veh"), "Owner")
    home_id = await create_driveway_home(client)
    vehicle = await create_vehicle(client, home_id)
    today = datetime.now(UTC).date().isoformat()

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}/reminders",
        json={"title": "MOT due", "due_date": today},
    )
    reminder_id = created.json()["id"]
    removed = await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}")
    assert removed.status_code == 204

    async with SessionFactory() as db:
        row = await db.get(Reminder, uuid.UUID(reminder_id))
        assert row is None


# --- Scope changes ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_vehicle_scope_change_updates_linked_managed_reminder_scope(
    client: AsyncClient,
) -> None:
    user_id = await create_verified_user(client, unique_email("scope-change"), "Owner")
    home_id = await create_driveway_home(client)
    vehicle = await create_vehicle(client, home_id, scope="personal")
    today = datetime.now(UTC).date().isoformat()

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}/reminders",
        json={"title": "MOT due", "due_date": today},
    )
    reminder_id = created.json()["id"]

    changed = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}",
        json={
            "nickname": vehicle["nickname"],
            "scope": "household",
            "country_code": "GB",
            "registration": vehicle["registration"],
            "expected_updated_at": vehicle["updated_at"],
        },
    )
    assert changed.status_code == 200, changed.text

    row = await db_reminder(reminder_id)
    assert row.scope == RoutineScope.household
    assert row.owner_user_id is None


@pytest.mark.asyncio
async def test_unrelated_standalone_reminder_unaffected_by_vehicle_scope_change(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("scope-unrelated"), "Owner")
    home_id = await create_driveway_home(client)
    vehicle = await create_vehicle(client, home_id, scope="personal")
    today = datetime.now(UTC).date().isoformat()

    standalone = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/reminders",
        json={"title": "Unrelated", "due_date": today, "due_time": "09:00:00", "scope": "personal"},
    )
    assert standalone.status_code == 201

    await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}",
        json={
            "nickname": vehicle["nickname"],
            "scope": "household",
            "country_code": "GB",
            "registration": vehicle["registration"],
            "expected_updated_at": vehicle["updated_at"],
        },
    )

    row = await db_reminder(standalone.json()["id"])
    assert row.scope == RoutineScope.personal


# --- Permissions -------------------------------------------------------------


@pytest.mark.asyncio
async def test_unrelated_home_cannot_access_reminders_through_driveway_route(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("cross-home-a"), "Owner A")
    home_id = await create_driveway_home(client, "Home A")
    vehicle = await create_vehicle(client, home_id)

    await create_verified_user(client, unique_email("cross-home-b"), "Owner B")
    other_home_id = await create_driveway_home(client, "Home B")

    response = await unsafe(
        client, "GET", f"/api/v1/homes/{other_home_id}/vehicles/{vehicle['id']}/reminders"
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_non_owner_cannot_access_personal_vehicle_reminders(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("owner-x"), "Owner")
    home_id = await create_driveway_home(client)
    vehicle = await create_vehicle(client, home_id, scope="personal")
    today = datetime.now(UTC).date().isoformat()
    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}/reminders",
        json={"title": "MOT due", "due_date": today},
    )
    assert created.status_code == 201

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        from mykhaya.models import HouseholdRelationship, Membership, PermissionProfile, Role

        other_id = await create_verified_user(other_client, unique_email("partner-x"), "Partner")
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

        listing = await unsafe(
            other_client, "GET", f"/api/v1/homes/{home_id}/vehicles/{vehicle['id']}/reminders"
        )
        assert listing.status_code == 404
