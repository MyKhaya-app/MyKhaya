"""Rate-limit bucket identity: per-client-IP, resolved through trusted proxies only.

A login throttle that sees every user as the same address (a proxy, a Docker
bridge, loopback) would lock everybody out after a handful of attempts. These
tests pin the bucket key, the trusted-proxy resolution it depends on, and that
the production/dev defaults are not the test stack's.
"""

import secrets
from collections.abc import AsyncIterator

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from mykhaya.config import Settings, get_settings
from mykhaya.main import app
from mykhaya.rate_limit import enforce_rate_limit

PROXY = "172.16.0.2"


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request(
        {"type": "http", "method": "POST", "path": "/", "headers": headers, "client": (peer, 1)}
    )


def _settings(**update: object) -> Settings:
    return get_settings().model_copy(update={"trusted_proxy_cidrs": ["172.16.0.0/24"], **update})


def _bucket() -> str:
    return f"test-{secrets.token_hex(6)}"


async def _hit(request: Request, settings: Settings, bucket: str, limit: int) -> int:
    try:
        await enforce_rate_limit(request, settings, bucket, limit, 60)
    except HTTPException as exc:
        return exc.status_code
    return 200


@pytest.mark.asyncio
async def test_repeated_attempts_from_one_client_are_throttled_with_retry_after() -> None:
    bucket, settings = _bucket(), _settings()
    request = _request("203.0.113.10")
    assert [await _hit(request, settings, bucket, 3) for _ in range(3)] == [200, 200, 200]
    with pytest.raises(HTTPException) as blocked:
        await enforce_rate_limit(request, settings, bucket, 3, 60)
    assert blocked.value.status_code == 429
    assert blocked.value.headers == {"Retry-After": "60"}


@pytest.mark.asyncio
async def test_distinct_client_ips_do_not_share_a_bucket() -> None:
    bucket, settings = _bucket(), _settings()
    noisy = _request("203.0.113.10")
    for _ in range(3):
        await _hit(noisy, settings, bucket, 3)
    assert await _hit(noisy, settings, bucket, 3) == 429
    assert await _hit(_request("203.0.113.11"), settings, bucket, 3) == 200


@pytest.mark.asyncio
async def test_clients_behind_a_trusted_proxy_are_bucketed_by_forwarded_address() -> None:
    bucket, settings = _bucket(), _settings()
    first = _request(PROXY, "198.51.100.1")
    for _ in range(3):
        await _hit(first, settings, bucket, 3)
    assert await _hit(first, settings, bucket, 3) == 429
    # Same proxy peer, different real client: unaffected.
    assert await _hit(_request(PROXY, "198.51.100.2"), settings, bucket, 3) == 200


@pytest.mark.asyncio
async def test_forwarded_header_from_an_untrusted_peer_cannot_dodge_or_frame_a_bucket() -> None:
    bucket, settings = _bucket(), _settings()
    attacker = "203.0.113.50"
    for index in range(3):
        # Rotating a spoofed X-Forwarded-For does not mint fresh buckets...
        await _hit(_request(attacker, f"198.51.100.{index}"), settings, bucket, 3)
    assert await _hit(_request(attacker, "198.51.100.99"), settings, bucket, 3) == 429
    # ...and cannot be used to exhaust a victim's bucket either.
    assert await _hit(_request("203.0.113.51", "203.0.113.50"), settings, bucket, 3) == 200


@pytest.mark.asyncio
async def test_untrusted_proxy_collapses_every_client_into_one_bucket() -> None:
    """The failure mode behind mass 429s: with the proxy missing from the trusted
    list, resolution falls back to the proxy's own address for every user."""
    bucket = _bucket()
    settings = _settings(trusted_proxy_cidrs=["10.99.0.0/24"])  # does not include PROXY
    for index in range(3):
        await _hit(_request(PROXY, f"198.51.100.{index}"), settings, bucket, 3)
    assert await _hit(_request(PROXY, "198.51.100.200"), settings, bucket, 3) == 429


def test_dev_and_production_defaults_are_not_the_test_stack_values() -> None:
    # Field defaults, not an instance: the test container deliberately overrides
    # these via environment (compose.yml's `test` service), which is exactly the
    # configuration that must never become the default anywhere else.
    fields = Settings.model_fields
    assert fields["rate_limit_login"].default == 10
    assert fields["rate_limit_register"].default == 5
    assert fields["trusted_proxy_cidrs"].default == []


@pytest.fixture
async def mobile_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app, client=(PROXY, 44000)),
        base_url="http://localhost:8080",
        headers={"Origin": "http://localhost:8080"},
    ) as value:
        yield value


@pytest.mark.asyncio
async def test_mobile_login_is_throttled_per_client_ip_and_unrelated_users_are_not_blocked(
    mobile_client: AsyncClient,
) -> None:
    settings = _settings(rate_limit_login=2)
    app.dependency_overrides[get_settings] = lambda: settings
    unique = secrets.token_hex(4)
    ip_a, ip_b = f"198.51.{secrets.randbelow(200)}.{secrets.randbelow(200) + 1}", "198.51.100.250"

    async def attempt(ip: str):
        return await mobile_client.post(
            "/api/v1/auth/mobile/login",
            json={"email": f"nobody-{unique}@example.com", "password": "Wrong password 123!"},
            headers={"X-Forwarded-For": ip},
        )

    try:
        statuses_a = [(await attempt(ip_a)).status_code for _ in range(3)]
        assert statuses_a == [401, 401, 429]  # the third attempt trips the limiter
        # A different user behind the same proxy still gets a normal answer.
        assert (await attempt(ip_b)).status_code == 401
    finally:
        app.dependency_overrides.pop(get_settings, None)
