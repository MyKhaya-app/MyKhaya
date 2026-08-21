"""Wishlists V1: wishlist/item CRUD, entitlement/capability gating,
owner-vs-viewer serialization, MyKhaya-to-MyKhaya sharing, and cross-Home
IDOR. See mykhaya.routers.wishlists. Guest link+PIN sharing has its own
coverage in test_wishlist_guest_sharing.py.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
        db.add(FeatureOverride(feature_key=FeatureKey.wish_lists, group_id=home_id, enabled=True))
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


@asynccontextmanager
async def login_as(email: str) -> AsyncIterator[AsyncClient]:
    # An async context manager (not a plain "create + login + return") —
    # httpx.AsyncClient implicitly transitions UNOPENED -> OPENED on its
    # first request, so logging in *before* the caller's own `async with`
    # entered the client would make that later `__aenter__` raise "Cannot
    # open a client instance more than once."
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other:
        login = await unsafe(
            other, "POST", "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        )
        assert login.status_code == 200
        yield other


async def create_wishlist(client: AsyncClient, home_id: uuid.UUID, **overrides: object):
    body = {"title": "Birthday List", "occasion": "birthday", **overrides}
    response = await unsafe(client, "POST", f"/api/v1/homes/{home_id}/wishlists", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def add_item(client: AsyncClient, home_id: uuid.UUID, wishlist_id: str, **overrides: object):
    body = {"name": "Lego Set", **overrides}
    response = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/wishlists/{wishlist_id}/items", json=body
    )
    assert response.status_code == 201, response.text
    return response.json()


async def set_home_visible(
    client: AsyncClient, home_id: uuid.UUID, wishlist_id: str, enabled: bool = True
):
    """Wishlists default to Private (home_visible=False) — see
    models.Wishlist.home_visible. Tests that exercise "any Home member with
    wishlists_view can see this wishlist" now have to opt in explicitly,
    same as a real owner would."""
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists/{wishlist_id}/home-visibility",
        json={"enabled": enabled},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Entitlement / feature gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_family_user_can_use_wishlists(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("family"), "Family User")
    home_id = await create_home(client, "Family Wishlist Home")
    created = await create_wishlist(client, home_id)
    assert created["title"] == "Birthday List"
    assert created["items"] == []


@pytest.mark.asyncio
async def test_free_user_cannot_use_wishlists(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("free"), "Free User")
    home_id = await create_home(client, "Free Wishlist Home", plan=SubscriptionPlan.free)
    create = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists",
        json={"title": "X", "occasion": "general"},
    )
    assert create.status_code == 403
    assert create.json()["detail"]["code"] == "plan_feature_unavailable"
    assert create.json()["detail"]["entitlement"] == "wishlists.enabled"


@pytest.mark.asyncio
async def test_wishlists_feature_off_returns_404_even_on_family(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("nofeature"), "No Feature User")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "No Feature Home"})
    home_id = uuid.UUID(group.json()["id"])
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()
    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists",
        json={"title": "X", "occasion": "general"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Wishlist / item CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_update_delete_wishlist(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("crud"), "CRUD User")
    home_id = await create_home(client, "CRUD Home")
    created = await create_wishlist(client, home_id)
    wishlist_id = created["id"]

    updated = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/wishlists/{wishlist_id}",
        json={
            "title": "Updated Title",
            "occasion": "christmas",
            "expected_updated_at": created["updated_at"],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "Updated Title"

    deleted = await unsafe(client, "DELETE", f"/api/v1/homes/{home_id}/wishlists/{wishlist_id}")
    assert deleted.status_code == 204
    gone = await client.get(f"/api/v1/homes/{home_id}/wishlists/{wishlist_id}")
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_update_rejects_stale_expected_updated_at(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("stale"), "Stale User")
    home_id = await create_home(client, "Stale Home")
    created = await create_wishlist(client, home_id)
    response = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/wishlists/{created['id']}",
        json={
            "title": "Race",
            "occasion": "general",
            "expected_updated_at": "2000-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_item_crud_and_reorder(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("items"), "Items User")
    home_id = await create_home(client, "Items Home")
    wishlist = await create_wishlist(client, home_id)
    wishlist_id = wishlist["id"]
    first = await add_item(client, home_id, wishlist_id, name="Book")
    item1_id = first["items"][0]["id"]
    second = await add_item(client, home_id, wishlist_id, name="Puzzle")
    item2_id = next(i["id"] for i in second["items"] if i["name"] == "Puzzle")

    edited = await unsafe(
        client,
        "PATCH",
        f"/api/v1/homes/{home_id}/wishlists/{wishlist_id}/items/{item1_id}",
        json={"quantity": 3},
    )
    assert edited.status_code == 200
    item1 = next(i for i in edited.json()["items"] if i["id"] == item1_id)
    assert item1["quantity"] == 3
    assert "reservation_status" not in item1

    reordered = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists/{wishlist_id}/items/reorder",
        json={"item_ids": [item2_id, item1_id]},
    )
    assert reordered.status_code == 200
    assert [i["id"] for i in reordered.json()["items"]] == [item2_id, item1_id]

    deleted = await unsafe(
        client, "DELETE", f"/api/v1/homes/{home_id}/wishlists/{wishlist_id}/items/{item1_id}"
    )
    assert deleted.status_code == 200
    assert len(deleted.json()["items"]) == 1


# ---------------------------------------------------------------------------
# Household access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_partner_can_view_but_not_edit_owners_wishlist(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("owner1"), "Owner")
    home_id = await create_home(client, "Shared Home")
    wishlist = await create_wishlist(client, home_id)
    partner_email = unique_email("partner1")
    await add_partner(client, home_id, partner_email, "Partner")
    # Private by default — a same-Home member needs the owner to opt into
    # Home visibility (or a personal share) before wishlists_view alone is
    # enough to see this wishlist.
    await set_home_visible(client, home_id, wishlist["id"])

    async with SessionFactory() as db:
        membership = await db.scalar(
            select(Membership).where(
                Membership.group_id == home_id,
                Membership.relationship == HouseholdRelationship.partner,
            )
        )
        assert membership is not None
        # Downgrade the partner to remove wishlists_manage so we can prove
        # they can view (wishlists_view) without being able to edit.
        membership.permission_overrides = {"wishlists.manage": False}
        await db.commit()

    async with login_as(partner_email) as partner_client:
        seen = await partner_client.get(f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}")
        assert seen.status_code == 200
        assert "owner_display_name" in seen.json()  # viewer shape, not owner shape

        blocked = await unsafe(
            partner_client,
            "PATCH",
            f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}",
            json={
                "title": "Hijack",
                "occasion": "general",
                "expected_updated_at": wishlist["updated_at"],
            },
        )
        assert blocked.status_code == 403


@pytest.mark.asyncio
async def test_partner_can_create_and_manage_own_wishlist(client: AsyncClient) -> None:
    """A standard_partner has wishlists_manage, but that alone must not let
    them edit someone ELSE's wishlist — the owner-or-admin check is the
    deviation from Lists/Meals' shared-structure model."""
    await create_verified_user(client, unique_email("owner2"), "Owner")
    home_id = await create_home(client, "Owner Only Home")
    owners_wishlist = await create_wishlist(client, home_id)
    partner_email = unique_email("partner2")
    await add_partner(client, home_id, partner_email, "Partner")

    async with login_as(partner_email) as partner_client:
        blocked = await unsafe(
            partner_client,
            "PATCH",
            f"/api/v1/homes/{home_id}/wishlists/{owners_wishlist['id']}",
            json={
                "title": "Hijack",
                "occasion": "general",
                "expected_updated_at": owners_wishlist["updated_at"],
            },
        )
        assert blocked.status_code == 403

        own = await create_wishlist(partner_client, home_id, title="Partner's List")
        assert own["title"] == "Partner's List"


# ---------------------------------------------------------------------------
# Reservation privacy — the core non-negotiable rule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_owner_never_sees_reservation_data_even_after_a_reservation(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("privacyowner"), "Privacy Owner")
    home_id = await create_home(client, "Privacy Home")
    wishlist = await create_wishlist(client, home_id)
    added = await add_item(client, home_id, wishlist["id"], name="Secret Gift")
    item_id = added["items"][0]["id"]

    partner_email = unique_email("privacypartner")
    await add_partner(client, home_id, partner_email, "Reserving Partner")
    # Home-visible this time (as opposed to the guest-sharing equivalent
    # test) — reservation privacy must hold regardless of how the reserver
    # reached the wishlist.
    await set_home_visible(client, home_id, wishlist["id"])

    async with login_as(partner_email) as partner_client:
        reserved = await unsafe(
            partner_client,
            "POST",
            f"/api/v1/wishlists/{wishlist['id']}/items/{item_id}/reserve",
            json={"buyer_display_name": "Auntie Sue"},
        )
        assert reserved.status_code == 200, reserved.text
        assert reserved.json()["reservation_status"] == "reserved"
        assert reserved.json()["reserved_by_display_name"] == "Auntie Sue"

    owner_view = await client.get(f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}")
    assert owner_view.status_code == 200
    payload = owner_view.json()
    owner_item = next(i for i in payload["items"] if i["id"] == item_id)
    # The load-bearing assertion: inspect the actual serialized keys, not
    # just their values — a "reservation_status": null would already be a
    # leak (it tells the owner a reservation slot exists at all).
    assert "reservation_status" not in owner_item
    assert "reserved_by_display_name" not in owner_item
    assert set(owner_item.keys()) == {
        "id", "name", "url", "price", "currency", "note", "image_url",
        "quantity", "sort_order", "created_at", "updated_at",
    }
    # No aggregate leak either (no reservation-shaped key anywhere, at any
    # nesting level, in the owner's response).
    assert "reservation" not in payload
    assert not any("reservation" in item for item in payload["items"])


@pytest.mark.asyncio
async def test_owner_cannot_reserve_own_item(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("selfowner"), "Self Owner")
    home_id = await create_home(client, "Self Reserve Home")
    wishlist = await create_wishlist(client, home_id)
    added = await add_item(client, home_id, wishlist["id"])
    item_id = added["items"][0]["id"]

    response = await unsafe(
        client, "POST", f"/api/v1/wishlists/{wishlist['id']}/items/{item_id}/reserve", json={}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reserving_already_reserved_item_does_not_leak_reserver(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("raceowner"), "Race Owner")
    home_id = await create_home(client, "Race Home")
    wishlist = await create_wishlist(client, home_id)
    added = await add_item(client, home_id, wishlist["id"])
    item_id = added["items"][0]["id"]

    first_email = unique_email("racefirst")
    await add_partner(client, home_id, first_email, "First Reserver")
    second_email = unique_email("racesecond")
    await add_partner(client, home_id, second_email, "Second Reserver")
    await set_home_visible(client, home_id, wishlist["id"])

    async with login_as(first_email) as first_client:
        first = await unsafe(
            first_client,
            "POST",
            f"/api/v1/wishlists/{wishlist['id']}/items/{item_id}/reserve",
            json={"buyer_display_name": "First Reserver"},
        )
        assert first.status_code == 200

    async with login_as(second_email) as second_client:
        second = await unsafe(
            second_client,
            "POST",
            f"/api/v1/wishlists/{wishlist['id']}/items/{item_id}/reserve",
            json={"buyer_display_name": "Second Reserver"},
        )
        assert second.status_code == 409
        assert "First Reserver" not in second.text


@pytest.mark.asyncio
async def test_release_only_by_original_reserver(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("relowner"), "Release Owner")
    home_id = await create_home(client, "Release Home")
    wishlist = await create_wishlist(client, home_id)
    added = await add_item(client, home_id, wishlist["id"])
    item_id = added["items"][0]["id"]

    reserver_email = unique_email("relreserver")
    await add_partner(client, home_id, reserver_email, "Reserver")
    bystander_email = unique_email("relbystander")
    await add_partner(client, home_id, bystander_email, "Bystander")
    await set_home_visible(client, home_id, wishlist["id"])

    async with login_as(reserver_email) as reserver_client:
        reserved = await unsafe(
            reserver_client,
            "POST",
            f"/api/v1/wishlists/{wishlist['id']}/items/{item_id}/reserve",
            json={},
        )
        assert reserved.status_code == 200

    async with login_as(bystander_email) as bystander_client:
        blocked = await unsafe(
            bystander_client,
            "POST",
            f"/api/v1/wishlists/{wishlist['id']}/items/{item_id}/release",
            json={},
        )
        assert blocked.status_code == 403

    async with login_as(reserver_email) as reserver_client:
        released = await unsafe(
            reserver_client,
            "POST",
            f"/api/v1/wishlists/{wishlist['id']}/items/{item_id}/release",
            json={},
        )
        assert released.status_code == 200
        assert released.json()["reservation_status"] == "available"


# ---------------------------------------------------------------------------
# MyKhaya-to-MyKhaya sharing (cross-Home)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_home_share_grants_only_that_one_wishlist(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("sharer"), "Sharer")
    home_id = await create_home(client, "Sharer Home")
    wishlist = await create_wishlist(client, home_id)
    other_wishlist = await create_wishlist(client, home_id, title="Not Shared")

    recipient_email = unique_email("recipient")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as recipient_client:
        recipient_id = await create_verified_user(recipient_client, recipient_email, "Recipient")
        recipient_home_id = await create_home(recipient_client, "Recipient's Own Home")

    lookup = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}/shares/lookup",
        json={"email": recipient_email},
    )
    assert lookup.status_code == 200
    assert lookup.json()["existing_user_id"] == str(recipient_id)

    share = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}/shares",
        json={
            "recipient_name": "Recipient",
            "recipient_email": recipient_email,
            "share_type": "mykhaya_user",
            "confirmed_user_id": str(recipient_id),
        },
    )
    assert share.status_code == 201, share.text
    share_id = share.json()["id"]

    async with login_as(recipient_email) as recipient_client:
        listed = await recipient_client.get("/api/v1/wishlists/shared-with-me")
        assert listed.status_code == 200
        ids = {item["id"] for item in listed.json()["items"]}
        assert wishlist["id"] in ids
        assert other_wishlist["id"] not in ids

        detail = await recipient_client.get(f"/api/v1/wishlists/{wishlist['id']}")
        assert detail.status_code == 200
        assert "reservation_status" not in str(detail.json())  # no items yet, trivially true

        # Never gains any visibility into the sharer's OTHER wishlists or
        # Home members via this share.
        other_detail = await recipient_client.get(f"/api/v1/wishlists/{other_wishlist['id']}")
        assert other_detail.status_code == 404
        home_members = await recipient_client.get(f"/api/v1/homes/{home_id}/wishlists")
        assert home_members.status_code == 404

        # Their own Home's own data is unaffected.
        own_home = await recipient_client.get(f"/api/v1/homes/{recipient_home_id}/wishlists")
        assert own_home.status_code == 200

    # Revoke, then confirm access is gone.
    revoke = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}/shares/{share_id}/revoke"
    )
    assert revoke.status_code == 204

    async with login_as(recipient_email) as recipient_client:
        after_revoke = await recipient_client.get(f"/api/v1/wishlists/{wishlist['id']}")
        assert after_revoke.status_code == 404
        listed_after = await recipient_client.get("/api/v1/wishlists/shared-with-me")
        assert listed_after.json()["items"] == []


@pytest.mark.asyncio
async def test_revoking_one_share_leaves_a_sibling_share_functional(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("multisharer"), "Multi Sharer")
    home_id = await create_home(client, "Multi Share Home")
    wishlist = await create_wishlist(client, home_id)

    emails = [unique_email("recip-a"), unique_email("recip-b")]
    ids = []
    for email in emails:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
        ) as c:
            ids.append(await create_verified_user(c, email, "Recip"))

    share_ids = []
    for email, uid in zip(emails, ids, strict=True):
        share = await unsafe(
            client,
            "POST",
            f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}/shares",
            json={
                "recipient_name": "Recip",
                "recipient_email": email,
                "share_type": "mykhaya_user",
                "confirmed_user_id": str(uid),
            },
        )
        assert share.status_code == 201
        share_ids.append(share.json()["id"])

    await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}/shares/{share_ids[0]}/revoke",
    )

    async with login_as(emails[0]) as revoked_client:
        blocked = await revoked_client.get(f"/api/v1/wishlists/{wishlist['id']}")
        assert blocked.status_code == 404

    async with login_as(emails[1]) as still_ok_client:
        ok = await still_ok_client.get(f"/api/v1/wishlists/{wishlist['id']}")
        assert ok.status_code == 200


# ---------------------------------------------------------------------------
# Cross-Home IDOR
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_home_wishlist_and_item_operations_are_rejected(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("idor-a"), "IDOR Home A")
    home_a = await create_home(client, "IDOR Home A")
    wishlist = await create_wishlist(client, home_a)
    added = await add_item(client, home_a, wishlist["id"])
    item_id = added["items"][0]["id"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        await create_verified_user(other_client, unique_email("idor-b"), "IDOR Home B")
        home_b = await create_home(other_client, "IDOR Home B")

        assert (
            await other_client.get(f"/api/v1/homes/{home_b}/wishlists/{wishlist['id']}")
        ).status_code == 404
        assert (
            await unsafe(
                other_client,
                "PATCH",
                f"/api/v1/homes/{home_b}/wishlists/{wishlist['id']}",
                json={
                    "title": "Hijacked",
                    "occasion": "general",
                    "expected_updated_at": wishlist["updated_at"],
                },
            )
        ).status_code == 404
        assert (
            await unsafe(other_client, "DELETE", f"/api/v1/homes/{home_b}/wishlists/{wishlist['id']}")
        ).status_code == 404
        assert (
            await unsafe(
                other_client,
                "POST",
                f"/api/v1/homes/{home_b}/wishlists/{wishlist['id']}/items",
                json={"name": "Sneaky"},
            )
        ).status_code == 404
        # No membership and no share -> the top-level view/reserve endpoints
        # 404 too, not just the Home-scoped ones.
        assert (
            await other_client.get(f"/api/v1/wishlists/{wishlist['id']}")
        ).status_code == 404
        assert (
            await unsafe(
                other_client,
                "POST",
                f"/api/v1/wishlists/{wishlist['id']}/items/{item_id}/reserve",
                json={},
            )
        ).status_code == 404


# ---------------------------------------------------------------------------
# Home visibility model — private by default, opt-in per wishlist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_wishlist_defaults_to_private(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("visdefault"), "Vis Default")
    home_id = await create_home(client, "Vis Default Home")
    wishlist = await create_wishlist(client, home_id)
    assert wishlist["home_visible"] is False
    assert wishlist["share_count"] == 0


@pytest.mark.asyncio
async def test_home_member_without_share_cannot_see_private_wishlist(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("visowner1"), "Vis Owner 1")
    home_id = await create_home(client, "Vis Private Home")
    wishlist = await create_wishlist(client, home_id)
    partner_email = unique_email("vispartner1")
    await add_partner(client, home_id, partner_email, "Vis Partner 1")

    async with login_as(partner_email) as partner_client:
        home_scoped = await partner_client.get(
            f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}"
        )
        assert home_scoped.status_code == 404
        top_level = await partner_client.get(f"/api/v1/wishlists/{wishlist['id']}")
        assert top_level.status_code == 404
        # And the Home-scoped list must not surface it either.
        listed = await partner_client.get(f"/api/v1/homes/{home_id}/wishlists")
        assert listed.status_code == 200
        assert wishlist["id"] not in {item["id"] for item in listed.json()["items"]}


@pytest.mark.asyncio
async def test_owner_always_sees_own_wishlist_regardless_of_visibility(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("visowner2"), "Vis Owner 2")
    home_id = await create_home(client, "Vis Owner Sees Own Home")
    wishlist = await create_wishlist(client, home_id)
    assert wishlist["home_visible"] is False

    private_view = await client.get(f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}")
    assert private_view.status_code == 200

    await set_home_visible(client, home_id, wishlist["id"])
    visible_view = await client.get(f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}")
    assert visible_view.status_code == 200


@pytest.mark.asyncio
async def test_toggling_home_visibility_grants_and_revokes_member_access(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("visowner3"), "Vis Owner 3")
    home_id = await create_home(client, "Vis Toggle Home")
    wishlist = await create_wishlist(client, home_id)
    partner_email = unique_email("vispartner3")
    await add_partner(client, home_id, partner_email, "Vis Partner 3")

    async with login_as(partner_email) as partner_client:
        before = await partner_client.get(f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}")
        assert before.status_code == 404

    enabled = await set_home_visible(client, home_id, wishlist["id"], enabled=True)
    assert enabled["home_visible"] is True

    async with login_as(partner_email) as partner_client:
        during = await partner_client.get(f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}")
        assert during.status_code == 200
        also_top_level = await partner_client.get(f"/api/v1/wishlists/{wishlist['id']}")
        assert also_top_level.status_code == 200
        also_listed = await partner_client.get(f"/api/v1/homes/{home_id}/wishlists")
        assert wishlist["id"] in {item["id"] for item in also_listed.json()["items"]}

    disabled = await set_home_visible(client, home_id, wishlist["id"], enabled=False)
    assert disabled["home_visible"] is False

    async with login_as(partner_email) as partner_client:
        after = await partner_client.get(f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}")
        assert after.status_code == 404


@pytest.mark.asyncio
async def test_individual_share_works_independently_of_home_visibility(client: AsyncClient) -> None:
    """A per-recipient share must keep working when home_visible is False —
    and must not itself flip home_visible on."""
    await create_verified_user(client, unique_email("visowner4"), "Vis Owner 4")
    home_id = await create_home(client, "Vis Share Home")
    wishlist = await create_wishlist(client, home_id)
    assert wishlist["home_visible"] is False

    recipient_email = unique_email("visrecipient4")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as recipient_client:
        recipient_id = await create_verified_user(recipient_client, recipient_email, "Vis Recipient 4")

    share = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}/shares",
        json={
            "recipient_name": "Vis Recipient 4",
            "recipient_email": recipient_email,
            "share_type": "mykhaya_user",
            "confirmed_user_id": str(recipient_id),
        },
    )
    assert share.status_code == 201, share.text
    share_id = share.json()["id"]

    async with login_as(recipient_email) as recipient_client:
        detail = await recipient_client.get(f"/api/v1/wishlists/{wishlist['id']}")
        assert detail.status_code == 200

    # The share creation itself must not have flipped home_visible.
    owner_view = await client.get(f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}")
    assert owner_view.json()["home_visible"] is False
    assert owner_view.json()["share_count"] == 1

    # Revoking the share must not affect home_visible either way.
    revoke = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}/shares/{share_id}/revoke",
    )
    assert revoke.status_code == 204
    after_revoke = await client.get(f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}")
    assert after_revoke.json()["home_visible"] is False
    assert after_revoke.json()["share_count"] == 0

    async with login_as(recipient_email) as recipient_client:
        gone = await recipient_client.get(f"/api/v1/wishlists/{wishlist['id']}")
        assert gone.status_code == 404


@pytest.mark.asyncio
async def test_toggling_home_visibility_does_not_revoke_shares(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("visowner5"), "Vis Owner 5")
    home_id = await create_home(client, "Vis Toggle No Revoke Home")
    wishlist = await create_wishlist(client, home_id)

    recipient_email = unique_email("visrecipient5")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as recipient_client:
        recipient_id = await create_verified_user(recipient_client, recipient_email, "Vis Recipient 5")

    share = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}/shares",
        json={
            "recipient_name": "Vis Recipient 5",
            "recipient_email": recipient_email,
            "share_type": "mykhaya_user",
            "confirmed_user_id": str(recipient_id),
        },
    )
    assert share.status_code == 201

    await set_home_visible(client, home_id, wishlist["id"], enabled=True)
    await set_home_visible(client, home_id, wishlist["id"], enabled=False)

    async with login_as(recipient_email) as recipient_client:
        still_ok = await recipient_client.get(f"/api/v1/wishlists/{wishlist['id']}")
        assert still_ok.status_code == 200


@pytest.mark.asyncio
async def test_cross_home_share_unaffected_by_home_visibility_either_state(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("visowner6"), "Vis Owner 6")
    home_id = await create_home(client, "Vis Cross Home")
    wishlist = await create_wishlist(client, home_id)

    recipient_email = unique_email("visrecipient6")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as recipient_client:
        recipient_id = await create_verified_user(recipient_client, recipient_email, "Vis Recipient 6")
        await create_home(recipient_client, "Vis Recipient's Own Home")

    share = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}/shares",
        json={
            "recipient_name": "Vis Recipient 6",
            "recipient_email": recipient_email,
            "share_type": "mykhaya_user",
            "confirmed_user_id": str(recipient_id),
        },
    )
    assert share.status_code == 201

    for enabled in (False, True, False):
        await set_home_visible(client, home_id, wishlist["id"], enabled=enabled)
        async with login_as(recipient_email) as recipient_client:
            listed = await recipient_client.get("/api/v1/wishlists/shared-with-me")
            assert wishlist["id"] in {item["id"] for item in listed.json()["items"]}


@pytest.mark.asyncio
async def test_unrelated_user_gets_no_access_under_any_visibility_combination(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("visowner7"), "Vis Owner 7")
    home_id = await create_home(client, "Vis Unrelated Home")
    wishlist = await create_wishlist(client, home_id)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as other_client:
        await create_verified_user(other_client, unique_email("visunrelated7"), "Vis Unrelated 7")
        await create_home(other_client, "Vis Unrelated's Own Home")

        for enabled in (False, True, False):
            await set_home_visible(client, home_id, wishlist["id"], enabled=enabled)
            blocked = await other_client.get(f"/api/v1/wishlists/{wishlist['id']}")
            assert blocked.status_code == 404


@pytest.mark.asyncio
async def test_owner_never_sees_reservation_data_on_a_home_visible_wishlist(
    client: AsyncClient,
) -> None:
    """Reservation privacy must hold regardless of home_visible — repeats
    test_owner_never_sees_reservation_data_even_after_a_reservation's
    assertions specifically against a Home-visible (not private) wishlist."""
    await create_verified_user(client, unique_email("visprivacyowner"), "Vis Privacy Owner")
    home_id = await create_home(client, "Vis Privacy Home")
    wishlist = await create_wishlist(client, home_id)
    added = await add_item(client, home_id, wishlist["id"], name="Visible Secret Gift")
    item_id = added["items"][0]["id"]

    partner_email = unique_email("visprivacypartner")
    await add_partner(client, home_id, partner_email, "Vis Reserving Partner")
    await set_home_visible(client, home_id, wishlist["id"])

    async with login_as(partner_email) as partner_client:
        reserved = await unsafe(
            partner_client,
            "POST",
            f"/api/v1/wishlists/{wishlist['id']}/items/{item_id}/reserve",
            json={"buyer_display_name": "Uncle Bob"},
        )
        assert reserved.status_code == 200, reserved.text

    owner_view = await client.get(f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}")
    owner_item = next(i for i in owner_view.json()["items"] if i["id"] == item_id)
    assert "reservation_status" not in owner_item
    assert "reserved_by_display_name" not in owner_item


@pytest.mark.asyncio
async def test_non_owner_admin_cannot_toggle_visibility_when_missing_manage_capability(
    client: AsyncClient,
) -> None:
    """A same-Home member without wishlists_manage cannot flip another
    member's visibility toggle, mirroring the existing owner-or-admin gate
    on every other mutation endpoint."""
    await create_verified_user(client, unique_email("visowner8"), "Vis Owner 8")
    home_id = await create_home(client, "Vis No Manage Home")
    wishlist = await create_wishlist(client, home_id)
    partner_email = unique_email("vispartner8")
    await add_partner(client, home_id, partner_email, "Vis Partner 8")

    async with SessionFactory() as db:
        membership = await db.scalar(
            select(Membership).where(
                Membership.group_id == home_id,
                Membership.relationship == HouseholdRelationship.partner,
            )
        )
        assert membership is not None
        membership.permission_overrides = {"wishlists.manage": False}
        await db.commit()

    async with login_as(partner_email) as partner_client:
        blocked = await unsafe(
            partner_client,
            "POST",
            f"/api/v1/homes/{home_id}/wishlists/{wishlist['id']}/home-visibility",
            json={"enabled": True},
        )
        assert blocked.status_code == 403
