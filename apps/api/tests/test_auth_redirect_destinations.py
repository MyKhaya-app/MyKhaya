"""Safe post-authentication destination regressions for provider sign-in."""

import pytest

from mykhaya.routers.auth import _post_auth_destination


@pytest.mark.parametrize("provider", ["Apple", "Google"])
def test_provider_registration_return_path_uses_account_destination(
    provider: str,
) -> None:
    assert provider in {"Apple", "Google"}
    assert _post_auth_destination("/register?beta=1", True) == "/home"
    assert _post_auth_destination("/register?beta=1", False) == "/onboarding"


def test_provider_preserves_safe_non_registration_return_path() -> None:
    assert (
        _post_auth_destination("/calendar-shares/accept?token=opaque", True)
        == "/calendar-shares/accept?token=opaque"
    )


@pytest.mark.parametrize("unsafe_path", [None, "https://attacker.example", "//attacker.example"])
def test_provider_rejects_unsafe_or_missing_return_path(unsafe_path: str | None) -> None:
    assert _post_auth_destination(unsafe_path, True) == "/home"
    assert _post_auth_destination(unsafe_path, False) == "/onboarding"
