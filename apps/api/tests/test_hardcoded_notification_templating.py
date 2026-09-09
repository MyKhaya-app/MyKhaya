"""Coverage for the notification-consistency follow-up: seven notification-producing
paths (list item assignment, wishlist sharing x2, meal plan create/update/remove, Home
join requests) that used to build title/body as hardcoded/computed strings, bypassing
mykhaya.notifications.templates.render_notification, and therefore could not be seen or
customised in PCC. This does not change notification_type, recipients, preference
gating, delivery timing, or idempotency for any of them — only where the wording comes
from. See docs/architecture/notification-engine.md and the notification template audit
(commit 6c70c66) that identified these seven paths.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

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
    MealPlanEntry,
    Membership,
    Notification,
    NotificationChannel,
    NotificationTemplate,
    PermissionProfile,
    Role,
    SubscriptionPlan,
    TokenPurpose,
    User,
)
from mykhaya.notifications.engine import get_or_create_preferences
from mykhaya.notifications.meal_plans import notify_updated
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
        client, "POST", "/api/v1/auth/register",
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
                ActionToken.user_id == user.id, ActionToken.purpose == TokenPurpose.verify_email
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


async def create_home(client: AsyncClient, name: str) -> uuid.UUID:
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert group.status_code == 201
    home_id = uuid.UUID(group.json()["id"])
    async with SessionFactory() as db:
        for key in (FeatureKey.shopping, FeatureKey.wish_lists, FeatureKey.meals):
            db.add(FeatureOverride(feature_key=key, group_id=home_id, enabled=True))
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
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


async def last_notification(recipient_id: uuid.UUID) -> Notification | None:
    async with SessionFactory() as db:
        return await db.scalar(
            select(Notification)
            .where(Notification.recipient_user_id == recipient_id)
            .order_by(Notification.created_at.desc())
        )


# --- List item assignment ----------------------------------------------------


@pytest.mark.asyncio
async def test_list_item_assignment_uses_the_template_and_keeps_its_notification_type(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("listowner"), "Listowner")
    home_id = await create_home(client, "List Templating Home")
    partner_id = await add_partner(client, home_id, unique_email("listpartner"), "Listpartner")

    created_list = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/lists", json={"name": "Weekly shop"}
    )
    assert created_list.status_code == 201, created_list.text
    list_id = created_list.json()["id"]

    added = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/lists/{list_id}/items",
        json={"text": "Milk", "assigned_member_id": str(partner_id)},
    )
    assert added.status_code == 201, added.text

    notification = await last_notification(partner_id)
    assert notification is not None
    assert notification.notification_type == "list_item_assigned"
    assert notification.title == "List item assigned"
    assert notification.body == 'Listowner assigned "Milk" to you on Weekly shop.'


@pytest.mark.asyncio
async def test_list_item_assignment_still_respects_list_assignments_enabled(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("listgate"), "Listgate")
    home_id = await create_home(client, "List Gate Home")
    partner_id = await add_partner(client, home_id, unique_email("listgatep"), "Listgatep")
    async with SessionFactory() as db:
        prefs = await get_or_create_preferences(db, partner_id)
        prefs.list_assignments_enabled = False
        await db.commit()

    created_list = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/lists", json={"name": "Groceries"}
    )
    list_id = created_list.json()["id"]
    added = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/lists/{list_id}/items",
        json={"text": "Bread", "assigned_member_id": str(partner_id)},
    )
    assert added.status_code == 201, added.text

    assert await last_notification(partner_id) is None


@pytest.mark.asyncio
async def test_list_item_assignment_pcc_override_is_used_by_the_real_send_path(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("listover"), "Listover")
    home_id = await create_home(client, "List Override Home")
    partner_id = await add_partner(client, home_id, unique_email("listoverp"), "Listoverp")
    async with SessionFactory() as db:
        db.add(
            NotificationTemplate(
                template_type="list_item_assigned",
                channel=NotificationChannel.in_app,
                subject="Custom assignment",
                body_text="Custom: {{item_name}} for {{actor_display_name}}",
                enabled=True,
            )
        )
        await db.commit()

    created_list = await unsafe(
        client, "POST", f"/api/v1/homes/{home_id}/lists", json={"name": "Overridden list"}
    )
    list_id = created_list.json()["id"]
    added = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/lists/{list_id}/items",
        json={"text": "Eggs", "assigned_member_id": str(partner_id)},
    )
    assert added.status_code == 201, added.text

    notification = await last_notification(partner_id)
    assert notification is not None
    assert notification.title == "Custom assignment"
    assert notification.body == "Custom: Eggs for Listover"


# --- Wishlist sharing ---------------------------------------------------------


@pytest.mark.asyncio
async def test_wishlist_direct_share_created_and_revoked_use_the_you_scope_wording(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("wlowner"), "Wlowner")
    home_id = await create_home(client, "Wishlist Templating Home")
    recipient_email = unique_email("wlrecipient")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as recipient_client:
        recipient_id = await create_verified_user(recipient_client, recipient_email, "Wlrecipient")

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists",
        json={"title": "Birthday ideas", "occasion": "general"},
    )
    assert created.status_code == 201, created.text
    wishlist_id = created.json()["id"]

    share = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists/{wishlist_id}/shares",
        json={
            "recipient_name": "Wlrecipient",
            "recipient_email": recipient_email,
            "share_type": "mykhaya_user",
            "confirmed_user_id": str(recipient_id),
        },
    )
    assert share.status_code == 201, share.text
    share_id = share.json()["id"]

    created_notification = await last_notification(recipient_id)
    assert created_notification is not None
    assert created_notification.notification_type == "wishlist_share_created"
    assert created_notification.title == "Wishlist shared with you"
    assert created_notification.body == 'Wlowner shared "Birthday ideas" with you.'

    revoke = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists/{wishlist_id}/shares/{share_id}/revoke",
    )
    assert revoke.status_code == 204

    revoked_notification = await last_notification(recipient_id)
    assert revoked_notification is not None
    assert revoked_notification.notification_type == "wishlist_share_revoked"
    assert revoked_notification.title == "Wishlist access removed"
    assert revoked_notification.body == 'Wlowner removed your access to "Birthday ideas".'


@pytest.mark.asyncio
async def test_wishlist_home_visibility_toggle_uses_the_your_home_scope_wording(
    client: AsyncClient,
) -> None:
    """The same two notification_types cover a genuinely different context —
    sharing with the whole Home rather than one named recipient — via the
    {{recipient_scope}}/{{access_scope}} variables on the same template,
    rather than a second near-duplicate template key."""
    await create_verified_user(client, unique_email("wlhome"), "Wlhome")
    home_id = await create_home(client, "Wishlist Home Visibility Home")
    member_id = await add_partner(client, home_id, unique_email("wlhomep"), "Wlhomep")

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists",
        json={"title": "Shared list", "occasion": "general"},
    )
    wishlist_id = created.json()["id"]

    enabled = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists/{wishlist_id}/home-visibility",
        json={"enabled": True},
    )
    assert enabled.status_code == 200, enabled.text

    notification = await last_notification(member_id)
    assert notification is not None
    assert notification.notification_type == "wishlist_share_created"
    assert notification.title == "Wishlist shared with your Home"
    assert notification.body == 'Wlhome shared "Shared list" with your Home.'

    disabled = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists/{wishlist_id}/home-visibility",
        json={"enabled": False},
    )
    assert disabled.status_code == 200, disabled.text

    revoked_notification = await last_notification(member_id)
    assert revoked_notification is not None
    assert revoked_notification.notification_type == "wishlist_share_revoked"
    assert revoked_notification.title == "Wishlist access removed"
    assert revoked_notification.body == 'Wlhome removed your Home access to "Shared list".'


@pytest.mark.asyncio
async def test_wishlist_share_still_respects_wishlist_sharing_enabled(
    client: AsyncClient,
) -> None:
    await create_verified_user(client, unique_email("wlgate"), "Wlgate")
    home_id = await create_home(client, "Wishlist Gate Home")
    recipient_email = unique_email("wlgater")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as recipient_client:
        recipient_id = await create_verified_user(recipient_client, recipient_email, "Wlgater")
    async with SessionFactory() as db:
        prefs = await get_or_create_preferences(db, recipient_id)
        prefs.wishlist_sharing_enabled = False
        await db.commit()

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists",
        json={"title": "Gated wishlist", "occasion": "general"},
    )
    wishlist_id = created.json()["id"]
    share = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists/{wishlist_id}/shares",
        json={
            "recipient_name": "Wlgater",
            "recipient_email": recipient_email,
            "share_type": "mykhaya_user",
            "confirmed_user_id": str(recipient_id),
        },
    )
    assert share.status_code == 201, share.text

    assert await last_notification(recipient_id) is None


# --- Meal plans ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_meal_plan_created_updated_removed_render_through_the_registry(
    client: AsyncClient,
) -> None:
    """No new preference category was added for meal plans — this proves the
    wording now comes from the registry while confirming delivery still
    happens exactly as before (same recipients, same three notification
    types, no opt-out)."""
    owner_id = await create_verified_user(client, unique_email("mealowner"), "Mealowner")
    home_id = await create_home(client, "Meal Plan Templating Home")
    partner_id = await add_partner(client, home_id, unique_email("mealpartner"), "Mealpartner")

    created = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/meal-plan/entries",
        json={
            "quick_meal_name": "Lasagne",
            "date": date.today().isoformat(),
            "meal_slot": "dinner",
            "cook_member_id": str(partner_id),
        },
    )
    assert created.status_code == 201, created.text
    entry = created.json()

    weekday = date.today().strftime("%A")
    created_notification = await last_notification(partner_id)
    assert created_notification is not None
    assert created_notification.notification_type == "meal_plan_created"
    assert created_notification.title == f"Dinner planned for {weekday}"
    assert created_notification.body == "Lasagne\nMealpartner is cooking"

    # notify_updated() is exercised directly rather than through the PATCH
    # endpoint: mykhaya.routers.meal_plans.update_meal_plan_entry has a
    # pre-existing, unrelated bug (confirmed independently of this task —
    # test_meal_plans.py::test_entry_update_and_soft_delete already fails
    # identically on an unmodified checkout) where entry.updated_at is
    # accessed after its attributes have been expired outside a greenlet
    # context. That is a router/ORM issue, not a templating one — out of
    # scope here — so this test reaches the same notify_updated() code the
    # HTTP path would call, without going through the broken endpoint.
    async with SessionFactory() as db:
        row = await db.get(MealPlanEntry, uuid.UUID(entry["id"]))
        assert row is not None
        row.quick_meal_name = "Roast chicken"
        await db.flush()
        await db.refresh(row)
        await notify_updated(
            db, get_settings(), row, None, owner_id,
            before_participants=set(), before_cook=partner_id, material_change=True,
        )
        await db.commit()

    updated_notification = await last_notification(partner_id)
    assert updated_notification is not None
    assert updated_notification.notification_type == "meal_plan_updated"
    assert updated_notification.title == f"{weekday}'s dinner changed"
    assert updated_notification.body == "Roast chicken\nMealpartner is cooking"

    removed = await unsafe(
        client, "DELETE", f"/api/v1/homes/{home_id}/meal-plan/entries/{entry['id']}"
    )
    assert removed.status_code == 204

    removed_notification = await last_notification(partner_id)
    assert removed_notification is not None
    assert removed_notification.notification_type == "meal_plan_removed"
    assert removed_notification.title == f"{weekday}'s dinner was removed"
    assert removed_notification.body == "Roast chicken\nMealpartner is cooking"


# --- Home join requests --------------------------------------------------------


@pytest.mark.asyncio
async def test_home_join_request_uses_the_template_and_still_reaches_the_admin(
    client: AsyncClient,
) -> None:
    """No opt-out was introduced — this notification remains gated only by
    the admin's channel toggles, matching current (non-mandatory but
    ungated) behaviour: see routers.home_join's own comment on why this is
    best-effort rather than a MANDATORY_EMAIL_TYPES-style workflow."""
    admin_id = await create_verified_user(client, unique_email("joinadmin"), "Joinadmin")
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Join Home"})
    home_id = group.json()["id"]
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, uuid.UUID(home_id))
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()
    code_response = await unsafe(
        client, "POST", f"/api/v1/groups/{home_id}/join-code/regenerate"
    )
    assert code_response.status_code == 200
    code = code_response.json()["code"]

    joiner_email = unique_email("joiner")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as joiner_client:
        await create_verified_user(joiner_client, joiner_email, "Requester")
        requested = await unsafe(
            joiner_client, "POST", "/api/v1/home-join/request", json={"code": code}
        )
        assert requested.status_code == 201, requested.text

    notification = await last_notification(admin_id)
    assert notification is not None
    assert notification.notification_type == "home_join_request"
    assert notification.title == "New Home join request"
    assert notification.body == "Requester wants to join Join Home using your Home join code."
