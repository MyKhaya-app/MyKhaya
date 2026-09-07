import pytest

from mykhaya.apple_review_fixture import (
    FIXTURE_EMAIL,
    FIXTURE_HOME_CODE,
    FIXTURE_HOME_NAME,
    FIXTURE_PASSWORD_ENV,
    _password,
)
from mykhaya.models import ManagedDemoStatus, ManagedDemoType, PermissionProfile, Role
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


def test_review_password_uses_the_application_hasher():
    raw = "test-only-review-secret"
    stored = password_hash.hash(raw)
    assert stored != raw
    assert password_hash.verify(raw, stored)


def test_review_account_is_a_normal_home_admin_not_platform_admin():
    assert Role.owner.value == "owner"
    assert PermissionProfile.home_admin.value == "home_admin"
    assert not hasattr(Role, "platform_admin")


def test_managed_demo_lifecycle_contract_is_explicit():
    assert {item.value for item in ManagedDemoType} >= {"apple_review", "demo", "qa_test"}
    assert {item.value for item in ManagedDemoStatus} == {"enabled", "disabled", "expired"}


def test_managed_demo_cli_uses_shared_service_entrypoints():
    from pathlib import Path

    source = Path(__file__).parents[1].joinpath("mykhaya", "apple_review_fixture.py").read_text()
    assert "ManagedDemoService.create" in source
    assert "ManagedDemoService.refresh_template" in source
    assert "ManagedDemoService.delete" in source


def test_managed_demo_service_has_scoped_security_guards():
    from pathlib import Path

    source = Path(__file__).parents[1].joinpath("mykhaya", "managed_demo_homes.py").read_text()
    create_source = source[
        source.index("async def create") : source.index("async def seed_template")
    ]
    delete_source = source[source.index("async def delete") :]
    reset_source = source[
        source.index("async def reset_password") : source.index("async def set_expiry")
    ]
    refresh_source = source[
        source.index("async def refresh_template") : source.index("async def register")
    ]
    assert "Refusing to adopt an existing customer account" in create_source
    assert "Refusing to delete an owner account used outside this fixture" in delete_source
    assert "row.owner_user_id" in reset_source
    assert "row.home_id" in refresh_source


def test_expiry_and_refresh_contract_preserves_lifecycle_state():
    from pathlib import Path

    source = Path(__file__).parents[1].joinpath("mykhaya", "managed_demo_homes.py").read_text()
    expiry_source = source[source.index("async def set_expiry") : source.index("async def refresh")]
    refresh_source = source[
        source.index("async def refresh_template") : source.index("async def register")
    ]
    assert "owner.is_active = True" not in expiry_source
    assert "set_enabled" not in refresh_source
    assert "row.expires_at" not in refresh_source
