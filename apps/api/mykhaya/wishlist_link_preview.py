"""Server-side URL metadata ("link preview") fetch for Wishlist items —
called when a user pastes a product URL, so the frontend can prefill
name/image/price without the browser itself needing to reach the target
site (which og:image etc. often disallow via CORS anyway).

Deliberately split into two layers, so the SSRF-sensitive part is easy to
read/audit/test on its own, separate from HTML parsing:

  - `_validate_target` / `_resolve_hostname` / `_is_blocked_ip`: is this URL
    even allowed to be fetched at all. Every hop of a redirect chain is
    re-validated here, not just the first request.
  - `_fetch_safely`: the actual network call — manual (non-auto-following)
    redirect handling, short timeouts, a streamed response with a hard size
    cap, and a content-type allowlist.
  - `_extract_metadata` / `_MetaExtractor` / `_extract_price_currency`: pure,
    no I/O, defensive HTML/JSON-LD parsing. Cannot raise on malformed input
    by construction (every parse step is wrapped).

`fetch_link_preview` is the only function routers.wishlists calls, and it
never raises and never returns a distinguishable "why it failed" — a
blocked private IP, a DNS failure, a timeout, an oversized body, and a
perfectly reachable page with no metadata at all all produce the exact same
all-None LinkPreviewResult. That is intentional: this endpoint must not let
a caller fingerprint MyKhaya's internal network by comparing error shapes
(see the router endpoint's docstring). The real reason is still logged
server-side via structlog for our own diagnostics.

We only ever return the *discovered image's own URL* as a string for the
frontend to hotlink directly — we never download/store/re-host the image
bytes themselves. That halves the SSRF surface (there is no second
fetch-and-store-blob pipeline to secure) and matches
`WishlistItem.image_url` already being a plain `String(2000)` URL column,
not an uploaded file (see models.py).
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

import httpx
import structlog

from mykhaya.config import Settings

log = structlog.get_logger()

# --- Limits -------------------------------------------------------------

_CONNECT_TIMEOUT_SECONDS = 3.0
_TOTAL_TIMEOUT_SECONDS = 6.0
_MAX_BODY_BYTES = 2 * 1024 * 1024  # 2MB
_MAX_REDIRECTS = 3
_ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml")
_USER_AGENT = "MyKhayaLinkPreview/1.0 (+https://mykhaya.app)"

# Literal hostnames worth blocking outright in addition to the IP-range
# checks below (which already catch anything resolving into a container
# network's private range). Sourced from Settings.trusted_hosts (the app's
# own externally-reachable names) plus compose.yml's other internal service
# names — none of these should ever be a legitimate wishlist item URL.
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "api",
        "web",
        "worker",
        "scheduler",
        "migrate",
        "postgres",
        "redis",
        "mailpit",
        "caddy",
        "api.mykhaya.app",
    }
)

# Known interstitial/bot-check phrasing, for honest-failure detection only —
# we are not attempting to defeat these protections. A page's ONLY signal
# being a bare fallback <title> (no og:title, no JSON-LD Product name) that
# contains one of these phrases almost certainly means the request landed on
# a block/interstitial page rather than a genuine product page, so it must
# not be reported to the caller as a "found" title — that would be lying
# about success. Deliberately short and generic (not retailer-specific
# scraping logic of any kind).
_INTERSTITIAL_TITLE_PHRASES = (
    "robot check",
    "captcha",
    "are you a human",
    "verify you are human",
    "access denied",
    "just a moment",  # Cloudflare's interstitial title
    "enter the characters you see",
    "unusual traffic",
)


def _looks_like_interstitial_title(title: str) -> bool:
    lowered = title.lower()
    return any(phrase in lowered for phrase in _INTERSTITIAL_TITLE_PHRASES)


@dataclass(frozen=True)
class LinkPreviewResult:
    title: str | None = None
    image_url: str | None = None
    description: str | None = None
    price: Decimal | None = None
    currency: str | None = None


# --- Layer 1: SSRF-safe target validation --------------------------------


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Deliberately checks every disallowed category explicitly rather than
    relying on `is_private` alone — is_private does not, for example, cover
    every multicast/reserved case on its own in all Python versions, and
    being explicit here is easier to audit than trusting one flag."""
    return (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        # Explicit belt-and-braces check for the single highest-value SSRF
        # target (the AWS/GCP/Azure metadata endpoint) even though it's
        # already covered by is_link_local above.
        or str(ip) == "169.254.169.254"
    )


def _resolve_hostname(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolves every A/AAAA record for hostname — a hostname can point at
    multiple IPs, and we must reject if ANY of them is disallowed, not just
    the first one returned."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError:
        return []
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        raw = info[4][0]
        try:
            addresses.append(ipaddress.ip_address(raw.split("%", 1)[0]))
        except ValueError:
            continue
    return addresses


def _validate_target(url: str) -> str | None:
    """Returns None if `url` is safe to fetch, otherwise a short machine
    reason string (logged, never returned to the caller)."""
    try:
        parsed = httpx.URL(url)
    except Exception:
        return "unparseable_url"
    if parsed.scheme not in ("http", "https"):
        return "disallowed_scheme"
    hostname = parsed.host
    if not hostname:
        return "no_host"
    normalised_host = hostname.strip(".").casefold()
    if normalised_host in _BLOCKED_HOSTNAMES:
        return "blocked_hostname"
    try:
        # A literal IP in the URL — validate it directly rather than
        # resolving (there's nothing to resolve).
        addresses = [ipaddress.ip_address(normalised_host)]
    except ValueError:
        addresses = _resolve_hostname(hostname)
    if not addresses:
        return "resolution_failed"
    if any(_is_blocked_ip(ip) for ip in addresses):
        return "blocked_ip"
    return None


def _safe_host(url: str) -> str | None:
    """Best-effort hostname extraction for logging only — never raises, and
    the result is a bare hostname (no path/query), so it can't leak a PIN,
    token, or full query string into logs."""
    try:
        return httpx.URL(url).host or None
    except Exception:
        return None


# --- Layer 2: the actual (SSRF-safe) fetch --------------------------------


async def _fetch_safely(
    url: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> bytes | None:
    """Streams the response body, enforcing the size cap while streaming
    (Content-Length is only a fast-path check — it can lie or be absent).
    Redirects are never auto-followed: each hop is validated against the
    same blocklist as the original URL before it is requested, which is the
    only way to catch a redirect from an allowed public host to a blocked
    internal one.

    `transport` is a test-only hook (httpx.MockTransport) so the SSRF
    regression tests can exercise this exact code path — redirect handling,
    size cap, content-type check — against a scripted response without any
    real network access. Production call sites never pass it, so the real
    fetch always uses httpx's normal transport.

    A `<meta http-equiv="refresh">` client-side redirect found in an
    otherwise-successful (200, right content-type) response is treated as
    one more hop of the SAME redirect chain: the target is resolved and
    re-validated through `_validate_target` exactly like a real HTTP 3xx
    Location header, and it is counted against the same `_MAX_REDIRECTS`
    budget (both kinds of hop share the one `for hop in ...` loop below) —
    it deliberately does not get its own separate allowance that could be
    combined with real redirects to exceed the intended total hop limit.
    This is the standards-based fix for link shorteners that redirect via an
    HTML/JS meta-refresh instead of (or in addition to) a real HTTP 3xx."""
    timeout = httpx.Timeout(_TOTAL_TIMEOUT_SECONDS, connect=_CONNECT_TIMEOUT_SECONDS)
    current_url = url
    original_host = _safe_host(url)
    try:
        async with httpx.AsyncClient(
            follow_redirects=False, timeout=timeout, transport=transport
        ) as client:
            for hop in range(_MAX_REDIRECTS + 1):
                reason = _validate_target(current_url)
                if reason is not None:
                    log.info(
                        "wishlist_link_preview.blocked",
                        reason=reason,
                        category=("redirect_blocked" if hop > 0 else "blocked_address")
                        if reason in ("blocked_hostname", "blocked_ip", "resolution_failed")
                        else "invalid_url",
                        hop=hop,
                        original_host=original_host,
                    )
                    return None
                async with client.stream(
                    "GET", current_url, headers={"User-Agent": _USER_AGENT}
                ) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            log.info("wishlist_link_preview.redirect_without_location")
                            return None
                        current_url = str(httpx.URL(current_url).join(location))
                        continue

                    content_type = (
                        response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    )
                    if content_type not in _ALLOWED_CONTENT_TYPES:
                        log.info(
                            "wishlist_link_preview.unsupported_content_type",
                            category="unsupported_content_type",
                            content_type=content_type,
                            original_host=original_host,
                        )
                        return None

                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            if int(content_length) > _MAX_BODY_BYTES:
                                log.info("wishlist_link_preview.content_length_too_large")
                                return None
                        except ValueError:
                            pass

                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > _MAX_BODY_BYTES:
                            log.info("wishlist_link_preview.body_too_large")
                            return None

                    if content_type in ("text/html", "application/xhtml+xml"):
                        text = body.decode("utf-8", errors="replace")
                        refresh_target = _extract_meta_refresh_target(text)
                        if refresh_target:
                            current_url = str(httpx.URL(current_url).join(refresh_target))
                            log.info(
                                "wishlist_link_preview.meta_refresh",
                                hop=hop,
                                original_host=original_host,
                            )
                            continue
                    return bytes(body)
            log.info(
                "wishlist_link_preview.too_many_redirects",
                category="redirect_blocked",
                original_host=original_host,
            )
            return None
    except httpx.TimeoutException:
        log.info(
            "wishlist_link_preview.timeout", category="timeout", original_host=original_host
        )
        return None
    except httpx.HTTPError as exc:
        log.info(
            "wishlist_link_preview.fetch_failed",
            category="upstream_http_error",
            error=str(exc),
            original_host=original_host,
        )
        return None


# --- Layer 3: pure HTML/JSON-LD metadata extraction -----------------------


class _MetaExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title: str | None = None
        self.json_ld_blocks: list[str] = []
        self._in_title = False
        self._in_json_ld = False
        self._json_ld_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            # http-equiv is only consulted as a last-resort key (after
            # property/name) so this doesn't change og:*/twitter:* lookups
            # at all — it exists solely so `refresh` (client-side redirect)
            # can be read via the same self.meta dict as everything else.
            key = (
                attrs_dict.get("property") or attrs_dict.get("name") or attrs_dict.get("http-equiv")
            )
            content = attrs_dict.get("content")
            if key and content is not None:
                normalised = key.strip().lower()
                # First occurrence wins — matches typical head-tag ordering
                # conventions (canonical og: tags before fallbacks).
                self.meta.setdefault(normalised, content)
        elif tag == "script":
            script_type = (attrs_dict.get("type") or "").strip().lower()
            if script_type == "application/ld+json":
                self._in_json_ld = True
                self._json_ld_buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._in_json_ld:
            self._in_json_ld = False
            self.json_ld_blocks.append("".join(self._json_ld_buffer))

    def handle_data(self, data: str) -> None:
        if self._in_title and self.title is None:
            self.title = data.strip()
        elif self._in_json_ld:
            self._json_ld_buffer.append(data)


def _iter_json_ld_products(data: object) -> list[dict]:
    """Defensive JSON-LD walk — a real page's JSON-LD is very often a single
    object, sometimes a list, sometimes a Product nested under @graph.
    Anything that doesn't match that shape is silently skipped, never
    raised."""
    products: list[dict] = []
    items = data if isinstance(data, list) else [data]
    for item in items:
        if not isinstance(item, dict):
            continue
        type_value = item.get("@type")
        types = type_value if isinstance(type_value, list) else [type_value]
        if any(isinstance(t, str) and t.lower() == "product" for t in types):
            products.append(item)
        graph = item.get("@graph")
        if isinstance(graph, list):
            products.extend(_iter_json_ld_products(graph))
    return products


def _extract_json_ld_image(value: object) -> str | None:
    """A JSON-LD Product's `image` is commonly a bare URL string, but schema.org
    also permits an array of strings, a single ImageObject (`{"url": ...}`),
    or an array of ImageObjects — all handled here, defensively (anything
    else is silently skipped, never raised)."""
    if isinstance(value, str):
        candidate = value.strip()
        return candidate or None
    if isinstance(value, dict):
        url = value.get("url")
        if isinstance(url, str) and url.strip():
            return url.strip()
        return None
    if isinstance(value, list):
        for item in value:
            found = _extract_json_ld_image(item)
            if found:
                return found
    return None


_META_REFRESH_URL_RE = re.compile(r"url\s*=\s*(.+)$", re.IGNORECASE)


def _extract_meta_refresh_target(html_text: str) -> str | None:
    """Looks for `<meta http-equiv="refresh" content="0;url=...">` — a
    client-side redirect some link shorteners use instead of (or alongside)
    a real HTTP 3xx. The caller is responsible for re-validating the
    returned target through `_validate_target` and counting it against the
    shared redirect-hop budget, exactly like a real redirect — this function
    only ever returns the raw target string, it never fetches anything."""
    try:
        parser = _MetaExtractor()
        parser.feed(html_text)
    except Exception:
        return None
    content = parser.meta.get("refresh")
    if not content:
        return None
    match = _META_REFRESH_URL_RE.search(content)
    if not match:
        return None
    target = match.group(1).strip().strip("'\"")
    return target or None


def _extract_json_ld_product_fields(
    json_ld_blocks: list[str],
) -> tuple[str | None, str | None, Decimal | None, str | None]:
    """One pass over every JSON-LD Product block, pulling name/image/
    price/currency together — deliberately not re-walking the JSON-LD
    separately per field. The first non-null value found for each field
    (scanning blocks/products in document order) wins; scanning stops early
    once all four fields are filled."""
    name: str | None = None
    image: str | None = None
    price: Decimal | None = None
    currency: str | None = None
    for raw in json_ld_blocks:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
        for product in _iter_json_ld_products(data):
            if name is None:
                candidate = product.get("name")
                if isinstance(candidate, str) and candidate.strip():
                    name = candidate.strip()
            if image is None:
                image = _extract_json_ld_image(product.get("image"))
            if price is None and currency is None:
                offers = product.get("offers")
                if isinstance(offers, list):
                    offers = offers[0] if offers else None
                if isinstance(offers, dict):
                    price_raw = offers.get("price")
                    if price_raw is None:
                        # schema.org AggregateOffer-style fallback — a
                        # price range with no single "price" still gives a
                        # usable figure.
                        price_raw = offers.get("lowPrice")
                    if price_raw is not None:
                        try:
                            candidate_price = Decimal(str(price_raw).strip())
                            if candidate_price.is_finite() and candidate_price >= 0:
                                price = candidate_price
                        except (InvalidOperation, ValueError):
                            pass
                    currency_raw = offers.get("priceCurrency")
                    if isinstance(currency_raw, str) and len(currency_raw.strip()) == 3:
                        currency = currency_raw.strip().upper()
        if name is not None and image is not None and price is not None and currency is not None:
            break
    return name, image, price, currency


def _extract_metadata(html_text: str) -> LinkPreviewResult:
    parser = _MetaExtractor()
    try:
        parser.feed(html_text)
    except Exception as exc:  # HTMLParser is fairly forgiving already, but
        # malformed input must never raise out of this pure function.
        log.info("wishlist_link_preview.html_parse_failed", error=str(exc))
        return LinkPreviewResult()

    try:
        json_ld_name, json_ld_image, price, currency = _extract_json_ld_product_fields(
            parser.json_ld_blocks
        )
    except Exception as exc:
        log.info("wishlist_link_preview.json_ld_parse_failed", error=str(exc))
        json_ld_name, json_ld_image, price, currency = None, None, None, None

    # Title preference: JSON-LD Product.name > og:title > <title> — but a
    # bare fallback <title> that looks like a bot-check/interstitial page
    # (see _looks_like_interstitial_title) is deliberately NOT treated as a
    # useful title on its own. JSON-LD name and og:title are curated,
    # explicit signals a site chose to publish, so they're trusted as-is;
    # only the last-resort <title> fallback gets the interstitial check.
    og_title = parser.meta.get("og:title")
    if json_ld_name:
        title: str | None = json_ld_name
    elif og_title:
        title = og_title
    elif parser.title and not _looks_like_interstitial_title(parser.title):
        title = parser.title
    else:
        title = None

    # Image preference: JSON-LD Product.image > og:image > og:image:secure_url
    # > twitter:image.
    image = (
        json_ld_image
        or parser.meta.get("og:image")
        or parser.meta.get("og:image:secure_url")
        or parser.meta.get("twitter:image")
    )
    description = parser.meta.get("og:description") or parser.meta.get("description")

    return LinkPreviewResult(
        title=(title.strip() or None) if title else None,
        image_url=(image.strip() or None) if image else None,
        description=(description.strip() or None) if description else None,
        price=price,
        currency=currency,
    )


# --- Public entrypoint -----------------------------------------------------


async def fetch_link_preview(
    url: str, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
) -> LinkPreviewResult:
    """Never raises. Any failure — blocked target, timeout, oversized body,
    wrong content type, unreachable host, unparseable HTML — resolves to an
    all-None result, indistinguishable from "reachable page with no
    metadata". `settings` is accepted (and unused beyond being available for
    future tuning) to match this codebase's convention of passing Settings
    explicitly to outbound-call helpers rather than reading get_settings()
    internally. `transport` is the same test-only hook as _fetch_safely's."""
    del settings  # reserved for future tuning; the fetch uses fixed, tight limits today
    original_host = _safe_host(url)
    try:
        body = await _fetch_safely(url, transport=transport)
    except Exception as exc:  # belt-and-braces: this function must never raise
        log.warning("wishlist_link_preview.unexpected_fetch_error", error=str(exc))
        log.info(
            "wishlist_link_preview.result",
            original_host=original_host,
            category="unexpected_error",
            fields_found=[],
        )
        return LinkPreviewResult()
    if body is None:
        # The specific reason (invalid_url / blocked_address / redirect_blocked
        # / timeout / unsupported_content_type / upstream_http_error) was
        # already logged inside _fetch_safely — this summary line is the one
        # place that logs a single, clear outcome per call, regardless of
        # which layer produced it.
        log.info(
            "wishlist_link_preview.result",
            original_host=original_host,
            category="fetch_failed",
            fields_found=[],
        )
        return LinkPreviewResult()
    try:
        html_text = body.decode("utf-8", errors="replace")
    except Exception as exc:
        log.warning("wishlist_link_preview.decode_failed", error=str(exc))
        log.info(
            "wishlist_link_preview.result",
            original_host=original_host,
            category="decode_failed",
            fields_found=[],
        )
        return LinkPreviewResult()
    result = _extract_metadata(html_text)
    fields_found = [
        field_name
        for field_name, value in (
            ("title", result.title),
            ("image_url", result.image_url),
            ("description", result.description),
            ("price", result.price),
            ("currency", result.currency),
        )
        if value is not None
    ]
    log.info(
        "wishlist_link_preview.result",
        original_host=original_host,
        category="metadata_found" if fields_found else "no_metadata",
        fields_found=fields_found,
    )
    return result
