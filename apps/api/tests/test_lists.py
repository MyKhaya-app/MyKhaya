"""Household Lists V1: list/item CRUD, quantity/note/assignment, reorder,
clear-completed, rename concurrency, entitlement/capability gating and
cross-Home authorisation. See docs/architecture/lists.md and
mykhaya.routers.lists.

Meal Plans' own ingredients-to-list regression coverage lives in
test_meal_plans.py (test_add_meal_ingredients_to_list and friends) — this
file focuses on the Lists module itself.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

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
        db.add(FeatureOverride(feature_key=FeatureKey.shopping, group_id=home_id, enabled=True))
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        subscription.plan = plan
        await db.commit()
    return home_id


async def add_partner(client: AsyncClient, home_id: uuid.UUID, email: str, name: str) -> uuid.UUID:
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


async def create_list(
    client: AsyncClient, home_id: uuid.UUID, name: str = "Groceries", **overrides: object
):
    body = {"name": name, **overrides}
    response = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/lists", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Entitlement / feature gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_family_user_can_use_lists(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("family"), "Family User")
    home_id = await create_home(client, "Family Lists Home")
    created = await create_list(client, home_id)
    assert created["name"] == "Groceries"
    assert created["items"] == []


@pytest.mark.asyncio
async def test_free_user_cannot_use_lists(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("free"), "Free User")
    home_id = await create_home(client, "Free Lists Home", plan=SubscriptionPlan.free)

    create = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/lists", json={"name": "X"})
    assert create.status_code == 403
    assert create.json()["detail"]["code"] == "plan_feature_unavailable"
    assert create.json()["detail"]["entitlement"] == "lists.enabled"

    listed = await client.get(f"/api/v1/homes/{home_id}/lists")
    assert listed.status_code == 403


@pytest.mark.asyncio
async def test_lists_feature_off_returns_404_even_on_family(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("nofeature"), "No Feature User")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "No Feature Home"})
    home_id = uuid.UUID(group.json()["id"])
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()
    # No FeatureOverride for shopping was set — module isn't released here.
    response = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/lists", json={"name": "X"})
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# List CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_list_with_icon(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("icon"), "Icon User")
    home_id = await create_home(client, "Icon Home")
    created = await create_list(client, home_id, name="Packing", icon="packing")
    assert created["icon"] == "packing"


@pytest.mark.asyncio
async def test_create_list_rejects_unknown_icon(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("badicon"), "Bad Icon User")
    home_id = await create_home(client, "Bad Icon Home")
    response = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/lists", json={"name": "X", "icon": "spaceship"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_overview_reports_counts_without_icon_required(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("counts"), "Counts User")
    home_id = await create_home(client, "Counts Home")
    created = await create_list(client, home_id)
    list_id = created["id"]
    for text in ("Milk", "Bread", "Bananas"):
        await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/lists/{list_id}/items",
            json={"text": text},
        )
    items = (await client.get(f"/api/v1/homes/{home_id}/lists/{list_id}")).json()["items"]
    bread_id = next(row["id"] for row in items if row["text"] == "Bread")
    await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/lists/{list_id}/items/{bread_id}",
        json={"is_checked": True},
    )

    overview = await client.get(f"/api/v1/homes/{home_id}/lists")
    row = next(r for r in overview.json()["items"] if r["id"] == list_id)
    assert row["item_count"] == 3
    assert row["remaining_count"] == 2
    assert row["icon"] is None


@pytest.mark.asyncio
async def test_rename_list_requires_matching_expected_updated_at(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("rename"), "Rename User")
    home_id = await create_home(client, "Rename Home")
    created = await create_list(client, home_id)
    list_id = created["id"]

    stale = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/lists/{list_id}",
        json={
            "name": "Groceries 2",
            "expected_updated_at": "2000-01-01T00:00:00Z",
        },
    )
    assert stale.status_code == 409

    fresh = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/lists/{list_id}",
        json={"name": "Groceries 2", "expected_updated_at": created["updated_at"]},
    )
    assert fresh.status_code == 200
    assert fresh.json()["name"] == "Groceries 2"


@pytest.mark.asyncio
async def test_delete_list_soft_deletes_and_blocks_further_use(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("del"), "Delete User")
    home_id = await create_home(client, "Delete Home")
    created = await create_list(client, home_id)
    list_id = created["id"]

    deleted = await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/lists/{list_id}")
    assert deleted.status_code == 204

    after = await client.get(f"/api/v1/homes/{home_id}/lists/{list_id}")
    assert after.status_code == 404

    overview = await client.get(f"/api/v1/homes/{home_id}/lists")
    assert all(row["id"] != list_id for row in overview.json()["items"])

    add_item = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/lists/{list_id}/items",
        json={"text": "Too late"},
    )
    assert add_item.status_code == 404


@pytest.mark.asyncio
async def test_list_search_by_name(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("search"), "Search User")
    home_id = await create_home(client, "Search Home")
    await create_list(client, home_id, name="Groceries")
    await create_list(client, home_id, name="Holiday packing")

    result = await client.get(f"/api/v1/homes/{home_id}/lists", params={"q": "pack"})
    names = {row["name"] for row in result.json()["items"]}
    assert names == {"Holiday packing"}


# ---------------------------------------------------------------------------
# Item CRUD: quantity, note, assignment, completion metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_item_minimal_text_only(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("min"), "Minimal User")
    home_id = await create_home(client, "Minimal Home")
    created = await create_list(client, home_id)
    result = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/lists/{created['id']}/items",
        json={"text": "Milk"},
    )
    assert result.status_code == 201
    item = result.json()["items"][0]
    assert item["text"] == "Milk"
    assert item["quantity"] is None
    assert item["note"] is None
    assert item["assigned_member_id"] is None
    assert item["is_checked"] is False


@pytest.mark.asyncio
async def test_add_item_with_quantity_note_and_assignment(client: AsyncClient) -> None:
    owner_id = await create_verified_user(client, unique_email("full"), "Full User")
    home_id = await create_home(client, "Full Home")
    created = await create_list(client, home_id)
    result = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/lists/{created['id']}/items",
        json={
            "text": "AA batteries",
            "quantity": "4",
            "note": "For the remote",
            "assigned_member_id": str(owner_id),
        },
    )
    assert result.status_code == 201
    item = result.json()["items"][0]
    assert item["quantity"] == "4"
    assert item["note"] == "For the remote"
    assert item["assigned_member_id"] == str(owner_id)


@pytest.mark.asyncio
async def test_assigning_a_member_from_another_home_is_rejected(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("assign-a"), "Assign Home A")
    home_a = await create_home(client, "Assign Home A")
    created = await create_list(client, home_a)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        outsider_id = await create_verified_user(other_client, unique_email("assign-b"), "Outsider")
        await create_home(other_client, "Assign Home B")

    result = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_a}/lists/{created['id']}/items",
        json={"text": "Sneaky", "assigned_member_id": str(outsider_id)},
    )
    assert result.status_code == 422


@pytest.mark.asyncio
async def test_toggle_completion_records_actor_and_timestamp(client: AsyncClient) -> None:
    owner_id = await create_verified_user(client, unique_email("complete"), "Complete User")
    home_id = await create_home(client, "Complete Home")
    created = await create_list(client, home_id)
    added = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/lists/{created['id']}/items",
        json={"text": "Bread"},
    )
    item_id = added.json()["items"][0]["id"]

    checked = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/lists/{created['id']}/items/{item_id}",
        json={"is_checked": True},
    )
    row = checked.json()["items"][0]
    assert row["is_checked"] is True
    assert row["completed_by"] == str(owner_id)
    assert row["completed_at"] is not None

    unchecked = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/lists/{created['id']}/items/{item_id}",
        json={"is_checked": False},
    )
    row = unchecked.json()["items"][0]
    assert row["is_checked"] is False
    assert row["completed_by"] is None
    assert row["completed_at"] is None


@pytest.mark.asyncio
async def test_edit_item_only_touches_fields_present_in_the_request(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("partial"), "Partial User")
    home_id = await create_home(client, "Partial Home")
    created = await create_list(client, home_id)
    added = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/lists/{created['id']}/items",
        json={"text": "Milk", "quantity": "2", "note": "Semi-skimmed"},
    )
    item_id = added.json()["items"][0]["id"]

    # Only toggling is_checked — text/quantity/note must survive untouched.
    toggled = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/lists/{created['id']}/items/{item_id}",
        json={"is_checked": True},
    )
    row = toggled.json()["items"][0]
    assert row["text"] == "Milk"
    assert row["quantity"] == "2"
    assert row["note"] == "Semi-skimmed"

    # Explicitly clearing quantity (null) while leaving note untouched.
    edited = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/lists/{created['id']}/items/{item_id}",
        json={"quantity": None},
    )
    row = edited.json()["items"][0]
    assert row["quantity"] is None
    assert row["note"] == "Semi-skimmed"
    assert row["is_checked"] is True  # untouched by this call


@pytest.mark.asyncio
async def test_delete_item(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("delitem"), "Delete Item User")
    home_id = await create_home(client, "Delete Item Home")
    created = await create_list(client, home_id)
    added = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/lists/{created['id']}/items",
        json={"text": "Milk"},
    )
    item_id = added.json()["items"][0]["id"]
    removed = await unsafe(
        client,
        "DELETE",
        f"/api/v1/homes/{home_id}/lists/{created['id']}/items/{item_id}",
    )
    assert removed.status_code == 200
    assert removed.json()["items"] == []


@pytest.mark.asyncio
async def test_clear_completed_removes_only_checked_items(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("clear"), "Clear User")
    home_id = await create_home(client, "Clear Home")
    created = await create_list(client, home_id)
    list_id = created["id"]
    for text in ("Milk", "Bread", "Bananas"):
        await unsafe(
            client, "POST", f"/api/v1/homes/{home_id}/lists/{list_id}/items", json={"text": text}
        )
    detail = (await client.get(f"/api/v1/homes/{home_id}/lists/{list_id}")).json()
    bread_id = next(row["id"] for row in detail["items"] if row["text"] == "Bread")
    await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/lists/{list_id}/items/{bread_id}",
        json={"is_checked": True},
    )

    cleared = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/lists/{list_id}/items/clear-completed"
    )
    assert cleared.status_code == 200
    remaining_texts = {row["text"] for row in cleared.json()["items"]}
    assert remaining_texts == {"Milk", "Bananas"}


# ---------------------------------------------------------------------------
# Reordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reorder_items_persists_new_order(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("reorder"), "Reorder User")
    home_id = await create_home(client, "Reorder Home")
    created = await create_list(client, home_id)
    list_id = created["id"]
    ids = []
    for text in ("Milk", "Bread", "Bananas"):
        added = await unsafe(
            client, "POST", f"/api/v1/homes/{home_id}/lists/{list_id}/items", json={"text": text}
        )
        ids.append(added.json()["items"][-1]["id"])

    reversed_ids = list(reversed(ids))
    reordered = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/lists/{list_id}/items/reorder",
        json={"item_ids": reversed_ids},
    )
    assert reordered.status_code == 200
    assert [row["id"] for row in reordered.json()["items"]] == reversed_ids

    refetched = await client.get(f"/api/v1/homes/{home_id}/lists/{list_id}")
    assert [row["id"] for row in refetched.json()["items"]] == reversed_ids


@pytest.mark.asyncio
async def test_reorder_rejects_a_stale_or_mismatched_item_set(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("stale"), "Stale User")
    home_id = await create_home(client, "Stale Home")
    created = await create_list(client, home_id)
    list_id = created["id"]
    added = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/lists/{list_id}/items", json={"text": "Milk"}
    )
    real_id = added.json()["items"][0]["id"]

    missing_one = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/lists/{list_id}/items/reorder",
        json={"item_ids": [str(uuid.uuid4())]},
    )
    assert missing_one.status_code == 409

    # Sanity: the real id on its own is accepted.
    ok = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/lists/{list_id}/items/reorder",
        json={"item_ids": [real_id]},
    )
    assert ok.status_code == 200


# ---------------------------------------------------------------------------
# Cross-Home IDOR
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_home_list_and_item_operations_are_rejected(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("idor-a"), "IDOR Home A")
    home_a = await create_home(client, "IDOR Home A")
    created = await create_list(client, home_a)
    list_id = created["id"]
    added = await unsafe(
        client, "POST", f"/api/v1/homes/{home_a}/lists/{list_id}/items", json={"text": "Milk"}
    )
    item_id = added.json()["items"][0]["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        await create_verified_user(other_client, unique_email("idor-b"), "IDOR Home B")
        home_b = await create_home(other_client, "IDOR Home B")

        read = await other_client.get(f"/api/v1/homes/{home_b}/lists/{list_id}")
        assert read.status_code == 404
        assert (
            await unsafe(
                other_client,
                "PATCH",
                f"/api/v1/homes/{home_b}/lists/{list_id}",
                json={"name": "Hijacked", "expected_updated_at": created["updated_at"]},
            )
        ).status_code == 404
        assert (
            await unsafe(other_client, "DELETE", f"/api/v1/homes/{home_b}/lists/{list_id}")
        ).status_code == 404
        assert (
            await unsafe(
                other_client,
                "POST",
                f"/api/v1/homes/{home_b}/lists/{list_id}/items",
                json={"text": "Sneaky"},
            )
        ).status_code == 404
        assert (
            await unsafe(
                other_client,
                "PATCH",
                f"/api/v1/homes/{home_b}/lists/{list_id}/items/{item_id}",
                json={"is_checked": True},
            )
        ).status_code == 404
        assert (
            await unsafe(
                other_client,
                "DELETE",
                f"/api/v1/homes/{home_b}/lists/{list_id}/items/{item_id}",
            )
        ).status_code == 404


# ---------------------------------------------------------------------------
# Capability: standard_partner has full manage rights (documented V1 matrix)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_partner_has_full_manage_rights_matching_home_admin(client: AsyncClient) -> None:
    """Documents the V1 permission matrix: a standard_partner gets the same
    lists_manage capability as home_admin — create/rename/delete a List and
    add/edit/delete/check items all succeed for a Partner, not just the
    Home Admin who created the Home. See lists.py's module docstring."""
    await create_verified_user(client, unique_email("owner"), "Owner")
    home_id = await create_home(client, "Partner Rights Home")
    partner_email = unique_email("partner")
    partner_id = await add_partner(client, home_id, partner_email, "Partner")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as partner_client:
        login = await unsafe(
            partner_client,
            "POST",
            "/api/v1/auth/login",
            json={"email": partner_email, "password": PASSWORD},
        )
        assert login.status_code == 200
        assert uuid.UUID(login.json()["id"]) == partner_id

        created = await create_list(partner_client, home_id, name="Partner List")
        list_id = created["id"]
        added = await unsafe(
            partner_client,
            "POST",
            f"/api/v1/homes/{home_id}/lists/{list_id}/items",
            json={"text": "Milk"},
        )
        assert added.status_code == 201
        item_id = added.json()["items"][0]["id"]

        checked = await unsafe(
            partner_client,
            "PATCH",
            f"/api/v1/homes/{home_id}/lists/{list_id}/items/{item_id}",
            json={"is_checked": True},
        )
        assert checked.status_code == 200

        renamed = await unsafe(
            partner_client,
            "PATCH",
            f"/api/v1/homes/{home_id}/lists/{list_id}",
            json={"name": "Renamed by partner", "expected_updated_at": created["updated_at"]},
        )
        assert renamed.status_code == 200

        deleted = await unsafe(partner_client, "DELETE", f"/api/v1/homes/{home_id}/lists/{list_id}")
        assert deleted.status_code == 204
