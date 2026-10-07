"""The Founding Beta signup/onboarding journey, end to end:

    register (global Terms only, Beta intent recorded) -> verify email -> sign in
    -> Beta continuation -> accept current Founding Beta Terms -> create/enrol Home
    -> join (complimentary Ultimate, founding_beta_lifetime) -> welcome email

The Beta intent is durable server-side state (BetaPendingRegistration), so it
survives verification and first sign-in without any query string.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from test_calendar import PASSWORD, client, create_verified_user, unsafe  # noqa: F401

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.founding_beta import FOUNDING_BETA_SLUG, FOUNDING_BETA_SOURCE
from mykhaya.models import (
    ActionToken,
    BetaEnrollment,
    BetaPendingRegistration,
    BetaProgramme,
    Group,
    HomeSubscription,
    LegalAcceptance,
    LegalDocument,
    LegalDocumentVersion,
    LegalDocumentVersionStatus,
    LegalReacceptanceScope,
    OutboxEvent,
    PlatformSetting,
    SubscriptionPlan,
    SubscriptionProvider,
    TokenPurpose,
    User,
)
from mykhaya.notifications.templates import render_notification_email
from mykhaya.security import derived_token

BETA_TERMS_KEY = "founding_beta_terms"


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _set_signup_mode(value: str) -> None:
    async with SessionFactory() as db:
        row = await db.scalar(select(PlatformSetting).where(PlatformSetting.key == "signup_mode"))
        if row is None:
            db.add(PlatformSetting(key="signup_mode", value={"value": value}))
        else:
            row.value = {"value": value}
        await db.commit()


@pytest.fixture(autouse=True)
async def _beta_open() -> AsyncIterator[None]:
    """Mixed signup mode, an active published Founding Beta Terms document
    and room in the programme; everything restored afterwards (other test
    modules archive adult legal documents and change the signup mode)."""
    async with SessionFactory() as db:
        mode_row = await db.scalar(
            select(PlatformSetting).where(PlatformSetting.key == "signup_mode")
        )
        saved_mode = mode_row.value if mode_row else None
        programme = await db.scalar(
            select(BetaProgramme).where(BetaProgramme.slug == FOUNDING_BETA_SLUG)
        )
        assert programme is not None
        saved_max, programme.max_homes = programme.max_homes, 1_000_000
        document = await db.scalar(select(LegalDocument).where(LegalDocument.key == BETA_TERMS_KEY))
        assert document is not None, "seeded Founding Beta Terms document is missing"
        saved_archived, document.archived_at = document.archived_at, None
        saved_required, document.acceptance_required = document.acceptance_required, True
        await db.commit()
    await _set_signup_mode("mixed")
    yield
    async with SessionFactory() as db:
        programme = await db.scalar(
            select(BetaProgramme).where(BetaProgramme.slug == FOUNDING_BETA_SLUG)
        )
        assert programme is not None
        programme.max_homes = saved_max
        document = await db.scalar(select(LegalDocument).where(LegalDocument.key == BETA_TERMS_KEY))
        assert document is not None
        document.archived_at = saved_archived
        document.acceptance_required = saved_required
        row = await db.scalar(select(PlatformSetting).where(PlatformSetting.key == "signup_mode"))
        if row is not None and saved_mode is not None:
            row.value = saved_mode
        await db.commit()


async def _register(http: AsyncClient, email: str, **extra: Any):
    return await unsafe(
        http,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": "Megan Hales", "password": PASSWORD, **extra},
    )


async def _verify(http: AsyncClient, email: str) -> None:
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        token = await db.scalar(
            select(ActionToken)
            .where(ActionToken.user_id == user.id, ActionToken.purpose == TokenPurpose.verify_email)
            .order_by(ActionToken.created_at.desc())
        )
        assert token is not None
        raw = derived_token(
            token.id, TokenPurpose.verify_email.value, get_settings().secret_key.get_secret_value()
        )
    verified = await unsafe(http, "POST", "/api/v1/auth/verify-email", json={"token": raw})
    assert verified.status_code == 200, verified.text


async def _login(http: AsyncClient, email: str) -> None:
    response = await unsafe(
        http, "POST", "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


async def _beta_user(http: AsyncClient) -> str:
    """Register through the Beta, verify (the emailed link has no Beta
    marker), and sign in."""
    email = _email("beta")
    assert (await _register(http, email, beta=True)).status_code == 202
    await _verify(http, email)
    await _login(http, email)
    return email


async def _accept_current_terms(http: AsyncClient) -> dict[str, Any]:
    terms = (await http.get("/api/v1/beta/continuation")).json()["terms"]
    accepted = await unsafe(
        http,
        "POST",
        "/api/v1/legal/acceptances",
        json={
            "document_key": terms["document_key"],
            "document_version_id": terms["version_id"],
            "context": "beta_enrolment",
            "platform": "web",
        },
    )
    assert accepted.status_code == 201, accepted.text
    return terms


async def _user_id(email: str) -> uuid.UUID:
    async with SessionFactory() as db:
        user_id = await db.scalar(select(User.id).where(User.email == email))
        assert user_id is not None
        return user_id


async def _beta_terms_acceptances(user_id: uuid.UUID) -> int:
    async with SessionFactory() as db:
        count = await db.scalar(
            select(func.count(LegalAcceptance.id))
            .join(
                LegalDocumentVersion, LegalDocumentVersion.id == LegalAcceptance.document_version_id
            )
            .join(LegalDocument, LegalDocument.id == LegalDocumentVersion.document_id)
            .where(LegalAcceptance.user_id == user_id, LegalDocument.key == BETA_TERMS_KEY)
        )
        return int(count or 0)


async def _welcome_emails(user_id: uuid.UUID) -> list[OutboxEvent]:
    async with SessionFactory() as db:
        rows = await db.scalars(
            select(OutboxEvent).where(OutboxEvent.topic == "notification.email")
        )
        return [
            row
            for row in rows
            if row.payload.get("notification_type") == "founding_beta_welcome"
            and row.payload.get("recipient_user_id") == str(user_id)
        ]


# ----------------------------------------------------------- registration


@pytest.mark.asyncio
async def test_beta_registration_creates_the_account_and_records_only_the_beta_intent(
    client: AsyncClient,  # noqa: F811
) -> None:
    email = _email("intent")
    response = await _register(client, email, beta=True)
    assert response.status_code == 202, response.text
    user_id = await _user_id(email)
    async with SessionFactory() as db:
        pending = await db.scalar(
            select(BetaPendingRegistration).where(BetaPendingRegistration.user_id == user_id)
        )
        assert pending is not None
        # No Home details and no Beta contract before verification.
        assert pending.home_name is None and pending.terms_version is None
        assert pending.consumed_at is None
        assert await db.scalar(select(Group.id).where(Group.created_by == user_id)) is None
    assert await _beta_terms_acceptances(user_id) == 0
    assert await _welcome_emails(user_id) == []


@pytest.mark.asyncio
async def test_legacy_beta_fields_only_imply_beta_and_never_create_a_home_early(
    client: AsyncClient,  # noqa: F811
) -> None:
    email = _email("legacy")
    response = await _register(
        client, email, beta_home_name="Early Home", beta_terms_version="anything"
    )
    assert response.status_code == 202, response.text
    user_id = await _user_id(email)
    async with SessionFactory() as db:
        pending = await db.scalar(
            select(BetaPendingRegistration).where(BetaPendingRegistration.user_id == user_id)
        )
        assert pending is not None and pending.home_name is None
        assert await db.scalar(select(Group.id).where(Group.created_by == user_id)) is None


@pytest.mark.asyncio
async def test_normal_registration_is_unchanged_and_records_no_beta_intent(
    client: AsyncClient,  # noqa: F811
) -> None:
    email = _email("normal")
    assert (await _register(client, email)).status_code == 202
    user_id = await _user_id(email)
    async with SessionFactory() as db:
        assert (
            await db.scalar(
                select(BetaPendingRegistration.id).where(BetaPendingRegistration.user_id == user_id)
            )
        ) is None
    await _verify(client, email)
    await _login(client, email)
    state = (await client.get("/api/v1/beta/continuation")).json()
    assert state["pending"] is False and state["enrolled"] is False


@pytest.mark.asyncio
async def test_beta_only_mode_rejects_ordinary_signup_with_a_user_facing_message(
    client: AsyncClient,  # noqa: F811
) -> None:
    await _set_signup_mode("beta_only")
    rejected = await _register(client, _email("ordinary"))
    assert rejected.status_code == 403
    assert "onboarding flow" not in rejected.json()["detail"]
    assert "Founding Beta" in rejected.json()["detail"]
    assert (await _register(client, _email("beta"), beta=True)).status_code == 202


# --------------------------------------------- intent through verification


@pytest.mark.asyncio
async def test_beta_intent_survives_verification_and_first_sign_in(
    client: AsyncClient,  # noqa: F811
) -> None:
    await _beta_user(client)
    state = (await client.get("/api/v1/beta/continuation")).json()
    assert state["pending"] is True
    assert state["enrolled"] is False
    assert state["eligible"] is True and state["home_id"] is None
    assert state["terms"]["document_key"] == BETA_TERMS_KEY
    # Global Terms (accepted at signup) never satisfy the Beta Terms.
    assert state["terms"]["satisfied"] is False


@pytest.mark.asyncio
async def test_no_welcome_email_at_registration_or_verification(
    client: AsyncClient,  # noqa: F811
) -> None:
    email = await _beta_user(client)
    assert await _welcome_emails(await _user_id(email)) == []


# ----------------------------------------------------------------- joining


@pytest.mark.asyncio
async def test_join_requires_the_current_beta_terms_and_creates_nothing_without_them(
    client: AsyncClient,  # noqa: F811
) -> None:
    email = await _beta_user(client)
    response = await unsafe(client, "POST", "/api/v1/beta/join", json={"home_name": "Hales Home"})
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "beta_terms_required"
    user_id = await _user_id(email)
    async with SessionFactory() as db:
        assert await db.scalar(select(Group.id).where(Group.created_by == user_id)) is None
        assert (
            await db.scalar(
                select(BetaEnrollment.id).where(BetaEnrollment.joined_user_id == user_id)
            )
        ) is None
    assert await _welcome_emails(user_id) == []


@pytest.mark.asyncio
async def test_full_journey_grants_lifetime_complimentary_ultimate_and_one_welcome_email(
    client: AsyncClient,  # noqa: F811
) -> None:
    email = await _beta_user(client)
    user_id = await _user_id(email)
    await _accept_current_terms(client)
    state = (await client.get("/api/v1/beta/continuation")).json()
    assert state["terms"]["satisfied"] is True

    joined = await unsafe(client, "POST", "/api/v1/beta/join", json={"home_name": "Hales Home"})
    assert joined.status_code == 200, joined.text
    assert joined.json()["entitlement_source"] == FOUNDING_BETA_SOURCE == "founding_beta_lifetime"
    home_id = uuid.UUID(joined.json()["home_id"])

    async with SessionFactory() as db:
        home = await db.get(Group, home_id)
        assert home is not None and home.name == "Hales Home" and home.created_by == user_id
        subscription = await db.scalar(
            select(HomeSubscription).where(HomeSubscription.group_id == home_id)
        )
        assert subscription is not None
        assert subscription.plan == SubscriptionPlan.ultimate
        assert subscription.provider == SubscriptionProvider.complimentary
        assert subscription.complimentary_source == FOUNDING_BETA_SOURCE
        assert subscription.complimentary_expires_at is None
        assert subscription.external_subscription_id is None
        enrollment = await db.scalar(
            select(BetaEnrollment).where(BetaEnrollment.joined_user_id == user_id)
        )
        assert enrollment is not None and enrollment.home_id == home_id
        pending = await db.scalar(
            select(BetaPendingRegistration).where(BetaPendingRegistration.user_id == user_id)
        )
        assert pending is not None and pending.consumed_at is not None

    # Plan & Billing: complimentary Ultimate as the Founding Beta benefit.
    billing = (await client.get(f"/api/v1/groups/{home_id}/billing")).json()
    assert billing["effective_plan"] == "ultimate"
    assert billing["provider"] == "complimentary"
    assert billing["complimentary_expires_at"] is None
    assert billing["complimentary_source"] == FOUNDING_BETA_SOURCE

    state = (await client.get("/api/v1/beta/continuation")).json()
    assert state["enrolled"] is True and state["pending"] is False
    # The Beta Terms were recorded once, at the Terms step — not again on join.
    assert await _beta_terms_acceptances(user_id) == 1

    emails = await _welcome_emails(user_id)
    assert len(emails) == 1
    assert emails[0].payload["subject"] == "Welcome to the MyKhaya Founding Beta"
    assert "Hales Home is now part of the MyKhaya Founding Beta" in emails[0].payload["body"]
    assert "Welcome to the Founding Beta" in emails[0].payload["html_body"]

    # A retried join is refused and never sends a second welcome email.
    retry = await unsafe(client, "POST", "/api/v1/beta/join", json={"home_name": "Hales Home"})
    assert retry.status_code == 409
    assert len(await _welcome_emails(user_id)) == 1


@pytest.mark.asyncio
async def test_inline_terms_version_on_join_never_duplicates_an_existing_acceptance(
    client: AsyncClient,  # noqa: F811
) -> None:
    email = await _beta_user(client)
    terms = await _accept_current_terms(client)
    joined = await unsafe(
        client,
        "POST",
        "/api/v1/beta/join",
        json={"home_name": "Inline Home", "terms_version": terms["version"]},
    )
    assert joined.status_code == 200, joined.text
    assert await _beta_terms_acceptances(await _user_id(email)) == 1


@pytest.mark.asyncio
async def test_a_new_beta_terms_version_requires_reacceptance(
    client: AsyncClient,  # noqa: F811
) -> None:
    await _beta_user(client)
    await _accept_current_terms(client)
    async with SessionFactory() as db:
        document = await db.scalar(select(LegalDocument).where(LegalDocument.key == BETA_TERMS_KEY))
        assert document is not None
        old = await db.scalar(
            select(LegalDocumentVersion).where(
                LegalDocumentVersion.document_id == document.id,
                LegalDocumentVersion.status == LegalDocumentVersionStatus.published,
                LegalDocumentVersion.is_test.is_(False),
            )
        )
        assert old is not None
        old.status = LegalDocumentVersionStatus.superseded
        sequence = await db.scalar(
            select(func.max(LegalDocumentVersion.version_sequence)).where(
                LegalDocumentVersion.document_id == document.id
            )
        )
        new = LegalDocumentVersion(
            document_id=document.id,
            version_sequence=int(sequence or 0) + 1,
            version="9.9-test",
            status=LegalDocumentVersionStatus.published,
            content_markdown="# Founding Beta Terms\n\nUpdated for test coverage.",
            change_summary="Test re-acceptance.",
            reacceptance_scope=LegalReacceptanceScope.all_existing_users,
            effective_date=date.today(),
            published_at=datetime.now(UTC),
        )
        db.add(new)
        await db.commit()
        old_id, new_id = old.id, new.id
    try:
        state = (await client.get("/api/v1/beta/continuation")).json()
        assert state["terms"]["version"] == "9.9-test"
        assert state["terms"]["satisfied"] is False
        refused = await unsafe(client, "POST", "/api/v1/beta/join", json={"home_name": "Home"})
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "beta_terms_required"
        await _accept_current_terms(client)
        state = (await client.get("/api/v1/beta/continuation")).json()
        assert state["terms"]["satisfied"] is True
    finally:
        async with SessionFactory() as db:
            await db.execute(
                delete(LegalAcceptance).where(LegalAcceptance.document_version_id == new_id)
            )
            await db.execute(delete(LegalDocumentVersion).where(LegalDocumentVersion.id == new_id))
            restored = await db.get(LegalDocumentVersion, old_id)
            assert restored is not None
            restored.status = LegalDocumentVersionStatus.published
            await db.commit()


# ------------------------------------------------------- existing accounts


@pytest.mark.asyncio
async def test_existing_free_home_is_enrolled_in_place(client: AsyncClient) -> None:  # noqa: F811
    email = _email("existing")
    await create_verified_user(client, email, "Existing Owner")
    created = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Existing Home"})
    assert created.status_code == 201, created.text
    home_id = created.json()["id"]

    state = (await client.get("/api/v1/beta/continuation")).json()
    assert state["pending"] is False and state["eligible"] is True
    assert state["home_id"] == home_id and state["home_name"] == "Existing Home"

    await _accept_current_terms(client)
    joined = await unsafe(client, "POST", "/api/v1/beta/join", json={})
    assert joined.status_code == 200, joined.text
    assert joined.json()["home_id"] == home_id  # same Home, not a second one
    async with SessionFactory() as db:
        owned = await db.scalar(
            select(func.count(Group.id)).where(Group.created_by == await _user_id(email))
        )
        assert owned == 1
        subscription = await db.scalar(
            select(HomeSubscription).where(HomeSubscription.group_id == uuid.UUID(home_id))
        )
        assert subscription is not None and subscription.plan == SubscriptionPlan.ultimate
        assert subscription.complimentary_source == FOUNDING_BETA_SOURCE


@pytest.mark.asyncio
async def test_existing_user_without_a_home_creates_a_beta_home(
    client: AsyncClient,  # noqa: F811
) -> None:
    email = _email("homeless")
    await create_verified_user(client, email, "No Home")
    await _accept_current_terms(client)
    joined = await unsafe(client, "POST", "/api/v1/beta/join", json={"home_name": "First Home"})
    assert joined.status_code == 200, joined.text
    async with SessionFactory() as db:
        home = await db.get(Group, uuid.UUID(joined.json()["home_id"]))
        assert home is not None and home.name == "First Home"


@pytest.mark.asyncio
async def test_a_new_home_needs_a_name(client: AsyncClient) -> None:  # noqa: F811
    await _beta_user(client)
    await _accept_current_terms(client)
    response = await unsafe(client, "POST", "/api/v1/beta/join", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_paid_home_public_conversion_stays_blocked(client: AsyncClient) -> None:  # noqa: F811
    email = _email("paid")
    await create_verified_user(client, email, "Paid Owner")
    created = await unsafe(client, "POST", "/api/v1/groups", json={"name": "Paid Home"})
    home_id = uuid.UUID(created.json()["id"])
    async with SessionFactory() as db:
        subscription = await db.scalar(
            select(HomeSubscription).where(HomeSubscription.group_id == home_id)
        )
        assert subscription is not None
        subscription.plan = SubscriptionPlan.family
        provider_before = subscription.provider
        await db.commit()

    state = (await client.get("/api/v1/beta/continuation")).json()
    assert state["eligible"] is False
    await _accept_current_terms(client)
    refused = await unsafe(client, "POST", "/api/v1/beta/join", json={})
    assert refused.status_code == 409
    async with SessionFactory() as db:
        subscription = await db.scalar(
            select(HomeSubscription).where(HomeSubscription.group_id == home_id)
        )
        assert subscription is not None
        assert subscription.plan == SubscriptionPlan.family
        assert subscription.provider == provider_before
        assert subscription.complimentary_source is None


# ------------------------------------------------------------------- email


@pytest.mark.asyncio
async def test_welcome_email_uses_the_branded_shell_and_the_approved_wording() -> None:
    settings = get_settings()
    async with SessionFactory() as db:
        subject, body, html = await render_notification_email(
            db,
            settings,
            "founding_beta_welcome",
            {"first_name": "Megan", "home_name": "Hales Home", "link": "https://example.com/home"},
            footer_note=(
                "You’re receiving this email because Hales Home has joined the "
                "MyKhaya Founding Beta."
            ),
        )
    assert subject == "Welcome to the MyKhaya Founding Beta"
    assert body.startswith("Hi Megan,\n\nYou’re in.")
    assert "Hales Home is now part of the MyKhaya Founding Beta" in body
    assert "• Complimentary MyKhaya Ultimate" in body
    assert body.rstrip().endswith("Welcome Home.\n\nAnthony\nMyKhaya")
    # The existing branded shell: cream background, white rounded card,
    # the hosted logo, the terracotta CTA and the standard footer.
    assert "background:#f2ede3" in html
    assert "border-radius:12px" in html
    assert "/mykhaya-email-logo.png" in html
    assert ">Welcome to the Founding Beta</h1>" in html
    assert "Open MyKhaya</a>" in html and 'href="https://example.com/home"' in html
    assert "background:#e07a5f" in html
    assert "MyKhaya helps families stay connected and organised." in html
    assert "because Hales Home has joined the MyKhaya Founding Beta" in html
