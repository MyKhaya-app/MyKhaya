"""Platform Control Centre Stripe-backed Home presentation: the actual
provider-derived price/currency, dashboard links, summary metrics, and the
manual reconciliation action. Also covers the Complimentary <-> Stripe
conflict guard extended onto Phase 1/2's grant_complimentary endpoint.
stripe.Price.retrieve / stripe.Subscription.retrieve are monkeypatched — no
real Stripe sandbox call is made.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime

import pytest
import stripe
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete, select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import ensure_home_subscription
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    AdministrativeAuditEvent,
    BillingInterval,
    HomeSubscriptionEvent,
    PlatformAdministrator,
    PlatformRole,
    SubscriptionPlan,
    SubscriptionProvider,
    SubscriptionStatus,
    TokenPurpose,
    User,
)
from mykhaya.security import derived_token, password_hash

ADMIN_ORIGIN = "http://admin.localhost:8080"
ORIGIN = "http://localhost:8080"
ADMIN_PASSWORD = "A separate operator password!"
USER_PASSWORD = "Correct horse battery staple!"


@pytest.fixture(autouse=True)
def _stripe_configured() -> AsyncIterator[None]:
    configured = get_settings().model_copy(
        update={
            "stripe_billing_configured": True,
            "stripe_secret_key": SecretStr("sk_test_abc123"),
            "stripe_webhook_secret": SecretStr("whsec_test_abc123"),
            "stripe_family_monthly_price_id": "price_month_current",
            "stripe_family_annual_price_id": "price_year_current",
        }
    )
    app.dependency_overrides[get_settings] = lambda: configured
    yield
    app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 44300)),
        base_url=ADMIN_ORIGIN,
        headers={"Origin": ADMIN_ORIGIN},
    ) as value:
        yield value


@pytest.fixture
async def household_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.fixture
async def admin_factory() -> AsyncIterator[
    Callable[[PlatformRole], Awaitable[PlatformAdministrator]]
]:
    identifiers: list[uuid.UUID] = []

    async def factory(role: PlatformRole = PlatformRole.owner) -> PlatformAdministrator:
        suffix = datetime.now(UTC).strftime("%H%M%S%f")
        async with SessionFactory() as db:
            row = PlatformAdministrator(
                email=f"operator-{suffix}@example.com",
                display_name="Test Operator",
                password_hash=password_hash.hash(ADMIN_PASSWORD),
                role=role,
                mfa_enrolled=True,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
        identifiers.append(row.id)
        return row

    yield factory
    if identifiers:
        async with SessionFactory() as db:
            await db.execute(
                delete(AdministrativeAuditEvent).where(
                    AdministrativeAuditEvent.administrator_id.in_(identifiers)
                )
            )
            await db.execute(
                delete(PlatformAdministrator).where(PlatformAdministrator.id.in_(identifiers))
            )
            await db.commit()


async def admin_login(client: AsyncClient, admin: PlatformAdministrator) -> None:
    response = await client.post(
        "/api/v1/platform/auth/login",
        json={"email": admin.email, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text


async def unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    csrf_cookie_name = "mk_admin_csrf" if "admin" in str(client.base_url) else "mk_csrf"
    csrf = client.cookies.get(csrf_cookie_name)
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


async def make_household(client: AsyncClient, suffix: str, name: str = "Test Home") -> uuid.UUID:
    email = f"member-{suffix}@example.com"
    register = await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": "Member", "password": USER_PASSWORD},
    )
    assert register.status_code == 202
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
            token.id,
            TokenPurpose.verify_email.value,
            get_settings().secret_key.get_secret_value(),
        )
    verified = await unsafe(client, "POST", "/api/v1/auth/verify-email", json={"token": raw})
    assert verified.status_code == 200
    login = await unsafe(
        client, "POST", "/api/v1/auth/login", json={"email": email, "password": USER_PASSWORD}
    )
    assert login.status_code == 200
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert group.status_code == 201
    return uuid.UUID(group.json()["id"])


async def _make_stripe_home(
    client: AsyncClient,
    suffix: str,
    *,
    status: SubscriptionStatus = SubscriptionStatus.active,
    interval: str = "month",
    price_id: str = "price_month_current",
    subscription_id: str | None = None,
) -> uuid.UUID:
    home_id = await make_household(client, suffix)
    async with SessionFactory() as db:
        subscription = await ensure_home_subscription(db, home_id)
        subscription.plan = SubscriptionPlan.family
        subscription.provider = SubscriptionProvider.stripe
        subscription.status = status
        subscription.external_customer_id = f"cus_{uuid.uuid4().hex[:12]}"
        subscription.external_subscription_id = subscription_id or f"sub_{uuid.uuid4().hex[:12]}"
        subscription.external_price_id = price_id
        subscription.billing_interval = BillingInterval(interval)
        await db.commit()
    return home_id


def _fake_price(price_id: str, *, unit_amount: int = 399, interval: str = "month") -> dict:
    return {
        "id": price_id,
        "active": True,
        "currency": "gbp",
        "unit_amount": unit_amount,
        "recurring": {"interval": interval},
    }


# ---------------------------------------------------------------------------
# Subscription detail: actual Stripe price + dashboard links
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_shows_live_stripe_price_and_test_mode_dashboard_links(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        stripe.Price, "retrieve", lambda price_id, **kw: _fake_price(price_id, unit_amount=399)
    )
    home_id = await _make_stripe_home(household_client, uuid.uuid4().hex[:10])
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    detail = await admin_client.get(f"/api/v1/platform/subscriptions/{home_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["subscription"]["provider"] == "stripe"
    assert payload["subscription"]["billing_interval"] == "month"
    assert payload["stripe_price"]["unit_amount"] == 399
    assert payload["stripe_price"]["formatted_amount"] == "£3.99"
    assert payload["stripe_dashboard_customer_url"].startswith(
        "https://dashboard.stripe.com/test/customers/"
    )
    assert payload["stripe_dashboard_subscription_url"].startswith(
        "https://dashboard.stripe.com/test/subscriptions/"
    )


@pytest.mark.asyncio
async def test_detail_resolves_the_historical_price_even_if_signup_price_changed(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A subscriber on an old, grandfathered Price is shown their own actual
    price, not the currently-configured signup price — see "Price increases
    and grandfathering" in docs/architecture/commercial-entitlements.md."""

    def fake_retrieve(price_id: str, **kw: object) -> dict:
        assert price_id == "price_old_grandfathered"
        return _fake_price(price_id, unit_amount=299)

    monkeypatch.setattr(stripe.Price, "retrieve", fake_retrieve)
    home_id = await _make_stripe_home(
        household_client, uuid.uuid4().hex[:10], price_id="price_old_grandfathered"
    )
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    detail = await admin_client.get(f"/api/v1/platform/subscriptions/{home_id}")
    payload = detail.json()
    assert payload["subscription"]["external_price_id"] == "price_old_grandfathered"
    assert payload["stripe_price"]["unit_amount"] == 299


# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_includes_stripe_specific_counts(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    before = (await admin_client.get("/api/v1/platform/subscriptions/summary")).json()

    suffix = uuid.uuid4().hex[:10]
    await _make_stripe_home(household_client, f"m-{suffix}", interval="month")
    await _make_stripe_home(household_client, f"y-{suffix}", interval="year")
    await _make_stripe_home(
        household_client,
        f"c-{suffix}",
        status=SubscriptionStatus.cancel_at_period_end,
        interval="month",
    )

    after = (await admin_client.get("/api/v1/platform/subscriptions/summary")).json()
    assert after["stripe_total"] == before["stripe_total"] + 3
    assert after["stripe_active_family"] == before["stripe_active_family"] + 3
    assert after["stripe_monthly"] == before["stripe_monthly"] + 2
    assert after["stripe_annual"] == before["stripe_annual"] + 1
    assert after["stripe_cancelling"] == before["stripe_cancelling"] + 1
    assert "revenue" not in after
    assert "mrr" not in after
    assert "arr" not in after


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_applies_current_stripe_state_and_is_audited(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    home_id = await _make_stripe_home(
        household_client,
        uuid.uuid4().hex[:10],
        status=SubscriptionStatus.past_due,
        subscription_id=sub_id,
    )

    def fake_retrieve(subscription_id: str, **kw: object) -> dict:
        assert subscription_id == sub_id
        return {
            "id": sub_id,
            "status": "active",
            "cancel_at_period_end": False,
            "customer": f"cus_{uuid.uuid4().hex[:12]}",
            "current_period_start": 1_700_000_000,
            "current_period_end": 1_800_000_000,
            "items": {
                "data": [
                    {"price": {"id": "price_month_current", "recurring": {"interval": "month"}}}
                ]
            },
        }

    monkeypatch.setattr(stripe.Subscription, "retrieve", fake_retrieve)
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    response = await unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/homes/{home_id}/subscription/reconcile-stripe",
        json={"reason": "Support ticket #4821 — customer reports access issue", "confirmed": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"

    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(HomeSubscriptionEvent)
                .where(HomeSubscriptionEvent.group_id == home_id)
                .order_by(HomeSubscriptionEvent.created_at.desc())
            )
        ).all()
        # The specific label reflects the actual transition detected
        # (past_due -> active is "payment recovered", overriding the
        # "stripe_reconciled" hint — see _pick_event_type in
        # mykhaya.billing.state) — what matters here is that reconciliation
        # produced exactly one new, attributable event.
        latest = events[0]
        assert latest.actor_administrator_id == owner.id
        assert latest.from_status == SubscriptionStatus.past_due
        assert latest.to_status == SubscriptionStatus.active

        audit_event = await db.scalar(
            select(AdministrativeAuditEvent).where(
                AdministrativeAuditEvent.administrator_id == owner.id,
                AdministrativeAuditEvent.action == "home.subscription_reconciled",
            )
        )
        assert audit_event is not None


@pytest.mark.asyncio
async def test_reconcile_with_no_named_transition_uses_the_reconciled_label(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A repair that doesn't match any named category (status unchanged,
    only the period/price refreshed) still gets a distinct, attributable
    history entry, labelled with the reconciliation hint."""
    sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    home_id = await _make_stripe_home(
        household_client,
        uuid.uuid4().hex[:10],
        status=SubscriptionStatus.active,
        subscription_id=sub_id,
        price_id="price_month_current",
    )

    def fake_retrieve(subscription_id: str, **kw: object) -> dict:
        return {
            "id": sub_id,
            "status": "active",
            "cancel_at_period_end": False,
            "customer": f"cus_{uuid.uuid4().hex[:12]}",
            "current_period_start": 1_700_000_000,
            "current_period_end": 1_900_000_000,
            "items": {
                "data": [{"price": {"id": "price_year_current", "recurring": {"interval": "year"}}}]
            },
        }

    monkeypatch.setattr(stripe.Subscription, "retrieve", fake_retrieve)
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    response = await unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/homes/{home_id}/subscription/reconcile-stripe",
        json={"reason": "Reconciling after a manual price change in Stripe", "confirmed": True},
    )
    assert response.status_code == 200, response.text

    async with SessionFactory() as db:
        events = (
            await db.scalars(
                select(HomeSubscriptionEvent).where(HomeSubscriptionEvent.group_id == home_id)
            )
        ).all()
        assert any(e.event_type == "stripe_reconciled" for e in events)


@pytest.mark.asyncio
async def test_reconcile_requires_operator_role(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    home_id = await _make_stripe_home(household_client, uuid.uuid4().hex[:10])
    support = await admin_factory(PlatformRole.support)
    await admin_login(admin_client, support)
    response = await unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/homes/{home_id}/subscription/reconcile-stripe",
        json={"reason": "Trying to reconcile without permission", "confirmed": True},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reconcile_without_a_stripe_subscription_conflicts(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    home_id = await make_household(household_client, uuid.uuid4().hex[:10])
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    response = await unsafe(
        admin_client,
        "POST",
        f"/api/v1/platform/homes/{home_id}/subscription/reconcile-stripe",
        json={"reason": "Nothing to reconcile here", "confirmed": True},
    )
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Complimentary <-> Stripe conflict guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grant_complimentary_rejects_a_live_stripe_subscription(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    home_id = await _make_stripe_home(household_client, uuid.uuid4().hex[:10])
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    response = await unsafe(
        admin_client,
        "PUT",
        f"/api/v1/platform/homes/{home_id}/subscription/complimentary",
        json={"complimentary_reason": "Beta tester", "confirmed": True, "reason": "Test grant"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_grant_complimentary_allowed_once_stripe_subscription_is_cancelled(
    admin_client: AsyncClient,
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],
    household_client: AsyncClient,
) -> None:
    home_id = await _make_stripe_home(
        household_client, uuid.uuid4().hex[:10], status=SubscriptionStatus.cancelled
    )
    owner = await admin_factory(PlatformRole.owner)
    await admin_login(admin_client, owner)
    response = await unsafe(
        admin_client,
        "PUT",
        f"/api/v1/platform/homes/{home_id}/subscription/complimentary",
        json={"complimentary_reason": "Beta tester", "confirmed": True, "reason": "Test grant"},
    )
    assert response.status_code == 200
    assert response.json()["provider"] == "complimentary"


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_household_group_response_never_exposes_stripe_identifiers(
    household_client: AsyncClient,
) -> None:
    home_id = await _make_stripe_home(household_client, uuid.uuid4().hex[:10])
    response = await unsafe(household_client, "GET", f"/api/v1/groups/{home_id}")
    assert response.status_code == 200
    text = response.text
    assert "external_customer_id" not in text
    assert "external_subscription_id" not in text
    assert "stripe_secret_key" not in text
    assert "whsec" not in text
