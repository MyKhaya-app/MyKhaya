"""Founding Beta availability: the public signup state and the waitlist
endpoint answer from one rule (mykhaya.founding_beta.beta_availability), so the
waitlist is offered exactly when it accepts sign-ups. Also: invitation-only is
enforced on POST /beta/join, and the waitlist response never reveals whether an
email is already listed."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from test_calendar import PASSWORD, client, unsafe  # noqa: F401

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.founding_beta import FOUNDING_BETA_SLUG
from mykhaya.main import app
from mykhaya.models import (
    ActionToken,
    BetaProgramme,
    BetaWaitlistEntry,
    BetaWaitlistStatus,
    LegalDocument,
    PlatformSetting,
    TokenPurpose,
    User,
)
from mykhaya.security import derived_token

BETA_TERMS_KEY = "founding_beta_terms"
SETTING_KEYS = ("signup_mode", "invite_only_mode", "registration_enabled")


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _set(key: str, value: Any) -> None:
    async with SessionFactory() as db:
        row = await db.scalar(select(PlatformSetting).where(PlatformSetting.key == key))
        if row is None:
            db.add(PlatformSetting(key=key, value={"value": value}))
        else:
            row.value = {"value": value}
        await db.commit()


async def _programme_settings(*, places_free: bool, waitlist_enabled: bool) -> None:
    async with SessionFactory() as db:
        programme = await db.scalar(
            select(BetaProgramme).where(BetaProgramme.slug == FOUNDING_BETA_SLUG)
        )
        assert programme is not None
        programme.max_homes = 1_000_000 if places_free else 0
        programme.waitlist_enabled = waitlist_enabled
        await db.commit()


@pytest.fixture(autouse=True)
async def _isolated_beta() -> AsyncIterator[None]:
    """Each test starts with nobody waiting on the real programme and finishes
    with the programme, settings and pre-existing waitlist exactly as found;
    entries a test adds are removed so later modules (which join the Beta and
    rely on an empty waitlist) are unaffected."""
    async with SessionFactory() as db:
        programme = await db.scalar(
            select(BetaProgramme).where(BetaProgramme.slug == FOUNDING_BETA_SLUG)
        )
        assert programme is not None
        saved_programme = (programme.max_homes, programme.waitlist_enabled)
        rows = {
            key: await db.scalar(select(PlatformSetting).where(PlatformSetting.key == key))
            for key in SETTING_KEYS
        }
        saved_settings = {key: (row.value if row else None) for key, row in rows.items()}
        before = set(await db.scalars(select(BetaWaitlistEntry.id)))
        parked = list(
            await db.scalars(
                select(BetaWaitlistEntry).where(
                    BetaWaitlistEntry.programme_id == programme.id,
                    BetaWaitlistEntry.status == BetaWaitlistStatus.waiting,
                )
            )
        )
        for entry in parked:
            entry.status = BetaWaitlistStatus.removed
        document = await db.scalar(select(LegalDocument).where(LegalDocument.key == BETA_TERMS_KEY))
        assert document is not None
        saved_document = (document.archived_at, document.acceptance_required)
        document.archived_at, document.acceptance_required = None, True
        await db.commit()
        parked_ids = [entry.id for entry in parked]
    for key in ("invite_only_mode", "registration_enabled"):
        async with SessionFactory() as db:
            await db.execute(delete(PlatformSetting).where(PlatformSetting.key == key))
            await db.commit()
    yield
    app.dependency_overrides.pop(get_settings, None)
    async with SessionFactory() as db:
        programme = await db.scalar(
            select(BetaProgramme).where(BetaProgramme.slug == FOUNDING_BETA_SLUG)
        )
        assert programme is not None
        programme.max_homes, programme.waitlist_enabled = saved_programme
        added = set(await db.scalars(select(BetaWaitlistEntry.id))) - before
        if added:
            await db.execute(delete(BetaWaitlistEntry).where(BetaWaitlistEntry.id.in_(added)))
        for entry_id in parked_ids:
            entry = await db.get(BetaWaitlistEntry, entry_id)
            if entry is not None:
                entry.status = BetaWaitlistStatus.waiting
        document = await db.scalar(select(LegalDocument).where(LegalDocument.key == BETA_TERMS_KEY))
        assert document is not None
        document.archived_at, document.acceptance_required = saved_document
        for key, value in saved_settings.items():
            row = await db.scalar(select(PlatformSetting).where(PlatformSetting.key == key))
            if value is None:
                if row is not None:
                    await db.delete(row)
            elif row is None:
                db.add(PlatformSetting(key=key, value=value))
            else:
                row.value = value
        await db.commit()


def _entry(email: str) -> dict[str, Any]:
    return {"name": "Sam Tester", "email": email, "country": "GB", "marketing_consent": False}


async def _signup_state(http: AsyncClient) -> dict[str, Any]:
    response = await http.get("/api/v1/public/signup-state")
    assert response.status_code == 200, response.text
    return response.json()


async def _join_waitlist(http: AsyncClient, email: str):
    return await unsafe(http, "POST", "/api/v1/public/beta/waitlist", json=_entry(email))


async def _waitlist_rows(email: str) -> int:
    async with SessionFactory() as db:
        return int(
            await db.scalar(
                select(func.count(BetaWaitlistEntry.id)).where(
                    BetaWaitlistEntry.normalized_email == email
                )
            )
            or 0
        )


# ------------------------------------------- signup state and POST agree


MODES = [
    # (label, signup_mode, invite_only, registration_enabled, places_free, waitlist_enabled,
    #  expected waitlist_available)
    ("beta open to the public", "beta_only", False, True, True, True, False),
    ("beta full, waitlist on", "beta_only", False, True, False, True, True),
    ("beta full, waitlist off", "beta_only", False, True, False, False, False),
    ("normal", "normal", False, True, True, True, False),
    ("mixed, beta open", "mixed", False, True, True, True, False),
    ("mixed, beta full, waitlist on", "mixed", False, True, False, True, True),
    ("closed, places free, waitlist on", "closed", False, True, True, True, True),
    ("closed, places full, waitlist on", "closed", False, True, False, True, True),
    ("closed, waitlist off", "closed", False, True, True, False, False),
    ("registration paused, waitlist on", "beta_only", False, False, False, True, False),
    ("invitation-only, places free, waitlist on", "beta_only", True, True, True, True, True),
    ("invitation-only, places free, waitlist off", "beta_only", True, True, True, False, False),
    ("invitation-only, places full, waitlist on", "beta_only", True, True, False, True, True),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "mode", "invite_only", "enabled", "places_free", "waitlist", "expected"),
    MODES,
    ids=[mode[0] for mode in MODES],
)
async def test_signup_state_and_waitlist_post_always_agree(
    client: AsyncClient,  # noqa: F811
    label: str,
    mode: str,
    invite_only: bool,
    enabled: bool,
    places_free: bool,
    waitlist: bool,
    expected: bool,
) -> None:
    await _set("signup_mode", mode)
    await _set("invite_only_mode", invite_only)
    await _set("registration_enabled", enabled)
    await _programme_settings(places_free=places_free, waitlist_enabled=waitlist)

    state = await _signup_state(client)
    assert state["waitlist_available"] is expected, label

    email = _email("agree")
    response = await _join_waitlist(client, email)
    if expected:
        assert response.status_code == 202, response.text
        assert response.json() == {"accepted": True, "status": "waiting"}
        assert await _waitlist_rows(email) == 1
    else:
        assert response.status_code == 409, response.text
        assert await _waitlist_rows(email) == 0


@pytest.mark.asyncio
async def test_invitation_only_with_places_free_keeps_beta_places_open_but_offers_the_waitlist(
    client: AsyncClient,  # noqa: F811
) -> None:
    await _set("signup_mode", "beta_only")
    await _set("invite_only_mode", True)
    await _programme_settings(places_free=True, waitlist_enabled=True)

    state = await _signup_state(client)
    assert state["invitation_required"] is True
    assert state["beta_joining_available"] is True
    assert state["waitlist_available"] is True


@pytest.mark.asyncio
async def test_deployment_invitation_only_also_opens_the_waitlist_with_places_free(
    client: AsyncClient,  # noqa: F811
) -> None:
    await _set("signup_mode", "beta_only")
    await _programme_settings(places_free=True, waitlist_enabled=True)
    app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(
        update={"registration_mode": "invitation_only"}
    )

    state = await _signup_state(client)
    assert state["invitation_required"] is True
    assert state["waitlist_available"] is True
    assert (await _join_waitlist(client, _email("deploy-invite"))).status_code == 202


# ----------------------------------------------------------- no enumeration


@pytest.mark.asyncio
async def test_waitlist_response_is_identical_for_new_and_already_listed_emails(
    client: AsyncClient,  # noqa: F811
) -> None:
    await _set("signup_mode", "beta_only")
    await _programme_settings(places_free=False, waitlist_enabled=True)
    email = _email("enumerate")

    first = await _join_waitlist(client, email)
    again = await _join_waitlist(client, email.upper())
    assert first.status_code == again.status_code == 202
    assert first.json() == again.json() == {"accepted": True, "status": "waiting"}
    assert await _waitlist_rows(email) == 1

    # Even once an entry has moved on (e.g. invited), the answer is the same.
    async with SessionFactory() as db:
        entry = await db.scalar(
            select(BetaWaitlistEntry).where(BetaWaitlistEntry.normalized_email == email)
        )
        assert entry is not None
        entry.status = BetaWaitlistStatus.invited
        await db.commit()
    invited = await _join_waitlist(client, email)
    assert invited.status_code == 202
    assert invited.json() == first.json()


@pytest.mark.asyncio
async def test_daily_cap_refuses_new_and_existing_emails_alike(
    client: AsyncClient,  # noqa: F811
) -> None:
    await _set("signup_mode", "beta_only")
    await _programme_settings(places_free=False, waitlist_enabled=True)
    listed = _email("listed")
    assert (await _join_waitlist(client, listed)).status_code == 202

    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    async with SessionFactory() as db:
        programme_id = await db.scalar(
            select(BetaProgramme.id).where(BetaProgramme.slug == FOUNDING_BETA_SLUG)
        )
        added_today = int(
            await db.scalar(
                select(func.count(BetaWaitlistEntry.id)).where(
                    BetaWaitlistEntry.programme_id == programme_id,
                    BetaWaitlistEntry.created_at >= day_start,
                )
            )
            or 0
        )
    assert added_today >= 1
    app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(
        update={"beta_waitlist_daily_cap": added_today}
    )

    fresh = _email("over-cap")
    new_response = await _join_waitlist(client, fresh)
    existing_response = await _join_waitlist(client, listed)
    assert new_response.status_code == existing_response.status_code == 429
    assert new_response.json() == existing_response.json()
    assert "Retry-After" in new_response.headers
    assert await _waitlist_rows(fresh) == 0


# ------------------------------------------------- /beta/join and invitations


async def _verified_signed_in_user(http: AsyncClient) -> None:
    email = _email("joiner")
    registered = await unsafe(
        http,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": "Jo Joiner", "password": PASSWORD},
    )
    assert registered.status_code == 202, registered.text
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
    assert (
        await unsafe(http, "POST", "/api/v1/auth/verify-email", json={"token": raw})
    ).status_code == 200
    login = await unsafe(
        http, "POST", "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text


async def _join_with_current_terms(http: AsyncClient):
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
    return await unsafe(http, "POST", "/api/v1/beta/join", json={"home_name": "Joiner Home"})


@pytest.mark.asyncio
async def test_beta_join_rejects_an_uninvited_account_when_the_control_centre_requires_invitations(
    client: AsyncClient,  # noqa: F811
) -> None:
    await _set("signup_mode", "mixed")
    await _programme_settings(places_free=True, waitlist_enabled=True)
    await _verified_signed_in_user(client)
    await _set("invite_only_mode", True)

    response = await _join_with_current_terms(client)
    assert response.status_code == 403, response.text
    assert "invitation-only" in response.text


@pytest.mark.asyncio
async def test_beta_join_rejects_an_uninvited_account_when_the_deployment_requires_invitations(
    client: AsyncClient,  # noqa: F811
) -> None:
    await _set("signup_mode", "mixed")
    await _programme_settings(places_free=True, waitlist_enabled=True)
    await _verified_signed_in_user(client)
    app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(
        update={"registration_mode": "invitation_only"}
    )

    response = await _join_with_current_terms(client)
    assert response.status_code == 403, response.text
    assert "invitation-only" in response.text


@pytest.mark.asyncio
async def test_beta_join_still_works_without_an_invitation_when_none_is_required(
    client: AsyncClient,  # noqa: F811
) -> None:
    await _set("signup_mode", "mixed")
    await _programme_settings(places_free=True, waitlist_enabled=True)
    await _verified_signed_in_user(client)

    response = await _join_with_current_terms(client)
    assert response.status_code == 200, response.text
