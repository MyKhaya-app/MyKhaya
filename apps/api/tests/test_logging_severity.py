from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from starlette.requests import Request
from starlette.responses import Response

from mykhaya import audit as audit_module
from mykhaya import main, wishlist_link_preview
from mykhaya import platform_audit as platform_audit_module
from mykhaya.models import PlatformRole


def make_request(method: str = "GET", path: str = "/api/v1/test") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 1),
            "scheme": "http",
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [200, 400, 401, 404])
async def test_request_below_500_is_logged_at_info(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    calls: list[str] = []

    class Logger:
        async def ainfo(self, *_args: object, **_kwargs: object) -> None:
            calls.append("info")

        async def aerror(self, *_args: object, **_kwargs: object) -> None:
            calls.append("error")

    monkeypatch.setattr(main, "log", Logger())
    request = make_request()
    async def call_next(_request: Request) -> Response:
        return _response(status_code)

    response = await main.security_and_limits(request, call_next)
    assert response.status_code == status_code
    assert calls == ["info"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [500, 503])
async def test_request_5xx_is_logged_at_error(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    calls: list[str] = []

    class Logger:
        async def ainfo(self, *_args: object, **_kwargs: object) -> None:
            calls.append("info")

        async def aerror(self, *_args: object, **_kwargs: object) -> None:
            calls.append("error")

    monkeypatch.setattr(main, "log", Logger())
    request = make_request()
    async def call_next(_request: Request) -> Response:
        return _response(status_code)

    response = await main.security_and_limits(request, call_next)
    assert response.status_code == status_code
    assert calls == ["error"]


def _response(status_code: int) -> Response:
    return Response(status_code=status_code)


class CaptureLogger:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def info(self, *_args: object, **_kwargs: object) -> None:
        self.calls.append("info")

    def warning(self, *_args: object, **_kwargs: object) -> None:
        self.calls.append("warning")

    def error(self, *_args: object, **_kwargs: object) -> None:
        self.calls.append("error")


def test_successful_consumer_audit_remains_info(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = CaptureLogger()
    monkeypatch.setattr(audit_module, "log", logger)
    audit_module.audit(SimpleNamespace(add=lambda _event: None), make_request(), "item.created")
    assert logger.calls == ["info"]


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [("succeeded", "info"), ("denied", "warning"), ("failure", "error")],
)
def test_platform_audit_uses_explicit_outcome_severity(
    monkeypatch: pytest.MonkeyPatch, outcome: str, expected: str
) -> None:
    logger = CaptureLogger()
    monkeypatch.setattr(platform_audit_module.structlog, "get_logger", lambda _name: logger)
    context = SimpleNamespace(
        administrator=SimpleNamespace(id=uuid4(), role=PlatformRole.owner),
        session=SimpleNamespace(id=uuid4()),
        source_ip="127.0.0.1",
    )
    platform_audit_module.platform_audit(
        SimpleNamespace(add=lambda _event: None),
        make_request(),
        context,
        "administrator.test",
        outcome=outcome,
    )
    assert logger.calls == [expected]


@pytest.mark.asyncio
async def test_wishlist_upstream_timeout_is_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = CaptureLogger()
    monkeypatch.setattr(wishlist_link_preview, "log", logger)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider timed out", request=request)

    result = await wishlist_link_preview._fetch_safely(
        "http://93.184.216.34/", transport=httpx.MockTransport(handler)
    )
    assert result is None
    assert logger.calls == ["warning"]


def test_wishlist_parser_failure_is_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = CaptureLogger()
    monkeypatch.setattr(wishlist_link_preview, "log", logger)

    def fail_feed(_self: object, _text: str) -> None:
        raise RuntimeError("parser failure")

    monkeypatch.setattr(wishlist_link_preview._MetaExtractor, "feed", fail_feed)
    result = wishlist_link_preview._extract_metadata("<html>")
    assert result.title is None
    assert logger.calls == ["warning"]
