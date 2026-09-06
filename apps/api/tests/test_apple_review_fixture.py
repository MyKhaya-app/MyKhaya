import pytest

from mykhaya.apple_review_fixture import (
    FIXTURE_EMAIL,
    FIXTURE_HOME_CODE,
    FIXTURE_HOME_NAME,
    FIXTURE_PASSWORD_ENV,
    _password,
    fixture_event_specs,
    fixture_meal_dates,
)
from mykhaya.models import PermissionProfile, Role
from mykhaya.security import password_hash


def test_fixture_identity_is_stable_and_not_platform_admin():
    assert FIXTURE_EMAIL == "apple-review@mykhaya.app"
    assert FIXTURE_HOME_NAME == "Apple Review Home"
    assert FIXTURE_HOME_CODE == "ARVHOME27"
    assert "platform" not in FIXTURE_EMAIL


def test_missing_review_password_fails_without_fallback(monkeypatch):
    monkeypatch.delenv(FIXTURE_PASSWORD_ENV, raising=False)
    with pytest.raises(RuntimeError, match=FIXTURE_PASSWORD_ENV):
        _password()


def test_fixture_dates_are_relative_and_cover_review_sections():
    from datetime import date

    today = date(2026, 9, 6)
    specs = fixture_event_specs(today)
    assert [spec[1] for spec in specs[:2]] == [today, today]
    assert specs[2][1] == date(2026, 9, 7)
    assert specs[3][1] == date(2026, 9, 8)
    assert specs[4][1] == date(2026, 9, 10)


def test_fixture_meals_are_monday_through_thursday():
    from datetime import date

    dates = fixture_meal_dates(date(2026, 9, 6))
    assert [day.weekday() for day in dates] == [0, 1, 2, 3]


def test_review_password_uses_the_application_hasher():
    raw = "test-only-review-secret"
    stored = password_hash.hash(raw)
    assert stored != raw
    assert password_hash.verify(raw, stored)


def test_review_account_is_a_normal_home_admin_not_platform_admin():
    assert Role.owner.value == "owner"
    assert PermissionProfile.home_admin.value == "home_admin"
    assert not hasattr(Role, "platform_admin")
