"""Wishlist link-preview: metadata extraction (og:*, <title>, JSON-LD
Product/offers) and — the highest-risk part — SSRF protections in the
safe-fetch layer. See mykhaya.wishlist_link_preview.

Most of these are exercised directly against the safe-fetch/extraction
functions, which is cleaner than going through the full endpoint/DB test
harness for pure logic that needs no auth/DB state at all (per the task
brief). A couple of endpoint-level tests confirm the plumbing (auth/
entitlement gating, rate limiting, response shape) separately.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.entitlements import get_home_subscription
from mykhaya.main import app
from mykhaya.models import ActionToken, FeatureKey, FeatureOverride, SubscriptionPlan, TokenPurpose, User
from mykhaya.routers import wishlists as wishlists_router
from mykhaya.security import derived_token
from mykhaya.wishlist_link_preview import (
    LinkPreviewResult,
    _extract_metadata,
    _fetch_safely,
    _validate_target,
    fetch_link_preview,
)

ORIGIN = "http://localhost:8080"
PASSWORD = "Correct horse battery staple!"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


def unique_email(prefix: str) -> str:
    suffix = datetime.now(UTC).strftime("%H%M%S%f")
    return f"{prefix}-{suffix}@example.com"


async def unsafe(client: AsyncClient, method: str, path: str, **kwargs: object):
    headers = dict(kwargs.pop("headers", {}))
    csrf = client.cookies.get("mk_csrf")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return await client.request(method, path, headers=headers, **kwargs)


async def create_verified_user(client: AsyncClient, email: str, name: str) -> uuid.UUID:
    response = await unsafe(
        client,
        "POST",
        "/api/v1/auth/register",
        json={"email": email, "display_name": name, "password": PASSWORD},
    )
    assert response.status_code == 202
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        user_id = user.id
        token = await db.scalar(
            select(ActionToken)
            .where(
                ActionToken.user_id == user.id,
                ActionToken.purpose == TokenPurpose.verify_email,
            )
            .order_by(ActionToken.created_at.desc())
        )
        assert token is not None
        raw = derived_token(
            token.id, TokenPurpose.verify_email.value, get_settings().secret_key.get_secret_value()
        )
    verified = await unsafe(client, "POST", "/api/v1/auth/verify-email", json={"token": raw})
    assert verified.status_code == 200
    login = await unsafe(
        client, "POST", "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200
    return user_id


async def create_home(
    client: AsyncClient, name: str, *, plan: SubscriptionPlan = SubscriptionPlan.family
) -> uuid.UUID:
    group = await unsafe(client, "POST", "/api/v1/groups", json={"name": name})
    assert group.status_code == 201
    home_id = uuid.UUID(group.json()["id"])
    async with SessionFactory() as db:
        db.add(FeatureOverride(feature_key=FeatureKey.wish_lists, group_id=home_id, enabled=True))
        subscription = await get_home_subscription(db, home_id)
        assert subscription is not None
        subscription.plan = plan
        await db.commit()
    return home_id


# ---------------------------------------------------------------------------
# Metadata extraction (pure, no I/O)
# ---------------------------------------------------------------------------


def test_extracts_og_title_and_og_image() -> None:
    html = """
    <html><head>
      <meta property="og:title" content="Nice Lego Set" />
      <meta property="og:image" content="https://shop.example.com/img/lego.jpg" />
      <meta property="og:description" content="A great gift." />
      <title>Fallback Title</title>
    </head><body></body></html>
    """
    result = _extract_metadata(html)
    assert result.title == "Nice Lego Set"
    assert result.image_url == "https://shop.example.com/img/lego.jpg"
    assert result.description == "A great gift."


def test_falls_back_to_title_tag_and_twitter_image_when_og_missing() -> None:
    html = """
    <html><head>
      <title>Plain Title</title>
      <meta name="twitter:image" content="https://shop.example.com/img/fallback.jpg" />
      <meta name="description" content="Plain description." />
    </head><body></body></html>
    """
    result = _extract_metadata(html)
    assert result.title == "Plain Title"
    assert result.image_url == "https://shop.example.com/img/fallback.jpg"
    assert result.description == "Plain description."


def test_extracts_json_ld_product_price_and_currency() -> None:
    html = """
    <html><head>
      <meta property="og:title" content="Board Game" />
      <script type="application/ld+json">
      {
        "@context": "https://schema.org/",
        "@type": "Product",
        "name": "Board Game",
        "offers": {
          "@type": "Offer",
          "price": "24.99",
          "priceCurrency": "GBP"
        }
      }
      </script>
    </head><body></body></html>
    """
    result = _extract_metadata(html)
    assert result.title == "Board Game"
    assert result.price == Decimal("24.99")
    assert result.currency == "GBP"


def test_json_ld_product_in_a_list_and_offers_as_a_list_still_parses() -> None:
    html = """
    <html><head>
      <script type="application/ld+json">
      [
        {"@type": "BreadcrumbList", "itemListElement": []},
        {
          "@type": "Product",
          "offers": [{"price": 9.5, "priceCurrency": "usd"}]
        }
      ]
      </script>
    </head></html>
    """
    result = _extract_metadata(html)
    assert result.price == Decimal("9.5")
    assert result.currency == "USD"


def test_malformed_json_ld_does_not_raise_and_yields_no_price() -> None:
    html = """
    <html><head>
      <meta property="og:title" content="Still Has A Title" />
      <script type="application/ld+json">{ not valid json at all </script>
    </head></html>
    """
    result = _extract_metadata(html)
    assert result.title == "Still Has A Title"
    assert result.price is None
    assert result.currency is None


def test_completely_empty_html_yields_all_none_result() -> None:
    result = _extract_metadata("<html><head></head><body>Nothing here</body></html>")
    assert result == LinkPreviewResult()


def test_json_ld_product_name_and_string_image_are_preferred_over_og_and_title() -> None:
    html = """
    <html><head>
      <title>Fallback Title</title>
      <meta property="og:title" content="OG Title" />
      <meta property="og:image" content="https://shop.example.com/og.jpg" />
      <script type="application/ld+json">
      {
        "@type": "Product",
        "name": "JSON-LD Product Name",
        "image": "https://shop.example.com/json-ld.jpg"
      }
      </script>
    </head><body></body></html>
    """
    result = _extract_metadata(html)
    assert result.title == "JSON-LD Product Name"
    assert result.image_url == "https://shop.example.com/json-ld.jpg"


def test_json_ld_image_as_array_of_strings() -> None:
    html = """
    <html><head>
      <script type="application/ld+json">
      {"@type": "Product", "image": ["https://shop.example.com/one.jpg", "https://shop.example.com/two.jpg"]}
      </script>
    </head></html>
    """
    result = _extract_metadata(html)
    assert result.image_url == "https://shop.example.com/one.jpg"


def test_json_ld_image_as_image_object_and_array_of_image_objects() -> None:
    html_single = """
    <html><head>
      <script type="application/ld+json">
      {"@type": "Product", "image": {"@type": "ImageObject", "url": "https://shop.example.com/obj.jpg"}}
      </script>
    </head></html>
    """
    assert _extract_metadata(html_single).image_url == "https://shop.example.com/obj.jpg"

    html_array = """
    <html><head>
      <script type="application/ld+json">
      {"@type": "Product", "image": [{"@type": "ImageObject", "url": "https://shop.example.com/arr.jpg"}]}
      </script>
    </head></html>
    """
    assert _extract_metadata(html_array).image_url == "https://shop.example.com/arr.jpg"


def test_og_image_secure_url_used_when_og_image_missing() -> None:
    html = """
    <html><head>
      <meta property="og:title" content="Secure Image Item" />
      <meta property="og:image:secure_url" content="https://shop.example.com/secure.jpg" />
    </head></html>
    """
    result = _extract_metadata(html)
    assert result.image_url == "https://shop.example.com/secure.jpg"


def test_offers_low_price_used_when_price_absent() -> None:
    html = """
    <html><head>
      <script type="application/ld+json">
      {"@type": "Product", "offers": {"lowPrice": "12.50", "priceCurrency": "GBP"}}
      </script>
    </head></html>
    """
    result = _extract_metadata(html)
    assert result.price == Decimal("12.50")
    assert result.currency == "GBP"


def test_bot_check_title_alone_is_not_reported_as_a_found_title() -> None:
    html = "<html><head><title>Robot Check - Please verify you are a human</title></head></html>"
    result = _extract_metadata(html)
    assert result.title is None
    assert result == LinkPreviewResult()


def test_cloudflare_interstitial_title_alone_is_not_reported() -> None:
    html = "<html><head><title>Just a moment...</title></head></html>"
    result = _extract_metadata(html)
    assert result.title is None


def test_interstitial_phrase_does_not_suppress_a_trusted_og_title() -> None:
    # The interstitial check only applies to the bare <title> fallback — an
    # explicit og:title is trusted even if it happens to contain one of the
    # generic phrases (extremely unlikely for a real product, but the rule
    # must not accidentally apply to curated signals).
    html = """
    <html><head>
      <meta property="og:title" content="Are You a Human? The Board Game" />
    </head></html>
    """
    result = _extract_metadata(html)
    assert result.title == "Are You a Human? The Board Game"


# ---------------------------------------------------------------------------
# SSRF target validation — reject before any request is made
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://169.254.169.254/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://172.16.0.5/",
        "http://0.0.0.0/",
        "file:///etc/passwd",
        "ftp://example.com/",
        "gopher://example.com/",
        "http://api/",
    ],
)
def test_validate_target_rejects_disallowed_targets(url: str) -> None:
    assert _validate_target(url) is not None


def test_validate_target_allows_a_plausible_public_https_url() -> None:
    # A public, non-reserved IP literal — no DNS resolution required, so
    # this assertion doesn't depend on network access being available in CI.
    assert _validate_target("https://93.184.216.34/product") is None


# ---------------------------------------------------------------------------
# SSRF regression via the safe-fetch layer (mocked transport / no real
# network access)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "file:///etc/passwd",
        "ftp://example.com/",
    ],
)
async def test_fetch_safely_blocks_disallowed_targets(url: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must never run
        raise AssertionError("blocked target must never reach the transport")

    body = await _fetch_safely(url, transport=httpx.MockTransport(handler))
    assert body is None


@pytest.mark.asyncio
async def test_fetch_safely_follows_and_revalidates_redirect_to_blocked_ip() -> None:
    """The classic SSRF-via-redirect bypass: a first request to an allowed
    public host that then 302s to a blocked internal target must be caught
    at the redirect hop, not just the original URL."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "93.184.216.34":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/secret"})
        raise AssertionError("must never follow through to the blocked redirect target")

    body = await _fetch_safely(
        "http://93.184.216.34/starts-fine", transport=httpx.MockTransport(handler)
    )
    assert body is None


@pytest.mark.asyncio
async def test_fetch_safely_gives_up_after_too_many_redirects() -> None:
    hops = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        hops["count"] += 1
        # Keep redirecting between two allowed public IPs — must still stop
        # after the configured hop limit rather than looping forever.
        next_host = "93.184.216.35" if request.url.host == "93.184.216.34" else "93.184.216.34"
        return httpx.Response(302, headers={"location": f"http://{next_host}/"})

    body = await _fetch_safely("http://93.184.216.34/", transport=httpx.MockTransport(handler))
    assert body is None
    assert hops["count"] <= 4  # initial + _MAX_REDIRECTS, never unbounded


@pytest.mark.asyncio
async def test_fetch_safely_rejects_oversized_response() -> None:
    huge = b"<html>" + (b"a" * (3 * 1024 * 1024)) + b"</html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=huge)

    body = await _fetch_safely("http://93.184.216.34/", transport=httpx.MockTransport(handler))
    assert body is None


@pytest.mark.asyncio
async def test_fetch_safely_rejects_non_html_content_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "application/octet-stream"}, content=b"binary"
        )

    body = await _fetch_safely("http://93.184.216.34/", transport=httpx.MockTransport(handler))
    assert body is None


@pytest.mark.asyncio
async def test_fetch_safely_handles_timeout_gracefully() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated hang", request=request)

    body = await _fetch_safely("http://93.184.216.34/", transport=httpx.MockTransport(handler))
    assert body is None


@pytest.mark.asyncio
async def test_fetch_safely_returns_body_for_a_normal_allowed_response() -> None:
    html = b"<html><head><title>OK</title></head></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=html)

    body = await _fetch_safely("http://93.184.216.34/", transport=httpx.MockTransport(handler))
    assert body == html


@pytest.mark.asyncio
async def test_fetch_safely_follows_meta_refresh_and_extracts_from_final_page() -> None:
    """A scripted 200 response whose body is only a
    `<meta http-equiv="refresh">` redirect — the kind some link shorteners
    use instead of (or alongside) a real HTTP 3xx — must be followed one
    more hop, re-validated exactly like a real redirect, and the metadata
    must come from the FINAL page, not the interim one."""
    interim = b'<html><head><meta http-equiv="refresh" content="0;url=/final"></head></html>'
    final = b"<html><head><title>Final Product Page</title></head></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(200, headers={"content-type": "text/html"}, content=interim)
        if request.url.path == "/final":
            return httpx.Response(200, headers={"content-type": "text/html"}, content=final)
        raise AssertionError(f"unexpected path {request.url.path}")

    body = await _fetch_safely(
        "http://93.184.216.34/start", transport=httpx.MockTransport(handler)
    )
    assert body == final
    result = _extract_metadata(body.decode("utf-8"))
    assert result.title == "Final Product Page"


@pytest.mark.asyncio
async def test_fetch_safely_rejects_meta_refresh_to_a_blocked_target() -> None:
    """Mirrors test_fetch_safely_follows_and_revalidates_redirect_to_blocked_ip
    but for a client-side (meta-refresh) redirect instead of a real HTTP
    3xx — the same SSRF-via-redirect bypass, via the standards-based
    JS/meta-refresh path instead of a Location header."""
    interim = (
        b'<html><head><meta http-equiv="refresh" '
        b'content="0;url=http://169.254.169.254/secret"></head></html>'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "93.184.216.34":
            return httpx.Response(200, headers={"content-type": "text/html"}, content=interim)
        raise AssertionError("must never follow through to the blocked meta-refresh target")

    body = await _fetch_safely(
        "http://93.184.216.34/start", transport=httpx.MockTransport(handler)
    )
    assert body is None


@pytest.mark.asyncio
async def test_fetch_safely_meta_refresh_shares_the_redirect_budget_with_real_redirects() -> None:
    """A chain that mixes a real HTTP redirect with meta-refresh hops must
    still be capped by the one shared _MAX_REDIRECTS budget, not get extra
    hops for switching redirect styles partway through."""
    hops = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        hops["count"] += 1
        # Alternate a real 302 and a meta-refresh forever — must still stop
        # after the configured hop limit rather than looping unboundedly.
        if hops["count"] % 2 == 1:
            return httpx.Response(302, headers={"location": "/next"})
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b'<html><head><meta http-equiv="refresh" content="0;url=/next"></head></html>',
        )

    body = await _fetch_safely("http://93.184.216.34/", transport=httpx.MockTransport(handler))
    assert body is None
    assert hops["count"] <= 4  # initial + _MAX_REDIRECTS, never unbounded


@pytest.mark.asyncio
async def test_fetch_link_preview_never_raises_and_is_graceful_end_to_end() -> None:
    settings = get_settings()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated connection refused", request=request)

    result = await fetch_link_preview(
        "http://93.184.216.34/", settings, transport=httpx.MockTransport(handler)
    )
    assert result == LinkPreviewResult()

    # And a genuinely blocked target resolves the exact same way, not with
    # any distinguishable error.
    blocked_result = await fetch_link_preview("http://127.0.0.1/", settings)
    assert blocked_result == LinkPreviewResult()


# ---------------------------------------------------------------------------
# Endpoint plumbing — auth/entitlement gating, rate limiting, response shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_preview_endpoint_returns_extracted_metadata(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await create_verified_user(client, unique_email("linkpreview"), "Link Preview User")
    home_id = await create_home(client, "Link Preview Home")

    async def fake_fetch(url: str, settings: object) -> LinkPreviewResult:
        assert url == "https://shop.example.com/item/123"
        return LinkPreviewResult(title="Nice Item", image_url="https://shop.example.com/i.jpg")

    monkeypatch.setattr(wishlists_router, "fetch_link_preview", fake_fetch)

    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists/link-preview",
        json={"url": "https://shop.example.com/item/123"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Nice Item"
    assert body["image_url"] == "https://shop.example.com/i.jpg"
    assert body["price"] is None


@pytest.mark.asyncio
async def test_link_preview_endpoint_requires_wishlists_manage(client: AsyncClient) -> None:
    await create_verified_user(client, unique_email("linkpreviewfree"), "Link Preview Free")
    home_id = await create_home(client, "Link Preview Free Home", plan=SubscriptionPlan.free)

    response = await unsafe(
        client,
        "POST",
        f"/api/v1/homes/{home_id}/wishlists/link-preview",
        json={"url": "https://shop.example.com/item/123"},
    )
    assert response.status_code == 403
