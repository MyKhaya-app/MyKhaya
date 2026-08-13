"""mykhaya.billing.state — the single function that turns a Stripe
Subscription object into HomeSubscription state. Pure-logic mapping tests
plus DB-backed tests of apply_stripe_subscription_state's transition,
out-of-order guards, and event-history behaviour.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from mykhaya.billing.state import (
    apply_stripe_subscription_state,
    extract_period,
    extract_price_and_interval,
    map_stripe_subscription_status,
)
from mykhaya.db import SessionFactory
from mykhaya.entitlements import get_home_subscription
from mykhaya.models import (
    BillingInterval,
    Group,
    HomeSubscriptionEvent,
    SubscriptionPlan,
    SubscriptionProvider,
    SubscriptionStatus,
    User,
)


async def _make_home(name: str = "Test Home") -> uuid.UUID:
    async with SessionFactory() as db:
        user = User(email=f"owner-{uuid.uuid4()}@example.com", display_name="Owner")
        db.add(user)
        await db.flush()
        group = Group(name=name, created_by=user.id)
        db.add(group)
        await db.commit()
        return group.id


def _stripe_subscription(
    *,
    id_: str | None = None,
    status: str = "active",
    cancel_at_period_end: bool = False,
    price_id: str = "price_month",
    interval: str = "month",
    period_start: int = 1_700_000_000,
    period_end: int = 1_702_592_000,
    customer: str | None = None,
) -> dict:
    return {
        "id": id_ or f"sub_{uuid.uuid4().hex[:12]}",
        "status": status,
        "cancel_at_period_end": cancel_at_period_end,
        "customer": customer or f"cus_{uuid.uuid4().hex[:12]}",
        "current_period_start": period_start,
        "current_period_end": period_end,
        "items": {
            "data": [
                {
                    "price": {"id": price_id, "recurring": {"interval": interval}},
                }
            ]
        },
    }


# ---------------------------------------------------------------------------
# Pure mapping
# ---------------------------------------------------------------------------


def test_maps_active_and_trialing_directly() -> None:
    assert map_stripe_subscription_status(_stripe_subscription(status="active")) == (
        SubscriptionStatus.active
    )
    assert map_stripe_subscription_status(_stripe_subscription(status="trialing")) == (
        SubscriptionStatus.trialing
    )


def test_maps_unpaid_and_paused_to_past_due() -> None:
    assert map_stripe_subscription_status(_stripe_subscription(status="unpaid")) == (
        SubscriptionStatus.past_due
    )
    assert map_stripe_subscription_status(_stripe_subscription(status="paused")) == (
        SubscriptionStatus.past_due
    )


def test_maps_canceled_and_incomplete_expired_to_cancelled() -> None:
    assert map_stripe_subscription_status(_stripe_subscription(status="canceled")) == (
        SubscriptionStatus.cancelled
    )
    assert map_stripe_subscription_status(_stripe_subscription(status="incomplete_expired")) == (
        SubscriptionStatus.cancelled
    )


def test_incomplete_and_unrecognised_status_produce_no_mutation() -> None:
    assert map_stripe_subscription_status(_stripe_subscription(status="incomplete")) is None
    assert map_stripe_subscription_status(_stripe_subscription(status="some_future_status")) is None


def test_active_with_cancel_at_period_end_maps_to_cancel_at_period_end_status() -> None:
    result = map_stripe_subscription_status(
        _stripe_subscription(status="active", cancel_at_period_end=True)
    )
    assert result == SubscriptionStatus.cancel_at_period_end


def test_extract_price_and_interval() -> None:
    price_id, interval = extract_price_and_interval(
        _stripe_subscription(price_id="price_annual", interval="year")
    )
    assert price_id == "price_annual"
    assert interval == BillingInterval.year


def test_extract_price_and_interval_with_no_items() -> None:
    price_id, interval = extract_price_and_interval({"items": {"data": []}})
    assert price_id is None
    assert interval is None


def test_extract_period_from_subscription_level_fields() -> None:
    start, end = extract_period(
        _stripe_subscription(period_start=1_700_000_000, period_end=1_702_592_000)
    )
    assert start == datetime.fromtimestamp(1_700_000_000, tz=UTC)
    assert end == datetime.fromtimestamp(1_702_592_000, tz=UTC)


def test_extract_period_falls_back_to_item_level_fields() -> None:
    subscription = {
        "items": {
            "data": [
                {
                    "price": {"id": "price_month", "recurring": {"interval": "month"}},
                    "current_period_start": 1_700_000_000,
                    "current_period_end": 1_702_592_000,
                }
            ]
        }
    }
    start, end = extract_period(subscription)
    assert start == datetime.fromtimestamp(1_700_000_000, tz=UTC)
    assert end == datetime.fromtimestamp(1_702_592_000, tz=UTC)


# ---------------------------------------------------------------------------
# apply_stripe_subscription_state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_activates_family_from_confirmed_active_status() -> None:
    home_id = await _make_home()
    sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    async with SessionFactory() as db:
        result = await apply_stripe_subscription_state(
            db,
            group_id=home_id,
            stripe_subscription=_stripe_subscription(id_=sub_id, status="active"),
            actor_administrator_id=None,
            reason="test",
            event_type_hint="stripe_subscription_activated",
        )
        await db.commit()
        assert result is not None
        assert result.plan == SubscriptionPlan.family
        assert result.provider == SubscriptionProvider.stripe
        assert result.status == SubscriptionStatus.active
        assert result.external_subscription_id == sub_id
        assert result.external_price_id == "price_month"
        assert result.billing_interval == BillingInterval.month

    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(HomeSubscriptionEvent).where(HomeSubscriptionEvent.group_id == home_id)
            )
        ).all()
        assert any(event.event_type == "stripe_subscription_activated" for event in events)


@pytest.mark.asyncio
async def test_apply_with_incomplete_status_makes_no_mutation() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        result = await apply_stripe_subscription_state(
            db,
            group_id=home_id,
            stripe_subscription=_stripe_subscription(status="incomplete"),
            actor_administrator_id=None,
            reason="test",
            event_type_hint="stripe_subscription_activated",
        )
        await db.commit()
        assert result is None

    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        assert subscription is None


@pytest.mark.asyncio
async def test_apply_clears_complimentary_fields_on_transition_to_stripe() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        from mykhaya.entitlements import ensure_home_subscription

        subscription = await ensure_home_subscription(db, home_id)
        subscription.plan = SubscriptionPlan.family
        subscription.provider = SubscriptionProvider.complimentary
        subscription.complimentary_reason = "Beta tester"
        subscription.complimentary_expires_at = datetime.now(UTC) + timedelta(days=30)
        await db.commit()

    async with SessionFactory() as db:
        result = await apply_stripe_subscription_state(
            db,
            group_id=home_id,
            stripe_subscription=_stripe_subscription(status="active"),
            actor_administrator_id=None,
            reason="test",
            event_type_hint="stripe_subscription_activated",
        )
        await db.commit()
        assert result is not None
        assert result.provider == SubscriptionProvider.stripe
        assert result.complimentary_reason is None
        assert result.complimentary_expires_at is None

    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(HomeSubscriptionEvent).where(HomeSubscriptionEvent.group_id == home_id)
            )
        ).all()
        activation = next(e for e in events if e.event_type == "stripe_subscription_activated")
        assert activation.from_provider == SubscriptionProvider.complimentary
        assert activation.to_provider == SubscriptionProvider.stripe


@pytest.mark.asyncio
async def test_apply_no_event_written_when_nothing_material_changed() -> None:
    home_id = await _make_home()
    sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    async with SessionFactory() as db:
        await apply_stripe_subscription_state(
            db,
            group_id=home_id,
            stripe_subscription=_stripe_subscription(id_=sub_id, status="active"),
            actor_administrator_id=None,
            reason="first",
            event_type_hint="stripe_subscription_activated",
        )
        await db.commit()
    async with SessionFactory() as db:
        events_before = (
            await db.scalars(
                select(HomeSubscriptionEvent).where(HomeSubscriptionEvent.group_id == home_id)
            )
        ).all()
    async with SessionFactory() as db:
        # Same subscription id, same status, same price/interval — a
        # duplicate/no-op delivery.
        result = await apply_stripe_subscription_state(
            db,
            group_id=home_id,
            stripe_subscription=_stripe_subscription(id_=sub_id, status="active"),
            actor_administrator_id=None,
            reason="second",
            event_type_hint="stripe_subscription_updated",
        )
        await db.commit()
        assert result is not None
    async with SessionFactory() as db:
        events_after = (
            await db.scalars(
                select(HomeSubscriptionEvent).where(HomeSubscriptionEvent.group_id == home_id)
            )
        ).all()
    assert len(events_after) == len(events_before)


@pytest.mark.asyncio
async def test_scheduled_cancellation_and_reversal_are_labelled_distinctly() -> None:
    home_id = await _make_home()
    sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    async with SessionFactory() as db:
        await apply_stripe_subscription_state(
            db,
            group_id=home_id,
            stripe_subscription=_stripe_subscription(id_=sub_id, status="active"),
            actor_administrator_id=None,
            reason="activate",
            event_type_hint="stripe_subscription_activated",
        )
        await db.commit()
    async with SessionFactory() as db:
        await apply_stripe_subscription_state(
            db,
            group_id=home_id,
            stripe_subscription=_stripe_subscription(
                id_=sub_id, status="active", cancel_at_period_end=True
            ),
            actor_administrator_id=None,
            reason="cancel scheduled",
            event_type_hint="stripe_subscription_updated",
        )
        await db.commit()
    async with SessionFactory() as db:
        await apply_stripe_subscription_state(
            db,
            group_id=home_id,
            stripe_subscription=_stripe_subscription(
                id_=sub_id, status="active", cancel_at_period_end=False
            ),
            actor_administrator_id=None,
            reason="resumed",
            event_type_hint="stripe_subscription_updated",
        )
        await db.commit()

    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(HomeSubscriptionEvent)
                .where(HomeSubscriptionEvent.group_id == home_id)
                .order_by(HomeSubscriptionEvent.created_at)
            )
        ).all()
        event_types = [e.event_type for e in events]
        assert "stripe_cancellation_scheduled" in event_types
        assert "stripe_cancellation_reversed" in event_types


@pytest.mark.asyncio
async def test_final_cancellation_keeps_plan_family_but_status_cancelled() -> None:
    """The Home's effective plan resolves Free via the entitlement service's
    honoured-status check — the row itself is left as historically
    informative (plan=family, provider=stripe, status=cancelled) rather than
    reset to free/free, unlike a Complimentary revoke."""
    home_id = await _make_home()
    sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    async with SessionFactory() as db:
        await apply_stripe_subscription_state(
            db,
            group_id=home_id,
            stripe_subscription=_stripe_subscription(id_=sub_id, status="active"),
            actor_administrator_id=None,
            reason="activate",
            event_type_hint="stripe_subscription_activated",
        )
        await db.commit()
    async with SessionFactory() as db:
        result = await apply_stripe_subscription_state(
            db,
            group_id=home_id,
            stripe_subscription=_stripe_subscription(id_=sub_id, status="canceled"),
            actor_administrator_id=None,
            reason="deleted",
            event_type_hint="stripe_subscription_cancelled",
        )
        await db.commit()
        assert result is not None
        assert result.plan == SubscriptionPlan.family
        assert result.provider == SubscriptionProvider.stripe
        assert result.status == SubscriptionStatus.cancelled

    from mykhaya.entitlements import effective_plan

    async with SessionFactory() as db:
        assert await effective_plan(db, home_id) == SubscriptionPlan.free


@pytest.mark.asyncio
async def test_out_of_order_event_for_a_different_subscription_id_is_ignored() -> None:
    home_id = await _make_home()
    async with SessionFactory() as db:
        await apply_stripe_subscription_state(
            db,
            group_id=home_id,
            stripe_subscription=_stripe_subscription(id_="sub_new", status="active"),
            actor_administrator_id=None,
            reason="activate",
            event_type_hint="stripe_subscription_activated",
        )
        await db.commit()
    async with SessionFactory() as db:
        # A stale/delayed event for an old, different (and not-yet-cancelled
        # per MyKhaya's records) subscription id must not override the
        # currently tracked one.
        result = await apply_stripe_subscription_state(
            db,
            group_id=home_id,
            stripe_subscription=_stripe_subscription(id_="sub_old", status="canceled"),
            actor_administrator_id=None,
            reason="stale delete",
            event_type_hint="stripe_subscription_cancelled",
        )
        await db.commit()
        assert result is None
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        assert subscription.external_subscription_id == "sub_new"
        assert subscription.status == SubscriptionStatus.active


@pytest.mark.asyncio
async def test_out_of_order_event_with_older_period_end_is_ignored() -> None:
    home_id = await _make_home()
    sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    async with SessionFactory() as db:
        await apply_stripe_subscription_state(
            db,
            group_id=home_id,
            stripe_subscription=_stripe_subscription(
                id_=sub_id, status="active", period_end=1_800_000_000
            ),
            actor_administrator_id=None,
            reason="latest",
            event_type_hint="stripe_subscription_activated",
        )
        await db.commit()
    async with SessionFactory() as db:
        # A delayed webhook carrying an earlier period_end than what's
        # already stored for the SAME subscription id.
        result = await apply_stripe_subscription_state(
            db,
            group_id=home_id,
            stripe_subscription=_stripe_subscription(
                id_=sub_id, status="active", period_end=1_700_000_000
            ),
            actor_administrator_id=None,
            reason="stale",
            event_type_hint="stripe_subscription_updated",
        )
        await db.commit()
        assert result is None
    async with SessionFactory() as db:
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        assert subscription.current_period_end == datetime.fromtimestamp(1_800_000_000, tz=UTC)


@pytest.mark.asyncio
async def test_payment_failed_and_recovered_are_labelled_distinctly() -> None:
    home_id = await _make_home()
    sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    async with SessionFactory() as db:
        await apply_stripe_subscription_state(
            db,
            group_id=home_id,
            stripe_subscription=_stripe_subscription(id_=sub_id, status="active"),
            actor_administrator_id=None,
            reason="activate",
            event_type_hint="stripe_subscription_activated",
        )
        await db.commit()
    async with SessionFactory() as db:
        await apply_stripe_subscription_state(
            db,
            group_id=home_id,
            stripe_subscription=_stripe_subscription(id_=sub_id, status="past_due"),
            actor_administrator_id=None,
            reason="payment failed",
            event_type_hint="stripe_payment_failed",
        )
        await db.commit()
    async with SessionFactory() as db:
        await apply_stripe_subscription_state(
            db,
            group_id=home_id,
            stripe_subscription=_stripe_subscription(id_=sub_id, status="active"),
            actor_administrator_id=None,
            reason="payment recovered",
            event_type_hint="stripe_subscription_updated",
        )
        await db.commit()

    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(HomeSubscriptionEvent)
                .where(HomeSubscriptionEvent.group_id == home_id)
                .order_by(HomeSubscriptionEvent.created_at)
            )
        ).all()
        event_types = [e.event_type for e in events]
        assert "stripe_payment_failed" in event_types
        assert "stripe_payment_recovered" in event_types

    from mykhaya.entitlements import effective_plan, has_entitlement

    async with SessionFactory() as db:
        # past_due is still honoured — Family access is retained during
        # dunning (see docs/architecture/commercial-entitlements.md).
        assert await effective_plan(db, home_id) == SubscriptionPlan.family
        assert await has_entitlement(db, home_id, "lists.enabled") is True
