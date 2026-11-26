from types import SimpleNamespace
from uuid import uuid4

import pytest

from mykhaya.driveway_dvla_controls import (
    DvlaBudgetExceeded,
    DvlaRedisUnavailable,
    enforce_request_budget,
    refresh_lock,
)


class FakeRedis:
    values: dict[str, str] = {}
    counts: dict[str, int] = {}

    async def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key, seconds):
        return True

    async def eval(self, script, count, key, token):
        if self.values.get(key) == token:
            del self.values[key]
            return 1
        return 0

    async def aclose(self):
        return None


@pytest.fixture
def settings():
    return SimpleNamespace(
        redis_url="redis://test",
        environment="test",
        dvla_refresh_lock_seconds=30,
        dvla_request_budget_per_second=1,
    )


@pytest.mark.asyncio
async def test_atomic_cleanup_does_not_delete_replacement_lock(monkeypatch, settings):
    fake = FakeRedis()
    monkeypatch.setattr("mykhaya.driveway_dvla_controls._redis", lambda _: fake)
    vehicle_id = uuid4()
    async with refresh_lock(settings, vehicle_id):
        pass
    async with refresh_lock(settings, vehicle_id) as acquired:
        assert acquired is True
        key = f"mykhaya:test:driveway:dvla:refresh:{vehicle_id}"
        replacement = fake.values[key]
        await fake.eval("compare-delete", 1, key, "old-token")
        assert fake.values[key] == replacement


@pytest.mark.asyncio
async def test_budget_is_shared_and_refuses_second_request(monkeypatch, settings):
    fake = FakeRedis()
    monkeypatch.setattr("mykhaya.driveway_dvla_controls._redis", lambda _: fake)
    await enforce_request_budget(settings)
    with pytest.raises(DvlaBudgetExceeded):
        await enforce_request_budget(settings)


@pytest.mark.asyncio
async def test_redis_failure_fails_closed(monkeypatch, settings):
    class BrokenRedis(FakeRedis):
        async def set(self, *args, **kwargs):
            raise ConnectionError("redis unavailable")

    monkeypatch.setattr("mykhaya.driveway_dvla_controls._redis", lambda _: BrokenRedis())
    with pytest.raises(DvlaRedisUnavailable):
        async with refresh_lock(settings, uuid4()):
            pass


@pytest.mark.asyncio
async def test_provider_exception_is_not_misclassified_as_redis_failure(monkeypatch, settings):
    fake = FakeRedis()
    monkeypatch.setattr("mykhaya.driveway_dvla_controls._redis", lambda _: fake)
    with pytest.raises(RuntimeError, match="provider failure"):
        async with refresh_lock(settings, uuid4()):
            raise RuntimeError("provider failure")
