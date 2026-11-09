"""Read-only connectivity probe for live acceptance of the public-route checks.

Run inside the container that hosts the monitor (the scheduler), so the
network path, DNS resolver and egress are exactly the monitor's:

    docker compose exec scheduler python -m mykhaya.monitoring.probe https://dev.mykhaya.app/
    docker compose exec scheduler python -m mykhaya.monitoring.probe \
        https://api.dev.mykhaya.app/api/v1/health/ready --expect-json status=ready

It reports each layer separately (DNS -> TCP/TLS with certificate validation
-> HTTP via Cloudflare -> body) and finishes with the verdict the monitor
itself would record, using the same classification code and User-Agent. It
sends one GET; it never authenticates, posts or follows sign-in flows.
"""

from __future__ import annotations

import argparse
import asyncio
import socket
import ssl
import sys
import time
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from mykhaya.monitoring.checks import classify_public_route, network_failure
from mykhaya.monitoring.engine import USER_AGENT
from mykhaya.monitoring.results import category_label


def _line(step: str, ok: bool, detail: str) -> None:
    print(f"[{'OK  ' if ok else 'FAIL'}] {step:<6} {detail}")


def _dns(host: str, port: int, timeout: float) -> bool:
    socket.setdefaulttimeout(timeout)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        _line("DNS", False, f"{host} did not resolve ({exc.strerror})")
        return False
    addresses = sorted({str(info[4][0]) for info in infos})
    _line("DNS", True, f"{host} -> {', '.join(addresses)}")
    return True


def _name_field(name: object, field: str) -> str | None:
    """Pull one attribute out of getpeercert()'s nested ((key, value),) RDNs."""
    if not isinstance(name, tuple):
        return None
    for rdn in name:
        if isinstance(rdn, tuple):
            for pair in rdn:
                if isinstance(pair, tuple) and len(pair) == 2 and pair[0] == field:
                    return str(pair[1])
    return None


def _tls(host: str, port: int, timeout: float) -> bool:
    context = ssl.create_default_context()
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                cert = tls.getpeercert() or {}
                version = tls.version()
    except ssl.SSLCertVerificationError as exc:
        _line("TLS", False, f"certificate validation failed: {exc.verify_message}")
        return False
    except (TimeoutError, OSError, ssl.SSLError) as exc:
        _line("TLS", False, f"{type(exc).__name__} connecting to {host}:{port}")
        return False
    subject = _name_field(cert.get("subject"), "commonName")
    issuer = _name_field(cert.get("issuer"), "organizationName")
    not_after = cert.get("notAfter")
    if not isinstance(not_after, str):
        _line("TLS", False, "the certificate has no expiry date")
        return False
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), UTC)
    days = (expires - datetime.now(UTC)).days
    _line(
        "TLS",
        True,
        f"{version}, CN={subject}, issuer={issuer}, "
        f"expires {expires:%Y-%m-%d} ({days} days), "
        f"{int((time.monotonic() - started) * 1000)} ms",
    )
    return True


async def _http(url: str, timeout_seconds: float, expect_json: str | None) -> int:
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        started = time.monotonic()
        try:
            response = await client.get(url, timeout=timeout_seconds, follow_redirects=True)
        except httpx.HTTPError as exc:
            result = network_failure(exc, urlsplit(url).hostname or url)
            _line("HTTP", False, f"{type(exc).__name__}: {result.detail}")
            print(f"\nMonitor verdict: FAILURE / {category_label(result.category)}")
            return 1
        elapsed = int((time.monotonic() - started) * 1000)
    headers = response.headers
    _line(
        "HTTP",
        response.status_code < 400,
        f"{response.status_code} in {elapsed} ms; server={headers.get('server')}; "
        f"cf-ray={headers.get('cf-ray')}; cf-cache-status={headers.get('cf-cache-status')}; "
        f"cf-mitigated={headers.get('cf-mitigated')}; content-type={headers.get('content-type')}",
    )
    body = " ".join(response.text[:300].split())
    print(f"       body   {body!r}")
    verdict = classify_public_route(response, urlsplit(url).hostname or url)
    if verdict is None and expect_json:
        key, _, expected = expect_json.partition("=")
        try:
            actual = str(response.json().get(key))
        except ValueError:
            actual = "<not JSON>"
        if actual != expected:
            print(f"\nMonitor verdict: FAILURE / Unexpected response ({key}={actual!r})")
            return 1
    if verdict is None:
        print("\nMonitor verdict: SUCCESS")
        return 0
    kind = "CANNOT VERIFY (monitor error)" if verdict.outcome == "monitor_error" else "FAILURE"
    print(f"\nMonitor verdict: {kind} / {category_label(verdict.category)}: {verdict.detail}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("url")
    parser.add_argument("--timeout", type=float, default=10.0, help="seconds (monitor default 10)")
    parser.add_argument("--expect-json", help="key=value the JSON body must contain")
    args = parser.parse_args(argv)
    parts = urlsplit(args.url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    print(f"Probing {args.url} as {USER_AGENT!r} (timeout {args.timeout}s)\n")
    if not _dns(host, port, args.timeout):
        print(f"\nMonitor verdict: FAILURE / {category_label('dns')}")
        return 1
    if parts.scheme == "https" and not _tls(host, port, args.timeout):
        print(f"\nMonitor verdict: FAILURE / {category_label('tls')} (or connectivity)")
        return 1
    return asyncio.run(_http(args.url, args.timeout, args.expect_json))


if __name__ == "__main__":
    sys.exit(main())
