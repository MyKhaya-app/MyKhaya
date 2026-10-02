"""Safe, schema.org-first recipe import for Meal Plans.

The importer deliberately understands JSON-LD Recipe data only. It never
executes remote scripts or falls back to arbitrary site-specific scraping.
"""

from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import re
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

MAX_RESPONSE_BYTES = 2_000_000
MAX_REDIRECTS = 3
REQUEST_TIMEOUT = httpx.Timeout(8.0, connect=4.0)
_WHITESPACE = re.compile(r"\s+")


class RecipeImportError(ValueError):
    pass


async def _read_limited(response: httpx.Response, limit: int) -> bytes:
    declared = response.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise RecipeImportError("We couldn't automatically read this recipe.")
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > limit:
            raise RecipeImportError("We couldn't automatically read this recipe.")
    return bytes(body)


class _JsonLdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._depth = 0
        self.parts: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        values = {key.lower(): value or "" for key, value in attrs}
        if values.get("type", "").lower() == "application/ld+json":
            self._depth = 1
            self.parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._depth:
            self.blocks.append("".join(self.parts))
            self._depth = 0
            self.parts = []

    def handle_data(self, data: str) -> None:
        if self._depth:
            self.parts.append(data)


def _text(value: Any, limit: int = 8000) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = _WHITESPACE.sub(" ", html.unescape(value)).strip()
    return cleaned[:limit] or None


def _is_recipe(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    kind = value.get("@type")
    if isinstance(kind, list):
        return any(str(item).lower() == "recipe" for item in kind)
    return str(kind).lower() == "recipe"


def _recipe_nodes(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        result: list[dict[str, Any]] = []
        for item in value:
            result.extend(_recipe_nodes(item))
        return result
    if not isinstance(value, dict):
        return []
    result = [value] if _is_recipe(value) else []
    for key in ("@graph", "mainEntity", "mainEntityOfPage", "itemListElement"):
        result.extend(_recipe_nodes(value.get(key)))
    return result


def _image_url(value: Any, source_url: str) -> str | None:
    candidates = value if isinstance(value, list) else [value]
    for candidate in candidates:
        raw = candidate.get("url") if isinstance(candidate, dict) else candidate
        if isinstance(raw, str) and raw.strip():
            return urljoin(source_url, raw.strip())[:2000]
    return None


def _duration_minutes(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?)?",
        value.strip(),
        re.I,
    )
    if not match:
        return None
    minutes = (int(match.group("days") or 0) * 1440) + (int(match.group("hours") or 0) * 60)
    minutes += int(match.group("minutes") or 0)
    return minutes or None


def _servings(value: Any) -> int | None:
    raw = value if isinstance(value, (int, float)) else _text(value, 80)
    if raw is None:
        return None
    match = re.search(r"\d+", str(raw))
    return max(1, min(100, int(match.group()))) if match else None


def _instruction_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [_text(value, 2000)] if _text(value, 2000) else []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_instruction_text(item))
        return result
    if isinstance(value, dict):
        if str(value.get("@type", "")).lower() == "howtosection":
            return _instruction_text(value.get("itemListElement"))
        return _instruction_text(value.get("text") or value.get("itemListElement"))
    return []


def _ingredients(value: Any) -> list[dict[str, str | None]]:
    values = value if isinstance(value, list) else [value]
    result: list[dict[str, str | None]] = []
    for item in values:
        raw = item.get("text") if isinstance(item, dict) else item
        text = _text(raw, 200)
        if text:
            result.append({"text": text, "quantity": None, "unit": None})
    return result[:100]


def normalise_recipe(data: Any, source_url: str) -> dict[str, Any] | None:
    recipes = _recipe_nodes(data)
    if not recipes:
        return None
    recipe = recipes[0]
    category = _text(recipe.get("recipeCategory"), 80)
    category_key = (category or "").lower()
    meal_type = next(
        (
            key
            for key in ("breakfast", "lunch", "dinner", "snack", "dessert")
            if key in category_key
        ),
        "other",
    )
    instructions = _instruction_text(recipe.get("recipeInstructions"))
    return {
        "name": _text(recipe.get("name"), 160) or "Imported meal",
        "description": _text(recipe.get("description"), 2000),
        "image_url": _image_url(recipe.get("image"), source_url),
        "meal_type": meal_type,
        "prep_minutes": _duration_minutes(recipe.get("prepTime")),
        "cook_minutes": _duration_minutes(recipe.get("cookTime")),
        "servings": _servings(recipe.get("recipeYield")),
        "instructions": "\n\n".join(instructions)[:8000] or None,
        "source_url": source_url,
        "ingredients": _ingredients(recipe.get("recipeIngredient")),
    }


def _validate_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme not in {"http", "https"} or not hostname or parsed.username or parsed.password:
        raise RecipeImportError("That recipe link is not supported.")
    internal_hosts = {"localhost", "localhost.localdomain", "metadata.google.internal"}
    if hostname in internal_hosts or hostname.endswith((".localhost", ".local", ".internal")):
        raise RecipeImportError("That recipe link is not supported.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
    ):
        raise RecipeImportError("That recipe link is not supported.")
    return value.strip()


async def _safe_url(value: str) -> str:
    url = _validate_url(value)
    hostname = urlsplit(url).hostname
    assert hostname is not None
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, hostname, None, type=socket.SOCK_STREAM)
    except (OSError, socket.gaierror) as cause:
        raise RecipeImportError("That recipe link could not be reached.") from cause
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
        ):
            raise RecipeImportError("That recipe link is not supported.")
    return url


async def import_recipe(url: str) -> dict[str, Any]:
    current = await _safe_url(url)
    headers = {
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": "MyKhaya recipe importer/1.0",
    }
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT, follow_redirects=False, headers=headers
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            async with client.stream("GET", current) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise RecipeImportError("We couldn't automatically read this recipe.")
                    current = await _safe_url(urljoin(current, location))
                    continue
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if response.status_code >= 400 or content_type not in {
                    "text/html",
                    "application/xhtml+xml",
                }:
                    raise RecipeImportError("We couldn't automatically read this recipe.")
                body = await _read_limited(response, MAX_RESPONSE_BYTES)
            parser = _JsonLdParser()
            parser.feed(body.decode(response.encoding or "utf-8", errors="replace"))
            for block in parser.blocks:
                try:
                    draft = normalise_recipe(json.loads(block), current)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if draft:
                    return draft
            raise RecipeImportError("We couldn't automatically read this recipe.")
    raise RecipeImportError("We couldn't automatically read this recipe.")


async def download_recipe_image(url: str) -> bytes | None:
    """Download a small image only after applying the same SSRF checks."""
    current = await _safe_url(url)
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        follow_redirects=False,
        headers={"User-Agent": "MyKhaya recipe importer/1.0"},
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            async with client.stream("GET", current) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        return None
                    current = await _safe_url(urljoin(current, location))
                    continue
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if response.status_code >= 400 or not content_type.startswith("image/"):
                    return None
                try:
                    return await _read_limited(response, 10_000_000)
                except RecipeImportError:
                    return None
    return None
