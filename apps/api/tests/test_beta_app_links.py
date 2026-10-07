"""Site-wide iPhone/Android app links, managed in PCC's Founding Beta section
and exposed (only those two values) through the public signup-state."""

from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from test_calendar import client  # noqa: F401
from test_platform_control_centre import (  # noqa: F401
    admin_client,
    admin_factory,
    login,
)
from test_platform_control_centre import unsafe as admin_unsafe

from mykhaya.db import SessionFactory
from mykhaya.founding_beta import FOUNDING_BETA_SLUG
from mykhaya.founding_beta_schemas import BetaProgrammeUpdate
from mykhaya.models import BetaProgramme, PlatformAdministrator, PlatformRole

BASE = {
    "max_homes": 100,
    "waitlist_enabled": True,
    "show_remaining_publicly": False,
    "invitation_ttl_days": 7,
    "terms_version": "test-terms",
    "reason": "Update the app download links",
}

TESTFLIGHT = "https://testflight.apple.com/join/AbCdEf12"
APP_STORE = "https://apps.apple.com/gb/app/mykhaya/id1234567890"
PLAY_TESTING = "https://play.google.com/apps/testing/app.mykhaya"


# ------------------------------------------------------------------ validation


@pytest.mark.parametrize("url", [TESTFLIGHT, APP_STORE, "https://APPS.apple.com/app/id1"])
def test_iphone_link_accepts_testflight_and_app_store(url: str) -> None:
    assert BetaProgrammeUpdate(**BASE, ios_app_url=url).ios_app_url == url


@pytest.mark.parametrize(
    "url",
    [
        "http://testflight.apple.com/join/AbCdEf12",  # not https
        "https://play.google.com/store/apps/details?id=app.mykhaya",  # wrong host
        "https://testflight.apple.com.evil.example/join/x",  # look-alike host
        "https://user:pass@apps.apple.com/app/id1",  # credentials
        "testflight.apple.com/join/AbCdEf12",  # no scheme
        "javascript:alert(1)",
    ],
)
def test_iphone_link_rejects_anything_else(url: str) -> None:
    with pytest.raises(ValidationError):
        BetaProgrammeUpdate(**BASE, ios_app_url=url)


@pytest.mark.parametrize(
    "url",
    [
        PLAY_TESTING,
        "https://play.google.com/store/apps/details?id=app.mykhaya",
        "https://example.com/apk",
    ],
)
def test_android_link_accepts_any_https_url(url: str) -> None:
    assert BetaProgrammeUpdate(**BASE, android_app_url=url).android_app_url == url


@pytest.mark.parametrize(
    "url", ["http://play.google.com/apps/testing/app.mykhaya", "ftp://example.com/x", "not a url"]
)
def test_android_link_rejects_non_https(url: str) -> None:
    with pytest.raises(ValidationError):
        BetaProgrammeUpdate(**BASE, android_app_url=url)


@pytest.mark.parametrize("empty", ["", "   ", None])
def test_both_links_may_be_empty(empty: str | None) -> None:
    body = BetaProgrammeUpdate(**BASE, ios_app_url=empty, android_app_url=empty)
    assert body.ios_app_url is None and body.android_app_url is None


def test_links_are_trimmed() -> None:
    assert BetaProgrammeUpdate(**BASE, ios_app_url=f"  {TESTFLIGHT} ").ios_app_url == TESTFLIGHT


# ------------------------------------------------------------- API round trip


@pytest.fixture
async def _restore_programme() -> AsyncIterator[None]:
    async with SessionFactory() as db:
        programme = await db.scalar(
            select(BetaProgramme).where(BetaProgramme.slug == FOUNDING_BETA_SLUG)
        )
        assert programme is not None
        saved = {
            key: getattr(programme, key)
            for key in (*[k for k in BASE if k != "reason"], "ios_app_url", "android_app_url")
        }
    yield
    async with SessionFactory() as db:
        programme = await db.scalar(
            select(BetaProgramme).where(BetaProgramme.slug == FOUNDING_BETA_SLUG)
        )
        assert programme is not None
        for key, value in saved.items():
            setattr(programme, key, value)
        await db.commit()


async def _current_settings(pcc: AsyncClient) -> dict[str, object]:
    current = (await pcc.get("/api/v1/platform/beta/programme")).json()
    return {key: current[key] for key in BASE if key != "reason"} | {"reason": BASE["reason"]}


@pytest.mark.asyncio
@pytest.mark.usefixtures("_restore_programme")
async def test_pcc_saves_links_and_public_signup_state_exposes_only_the_two_links(
    client: AsyncClient,  # noqa: F811
    admin_client: AsyncClient,  # noqa: F811
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],  # noqa: F811
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    settings = await _current_settings(admin_client)

    saved = await admin_unsafe(
        admin_client,
        "PATCH",
        "/api/v1/platform/beta/programme",
        json={**settings, "ios_app_url": TESTFLIGHT, "android_app_url": PLAY_TESTING},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["ios_app_url"] == TESTFLIGHT
    assert saved.json()["android_app_url"] == PLAY_TESTING

    public = (await client.get("/api/v1/public/signup-state")).json()
    assert public["ios_app_url"] == TESTFLIGHT
    assert public["android_app_url"] == PLAY_TESTING
    # Nothing else from the programme leaks through the public endpoint.
    assert set(public) == {
        "signup_mode",
        "registration_open",
        "invitation_required",
        "normal_signup_available",
        "beta_joining_available",
        "waitlist_available",
        "joinable_count",
        "beta_terms_version",
        "ios_app_url",
        "android_app_url",
    }

    # Omitting the links leaves them unchanged; sending "" clears them.
    unchanged = await admin_unsafe(
        admin_client, "PATCH", "/api/v1/platform/beta/programme", json=settings
    )
    assert unchanged.json()["ios_app_url"] == TESTFLIGHT
    cleared = await admin_unsafe(
        admin_client,
        "PATCH",
        "/api/v1/platform/beta/programme",
        json={**settings, "ios_app_url": "", "android_app_url": ""},
    )
    assert cleared.json()["ios_app_url"] is None and cleared.json()["android_app_url"] is None
    public = (await client.get("/api/v1/public/signup-state")).json()
    assert public["ios_app_url"] is None and public["android_app_url"] is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("_restore_programme")
async def test_pcc_rejects_an_invalid_iphone_link(
    admin_client: AsyncClient,  # noqa: F811
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],  # noqa: F811
) -> None:
    admin = await admin_factory(PlatformRole.owner)
    await login(admin_client, admin)
    settings = await _current_settings(admin_client)
    rejected = await admin_unsafe(
        admin_client,
        "PATCH",
        "/api/v1/platform/beta/programme",
        json={**settings, "ios_app_url": "https://example.com/app"},
    )
    assert rejected.status_code == 422


@pytest.mark.asyncio
@pytest.mark.usefixtures("_restore_programme")
async def test_support_role_cannot_change_links(
    admin_client: AsyncClient,  # noqa: F811
    admin_factory: Callable[[PlatformRole], Awaitable[PlatformAdministrator]],  # noqa: F811
) -> None:
    admin = await admin_factory(PlatformRole.support)
    await login(admin_client, admin)
    settings = await _current_settings(admin_client)
    forbidden = await admin_unsafe(
        admin_client,
        "PATCH",
        "/api/v1/platform/beta/programme",
        json={**settings, "ios_app_url": TESTFLIGHT},
    )
    assert forbidden.status_code == 403
