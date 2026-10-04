"""Safe defaults required while importing the API test application."""

import os  # noqa: I001


# Tests must never depend on a production secret or a developer's .env file.
# This value only satisfies Settings validation; it is not used outside tests.
os.environ.setdefault("MYKHAYA_SECRET_KEY", "test-only-secret-key-never-used-in-production-1234")
os.environ.setdefault(
    "MYKHAYA_TRUSTED_HOSTS",
    '["localhost", "127.0.0.1", "api", "api.localhost", "admin.localhost", "status.localhost"]',
)
os.environ.setdefault(
    "MYKHAYA_CORS_ORIGINS",
    '["http://localhost:8080", "http://admin.localhost:8080"]',
)


from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
async def reset_rate_limits() -> AsyncIterator[None]:
    """Give every test a fresh rate-limit budget.

    mykhaya.rate_limit keys its fixed-window counters by client IP, and the ASGI
    test transport presents the same fake peer to every test, so one test's
    requests would otherwise count against every later test's budget (e.g. the
    20-per-hour household invitation limit, long since exhausted by the time the
    last invitation test runs). The production limits themselves are untouched,
    and a test that exercises a limit still sees it enforced within the test.
    """
    from redis.asyncio import Redis
    from redis.exceptions import RedisError

    from mykhaya.config import get_settings

    redis = Redis.from_url(get_settings().redis_url, socket_timeout=2, decode_responses=True)
    try:
        keys = [key async for key in redis.scan_iter("rate:*")]
        if keys:
            await redis.delete(*keys)
    except (RedisError, OSError):
        # No Redis (e.g. a static-only local run): nothing to reset, and any test
        # that really needs the limiter fails on its own connection anyway.
        pass
    finally:
        await redis.aclose()
    yield
