from types import SimpleNamespace

import pytest

from mykhaya import browser_preauth


class FakeRedis:
    values: dict[str, str] = {}
    expiries: dict[str, int] = {}

    @classmethod
    def from_url(cls, *_args, **_kwargs):
        return cls()

    async def set(self, key, value, **_kwargs):
        self.values[key] = value
        self.expiries[key] = _kwargs["ex"]
        return True

    async def getdel(self, key):
        return self.values.pop(key, None)

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_browser_pre_auth_is_opaque_single_use_and_expires_via_redis_ttl(monkeypatch):
    FakeRedis.values.clear()
    FakeRedis.expiries.clear()
    monkeypatch.setattr(browser_preauth, "Redis", FakeRedis)
    settings = SimpleNamespace(redis_url="redis://test", secret_key=SimpleNamespace())

    transaction_id = await browser_preauth.create_browser_pre_auth(
        settings,
        user_id="user-1",
        method="apple",
        destination="/home",
    )
    assert transaction_id
    assert (
        FakeRedis.expiries[next(iter(FakeRedis.expiries))]
        == browser_preauth.TRANSACTION_TTL_SECONDS
    )
    assert "user-1" not in transaction_id
    assert "token" not in FakeRedis.values[next(iter(FakeRedis.values))]

    state = await browser_preauth.consume_browser_pre_auth(settings, transaction_id)
    assert state is not None
    assert state.user_id == "user-1"
    assert state.method == "apple"
    assert await browser_preauth.consume_browser_pre_auth(settings, transaction_id) is None
