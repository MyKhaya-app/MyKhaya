"""Phase 2A: PCC platform availability is authoritative over a Home's
FeatureOverride — see docs/architecture/feature-flags.md and
mykhaya.features.is_feature_enabled. Also covers Nudges' independent module
governance (FeatureKey.nudges), replacing the previous entanglement with
FeatureKey.notifications.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from test_journey import ORIGIN, create_verified_user, unsafe

from mykhaya.db import SessionFactory
from mykhaya.entitlements import get_home_subscription
from mykhaya.features import is_feature_enabled
from mykhaya.main import app
from mykhaya.models import FeatureFlag, FeatureKey, FeatureOverride, SubscriptionPlan, Todo


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.fixture
async def nudges_globally_disabled() -> AsyncIterator[None]:
    """Temporarily flips the *global* 'nudges' FeatureFlag off, always
    restoring it afterwards — this is shared, cross-test state (unlike a
    Home-scoped FeatureOverride), so every test that touches it must clean
    up unconditionally or it would silently break unrelated tests/suites
    that rely on Nudges being globally enabled by default (the state
    0062_nudges_feature_flag_seed establishes)."""
    async with SessionFactory() as db:
        row = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == FeatureKey.nudges))
        assert row is not None
        row.enabled = False
        await db.commit()
    try:
        yield
    finally:
        async with SessionFactory() as db:
            row = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == FeatureKey.nudges))
            assert row is not None
            row.enabled = True
            await db.commit()


async def _home(client: AsyncClient, email: str, name: str) -> str:
    await create_verified_user(client, email, name)
    created = await unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert created.status_code == 201
    return created.json()["id"]


async def _make_family(home_id: str) -> None:
    """Nudges also requires the nudges.enabled commercial entitlement
    (Family-only, Phase 2B) on top of FeatureKey.nudges — tests that
    exercise a *successful* Nudges path need a Family Home; tests that
    exercise feature-flag denial don't (require_feature fails before
    require_entitlement is ever reached, so those stay valid on Free)."""
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, uuid.UUID(home_id))
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        await db.commit()


async def _set_override(home_id: str, feature: FeatureKey, enabled: bool) -> None:
    async with SessionFactory() as db:
        row = await db.scalar(
            select(FeatureOverride).where(
                FeatureOverride.group_id == uuid.UUID(home_id),
                FeatureOverride.feature_key == feature,
            )
        )
        if row is None:
            db.add(
                FeatureOverride(
                    group_id=uuid.UUID(home_id), feature_key=feature, enabled=enabled
                )
            )
        else:
            row.enabled = enabled
        await db.commit()


# --- Nudges registry -------------------------------------------------------


def test_nudges_feature_key_exists() -> None:
    assert FeatureKey("nudges") == FeatureKey.nudges


def test_nudges_module_definition_is_released_and_toggleable() -> None:
    from mykhaya.module_registry import ReleaseState, module_definition

    definition = module_definition(FeatureKey.nudges.value)
    assert definition.release_state == ReleaseState.released
    assert definition.household_toggleable is True
    assert definition.home_admin_manageable is True
    assert definition.category == "Family"
    assert definition.route == "/settings/routines-reminders"


@pytest.mark.asyncio
async def test_nudges_appears_released_and_toggleable_in_module_management(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id = await _home(client, f"nudges-registry-{suffix}@example.com", "Nudges Registry Home")
    await _make_family(home_id)

    management = await client.get(f"/api/v1/features/{home_id}/modules/management")
    assert management.status_code == 200
    rows = {row["id"]: row for row in management.json()}
    assert "nudges" in rows
    assert rows["nudges"]["release_state"] == "released"
    assert rows["nudges"]["toggleable"] is True
    assert rows["nudges"]["entitled"] is True
    assert rows["nudges"]["blocked_by"] is None
    assert rows["nudges"]["enabled"] is True  # global default seeded enabled


# --- Home Admin Module Management: plan awareness (Part C) ------------------


@pytest.mark.asyncio
async def test_free_home_module_management_shows_plan_blocked_modules(client: AsyncClient) -> None:
    """A Free Home still sees Nudges/Meal Plans/Wishlists in Module
    Management (so it's clear what Family includes) but they resolve
    unavailable/blocked_by=plan, and Lists/Calendar resolve available."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id = await _home(client, f"free-modmgmt-{suffix}@example.com", "Free Module Mgmt Home")

    management = await client.get(f"/api/v1/features/{home_id}/modules/management")
    assert management.status_code == 200
    rows = {row["id"]: row for row in management.json()}

    for module_id in ("nudges", "meals", "wish_lists"):
        assert rows[module_id]["entitled"] is False, module_id
        assert rows[module_id]["blocked_by"] == "plan", module_id
        assert rows[module_id]["enabled"] is False, module_id

    assert rows["shopping"]["entitled"] is True
    assert rows["shopping"]["blocked_by"] is None
    assert rows["calendar"]["entitled"] is True
    assert rows["calendar"]["blocked_by"] is None


@pytest.mark.asyncio
async def test_family_home_can_enable_and_disable_entitled_optional_modules(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id = await _home(client, f"family-modmgmt-{suffix}@example.com", "Family Module Mgmt Home")
    await _make_family(home_id)

    enabled = await unsafe(
        client,
        "PUT",
        f"/api/v1/features/{home_id}/nudges/household",
        json={"enabled": True, "reason": "Home Admin enables Nudges", "confirmed": True},
    )
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert enabled.json()["entitled"] is True
    assert enabled.json()["blocked_by"] is None

    disabled = await unsafe(
        client,
        "PUT",
        f"/api/v1/features/{home_id}/nudges/household",
        json={"enabled": False, "reason": "Home Admin disables Nudges again", "confirmed": True},
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False


@pytest.mark.asyncio
async def test_home_enable_request_cannot_bypass_plan_state(client: AsyncClient) -> None:
    """The PUT .../household endpoint must reject enabling a module the
    Home's plan doesn't include — the same commercial_restriction_error
    shape every other plan-gated write already uses."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id = await _home(client, f"free-enable-blocked-{suffix}@example.com", "Free Enable Home")

    response = await unsafe(
        client,
        "PUT",
        f"/api/v1/features/{home_id}/nudges/household",
        json={
            "enabled": True,
            "reason": "Free Home attempts to enable a Family-only module",
            "confirmed": True,
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "plan_feature_unavailable"
    assert response.json()["detail"]["entitlement"] == "nudges.enabled"
    async with SessionFactory() as db:
        row = await db.scalar(
            select(FeatureOverride).where(
                FeatureOverride.group_id == uuid.UUID(home_id),
                FeatureOverride.feature_key == FeatureKey.nudges,
            )
        )
        assert row is None  # no misleading override written


@pytest.mark.asyncio
async def test_platform_disabled_module_resolves_unavailable_in_module_management(
    client: AsyncClient, nudges_globally_disabled: None
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id = await _home(client, f"platform-off-modmgmt-{suffix}@example.com", "Platform Off Home")
    await _make_family(home_id)

    management = await client.get(f"/api/v1/features/{home_id}/modules/management")
    assert management.status_code == 200
    rows = {row["id"]: row for row in management.json()}
    assert rows["nudges"]["blocked_by"] == "platform"
    assert rows["nudges"]["enabled"] is False
    # Entitled is still True here — the Home's plan does include it, the
    # platform is what's currently blocking it — so the UI can show the
    # correct one of the two distinct "unavailable" reasons.
    assert rows["nudges"]["entitled"] is True


# --- Nudges authorization ----------------------------------------------------


@pytest.mark.asyncio
async def test_nudges_apis_succeed_when_globally_enabled_and_home_inherits(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id = await _home(client, f"nudges-ok-{suffix}@example.com", "Nudges OK Home")
    await _make_family(home_id)

    for path in ("routines", "reminders", "todos"):
        response = await client.get(f"/api/v1/homes/{home_id}/{path}")
        assert response.status_code == 200, path


@pytest.mark.asyncio
async def test_free_home_denied_nudges_even_though_globally_enabled(client: AsyncClient) -> None:
    """The feature-flag layer allows it (global default is enabled) — the
    commercial-entitlement layer is what actually denies a Free Home."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id = await _home(client, f"nudges-free-{suffix}@example.com", "Free Nudges Home")

    response = await client.get(f"/api/v1/homes/{home_id}/routines")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "plan_feature_unavailable"
    assert response.json()["detail"]["entitlement"] == "nudges.enabled"


@pytest.mark.asyncio
async def test_free_home_override_enabled_still_denied_by_plan(client: AsyncClient) -> None:
    """A Home FeatureOverride only ever operates within the platform/Home
    module-flag layer — it can never grant a commercial entitlement the
    Home's plan doesn't include."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id = await _home(
        client, f"nudges-free-override-{suffix}@example.com", "Free Override Home"
    )
    await _set_override(home_id, FeatureKey.nudges, True)

    response = await client.get(f"/api/v1/homes/{home_id}/routines")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "plan_feature_unavailable"


@pytest.mark.asyncio
async def test_pcc_global_enable_never_grants_free_plan_nudges_access(client: AsyncClient) -> None:
    """A PCC operator can only ever release a module platform-wide — that is
    the FeatureFlag layer. It can never itself grant a commercial
    entitlement; nudges.enabled remains resolved purely from the Home's
    plan, regardless of the global flag's value."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id = await _home(client, f"nudges-pcc-{suffix}@example.com", "PCC Enable Home")
    async with SessionFactory() as db:
        row = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == FeatureKey.nudges))
        assert row is not None
        assert row.enabled is True  # already globally enabled by default

    response = await client.get(f"/api/v1/homes/{home_id}/routines")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "plan_feature_unavailable"


@pytest.mark.asyncio
async def test_nudges_apis_fail_when_globally_disabled(
    client: AsyncClient, nudges_globally_disabled: None
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id = await _home(
        client, f"nudges-globaloff-{suffix}@example.com", "Nudges Global Off Home"
    )

    for path in ("routines", "reminders", "todos"):
        response = await client.get(f"/api/v1/homes/{home_id}/{path}")
        assert response.status_code == 404, path


@pytest.mark.asyncio
async def test_nudges_apis_fail_when_home_override_disables_it(client: AsyncClient) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id = await _home(client, f"nudges-homeoff-{suffix}@example.com", "Nudges Home Off Home")
    await _set_override(home_id, FeatureKey.nudges, False)

    for path in ("routines", "reminders", "todos"):
        response = await client.get(f"/api/v1/homes/{home_id}/{path}")
        assert response.status_code == 404, path


@pytest.mark.asyncio
async def test_home_override_enabled_does_not_bypass_global_disabled_state(
    client: AsyncClient, nudges_globally_disabled: None
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id = await _home(client, f"nudges-override-{suffix}@example.com", "Nudges Override Home")
    # A Home override explicitly requesting "on" must not resurrect a
    # feature the platform has switched off globally.
    await _set_override(home_id, FeatureKey.nudges, True)

    response = await client.get(f"/api/v1/homes/{home_id}/routines")
    assert response.status_code == 404
    async with SessionFactory() as db:
        assert (
            await is_feature_enabled(db, FeatureKey.nudges, uuid.UUID(home_id))
        ) is False


@pytest.mark.asyncio
async def test_disabling_nudges_does_not_disable_notifications(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id = await _home(client, f"nudges-isolation-{suffix}@example.com", "Isolation Home")
    await _set_override(home_id, FeatureKey.nudges, False)

    response = await client.get(f"/api/v1/homes/{home_id}/routines")
    assert response.status_code == 404

    async with SessionFactory() as db:
        assert (
            await is_feature_enabled(db, FeatureKey.notifications, uuid.UUID(home_id))
        ) is True


@pytest.mark.asyncio
async def test_home_admin_cannot_enable_nudges_while_globally_disabled(
    client: AsyncClient, nudges_globally_disabled: None
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id = await _home(
        client, f"nudges-blocked-enable-{suffix}@example.com", "Blocked Enable Home"
    )

    response = await unsafe(
        client,
        "PUT",
        f"/api/v1/features/{home_id}/nudges/household",
        json={
            "enabled": True,
            "reason": "Home Admin attempts to enable while platform has disabled it",
            "confirmed": True,
        },
    )
    assert response.status_code == 409
    async with SessionFactory() as db:
        row = await db.scalar(
            select(FeatureOverride).where(
                FeatureOverride.group_id == uuid.UUID(home_id),
                FeatureOverride.feature_key == FeatureKey.nudges,
            )
        )
        # No misleading override was written either.
        assert row is None


@pytest.mark.asyncio
async def test_nudge_data_is_preserved_on_downgrade_and_restored_on_upgrade(
    client: AsyncClient,
) -> None:
    """Downgrading to Free denies API access to Nudges (nudges.enabled is a
    simple boolean module entitlement, unlike Lists' numeric per-resource
    classification — there is nothing partial to classify) but must never
    delete existing routines/reminders/todos/completions/categories. See
    docs/architecture/commercial-entitlements.md 'Safe downgrade
    principle'."""
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id = await _home(client, f"nudges-preserve-{suffix}@example.com", "Preserve Home")
    await _make_family(home_id)

    created_todo = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/todos",
        json={"title": "Buy milk", "scope": "personal", "due_date": "2030-01-01"},
    )
    assert created_todo.status_code == 201, created_todo.text
    todo_id = created_todo.json()["id"]

    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, uuid.UUID(home_id))
        assert subscription is not None
        subscription.plan = SubscriptionPlan.free
        await db.commit()

    denied = await client.get(f"/api/v1/homes/{home_id}/todos")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "plan_feature_unavailable"

    # The row itself is untouched in the database throughout.
    async with SessionFactory() as db:
        row = await db.get(Todo, uuid.UUID(todo_id))
        assert row is not None
        assert row.title == "Buy milk"

    await _make_family(home_id)
    restored = await client.get(f"/api/v1/homes/{home_id}/todos")
    assert restored.status_code == 200
    assert any(item["id"] == todo_id for item in restored.json()["items"])


# --- Precedence matrix -------------------------------------------------------


@pytest.mark.asyncio
async def test_precedence_matrix(client: AsyncClient) -> None:
    # A single Home reused across every matrix row — registration is
    # IP-rate-limited (Settings.rate_limit_register), so a fresh user per
    # combination would exhaust it. Only is_feature_enabled's inputs
    # (global flag, Home override) vary between rows.
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id = await _home(client, f"matrix-{suffix}@example.com", "Matrix Home")

    async with SessionFactory() as db:
        flag_row = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == FeatureKey.nudges))
        assert flag_row is not None
        original_global = flag_row.enabled

    cases = [
        (False, None, False),
        (False, True, False),
        (False, False, False),
        (True, None, True),
        (True, True, True),
        (True, False, False),
    ]
    try:
        for global_enabled, home_override, expected in cases:
            async with SessionFactory() as db:
                flag_row = await db.scalar(
                    select(FeatureFlag).where(FeatureFlag.key == FeatureKey.nudges)
                )
                assert flag_row is not None
                flag_row.enabled = global_enabled
                await db.commit()
            if home_override is None:
                async with SessionFactory() as db:
                    override_row = await db.scalar(
                        select(FeatureOverride).where(
                            FeatureOverride.group_id == uuid.UUID(home_id),
                            FeatureOverride.feature_key == FeatureKey.nudges,
                        )
                    )
                    if override_row is not None:
                        await db.delete(override_row)
                        await db.commit()
            else:
                await _set_override(home_id, FeatureKey.nudges, home_override)
            async with SessionFactory() as db:
                result = await is_feature_enabled(db, FeatureKey.nudges, uuid.UUID(home_id))
            assert result is expected, (global_enabled, home_override, expected)
    finally:
        async with SessionFactory() as db:
            flag_row = await db.scalar(
                select(FeatureFlag).where(FeatureFlag.key == FeatureKey.nudges)
            )
            assert flag_row is not None
            flag_row.enabled = original_global
            await db.commit()


# --- Hidden modules -----------------------------------------------------


@pytest.mark.asyncio
async def test_hidden_module_fails_closed_regardless_of_flags_or_overrides(
    client: AsyncClient,
) -> None:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    home_id = await _home(client, f"hidden-{suffix}@example.com", "Hidden Module Home")

    async with SessionFactory() as db:
        row = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == FeatureKey.tasks))
        assert row is not None
        original = row.enabled
        row.enabled = True
        await db.commit()
    try:
        await _set_override(home_id, FeatureKey.tasks, True)
        async with SessionFactory() as db:
            assert (
                await is_feature_enabled(db, FeatureKey.tasks, uuid.UUID(home_id))
            ) is False
    finally:
        async with SessionFactory() as db:
            row = await db.scalar(select(FeatureFlag).where(FeatureFlag.key == FeatureKey.tasks))
            assert row is not None
            row.enabled = original
            await db.commit()

