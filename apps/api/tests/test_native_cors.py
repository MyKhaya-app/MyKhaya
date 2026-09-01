"""Regression coverage for native iOS login silently failing: the Capacitor
shell is a *live-frontend* WKWebView (loads the real dev.mykhaya.app/
mykhaya.app page), so its JS calls to api.dev.mykhaya.app/api.mykhaya.app
(ADR 0010) are genuine cross-origin fetches from a loaded web page — fully
CORS-subject, complete with preflight, exactly like a browser tab. The
CORSMiddleware's `allow_headers` list previously omitted the
X-MyKhaya-Client/-Platform/-App-Version headers NativeMyKhayaClient attaches
to every request (packages/api-client/src/native-client.ts's clientHeaders
option), so the browser's CORS preflight for every native login/session
request failed silently and the real POST never reached the server —
surfacing only as a generic "We couldn't sign you in" with no HTTP request
ever completing. See mykhaya.main's CORSMiddleware config and
mykhaya.config.Settings.native_api_url's docstring for the full story.
"""

from collections.abc import AsyncIterator
import os

# This module imports the application during collection. Supply only a
# deterministic test configuration before that import; this is never a
# production credential and avoids requiring a developer's .env file in CI.
os.environ["MYKHAYA_ENVIRONMENT"] = "test"
os.environ["MYKHAYA_SECRET_KEY"] = "test-only-native-cors-secret-32-bytes!!"
os.environ["MYKHAYA_PUBLIC_WEB_URL"] = "https://mykhaya.app"
os.environ["MYKHAYA_NATIVE_API_URL"] = "https://api.mykhaya.app"
os.environ["MYKHAYA_CORS_ORIGINS"] = '["https://mykhaya.app"]'
os.environ["MYKHAYA_TRUSTED_HOSTS"] = '["mykhaya.app","api.mykhaya.app"]'

import pytest
from httpx import ASGITransport, AsyncClient

from mykhaya.main import app

ORIGIN = "https://mykhaya.app"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


def _allowed_origin() -> str:
    return "https://mykhaya.app"


@pytest.mark.asyncio
async def test_preflight_for_native_mobile_login_allows_the_native_client_headers(
    client: AsyncClient,
) -> None:
    """The exact preflight WKWebView sends before POST /auth/mobile/login:
    Origin (an allow-listed one), Access-Control-Request-Method: POST, and
    Access-Control-Request-Headers listing every header the real request
    will carry (Content-Type plus the native session-metadata headers)."""
    origin = _allowed_origin()
    response = await client.options(
        "/api/v1/auth/mobile/login",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-mykhaya-client,x-mykhaya-platform",
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers.get("access-control-allow-origin") == origin
    allowed_headers = {
        header.strip().lower()
        for header in response.headers.get("access-control-allow-headers", "").split(",")
    }
    assert "x-mykhaya-client" in allowed_headers
    assert "x-mykhaya-platform" in allowed_headers
    assert "content-type" in allowed_headers


@pytest.mark.asyncio
async def test_preflight_for_native_bearer_requests_allows_authorization(client: AsyncClient) -> None:
    response = await client.options(
        "/api/v1/users/me",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers.get("access-control-allow-origin") == ORIGIN
    assert "authorization" in {
        header.strip().lower()
        for header in response.headers.get("access-control-allow-headers", "").split(",")
    }


@pytest.mark.asyncio
async def test_preflight_allows_the_app_version_header_too(client: AsyncClient) -> None:
    origin = _allowed_origin()
    response = await client.options(
        "/api/v1/auth/mobile/login",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-mykhaya-app-version",
        },
    )
    assert response.status_code == 200, response.text
    allowed_headers = {
        header.strip().lower()
        for header in response.headers.get("access-control-allow-headers", "").split(",")
    }
    assert "x-mykhaya-app-version" in allowed_headers


@pytest.mark.asyncio
async def test_preflight_from_a_disallowed_origin_is_not_granted(client: AsyncClient) -> None:
    """Confirms the fix didn't weaken CORS globally — an origin not in
    MYKHAYA_CORS_ORIGINS still gets no Access-Control-Allow-Origin, so the
    browser still blocks the real request."""
    response = await client.options(
        "/api/v1/auth/mobile/login",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-mykhaya-client",
        },
    )
    assert response.headers.get("access-control-allow-origin") != "https://evil.example"
