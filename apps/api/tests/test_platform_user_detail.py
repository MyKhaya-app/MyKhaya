"""Focused PCC user-detail regressions."""

from mykhaya.routers.platform import _beta_subscription_summary


def test_beta_user_detail_defaults_missing_subscription_to_free() -> None:
    assert _beta_subscription_summary(None) == (None, "free")
