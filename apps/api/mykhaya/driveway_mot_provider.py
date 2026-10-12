"""MOT history provider for Driveway (DVSA MOT History API, GB vehicles).

Everything DVSA-specific lives here — authentication, HTTP, retries, error
translation and response normalisation — so the rest of MyKhaya only ever
sees the provider-neutral ``MotHistory`` / ``MotTestRecord`` /
``MotDefectRecord`` structures below.

Authentication (confirmed against the official DVSA documentation,
documentation.history.mot.api.gov.uk): OAuth 2.0 client credentials issued
by Microsoft Entra ID — a form POST of grant_type/client_id/client_secret/
scope to the tenant token URL from the DVSA credentials email — and every
API request carries ``Authorization: Bearer <token>`` plus
``X-API-Key: <api key>``. Tokens last 60 minutes; they are cached in-process
and refreshed early. Lookup: ``GET {base}/registration/{VRM}`` with base
``https://history.mot.api.gov.uk/v1/trade/vehicles``.

Rate limits (DVSA): 15 requests/second average, burst 10, 500,000/day;
exceeding them returns 429 (MOTH-RL-01/02). 429 is never retried here.

Security: credentials, tokens and registrations are never logged, never put
in an exception message and never returned. The registration passed in must
come from mykhaya.driveway_sensitive.registration_for_provider — this module
never touches a Vehicle row.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from mykhaya.config import Settings

PROVIDER_NAME = "dvsa"
_VRM_PATTERN = re.compile(r"^[A-Z0-9]{1,10}$")
# Refresh the cached token this long before DVSA would expire it.
_TOKEN_SAFETY_SECONDS = 120
MAX_ATTEMPTS = 2


# --- Normalised, provider-neutral results ---------------------------------------


@dataclass(frozen=True)
class MotDefectRecord:
    text: str
    # dangerous | major | minor | advisory | prs | fail | user_entered | other
    category: str
    dangerous: bool


@dataclass(frozen=True)
class MotTestRecord:
    test_number: str | None
    completed_at: datetime | None
    test_date: date
    expiry_date: date | None
    # passed | failed | other
    result: str
    odometer_value: int | None
    odometer_unit: str | None
    odometer_result: str | None
    defects: tuple[MotDefectRecord, ...] = ()


@dataclass(frozen=True)
class MotHistory:
    tests: tuple[MotTestRecord, ...]
    # For a vehicle that has not yet needed an MOT (DVSA "motTestDueDate").
    first_mot_due_date: date | None = None
    provider: str = PROVIDER_NAME


# --- Errors (category is safe to log, store and show in PCC) ------------------------


class MotLookupError(Exception):
    category = "unavailable"

    def __init__(self, message: str = "The MOT provider request failed.") -> None:
        super().__init__(message)


class MotNotConfigured(MotLookupError):
    category = "not_configured"


class MotVehicleNotFound(MotLookupError):
    category = "not_found"


class MotAuthFailed(MotLookupError):
    category = "auth_failed"


class MotRateLimited(MotLookupError):
    category = "rate_limited"


class MotUnavailable(MotLookupError):
    category = "unavailable"


class MotMalformedResponse(MotLookupError):
    category = "malformed"


class MotHistoryProvider(Protocol):
    name: str

    async def fetch(self, registration: str) -> MotHistory: ...


# --- Parsing helpers -------------------------------------------------------------------

_DATE_FORMATS = ("%Y-%m-%d", "%Y.%m.%d")
_DATETIME_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y.%m.%d %H:%M:%S",
)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
        for fmt in _DATETIME_FORMATS:
            try:
                parsed = datetime.strptime(value.strip(), fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    parsed = _parse_datetime(text)
    return parsed.date() if parsed else None


def _normalise_result(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"PASSED", "PASS", "PASSED WITH DEFECTS"}:
        return "passed"
    if text in {"FAILED", "FAIL"}:
        return "failed"
    return "other"


_DEFECT_CATEGORIES = {
    "DANGEROUS": "dangerous",
    "MAJOR": "major",
    "MINOR": "minor",
    "ADVISORY": "advisory",
    "PRS": "prs",
    "FAIL": "fail",
    "USER ENTERED": "user_entered",
}


def _normalise_defect(raw: Any) -> MotDefectRecord | None:
    if not isinstance(raw, dict):
        raise MotMalformedResponse("An MOT defect entry was not an object.")
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip():
        return None  # an empty defect line carries no information
    category = _DEFECT_CATEGORIES.get(str(raw.get("type") or "").strip().upper(), "other")
    dangerous = raw.get("dangerous") is True or category == "dangerous"
    return MotDefectRecord(text=text.strip()[:2000], category=category, dangerous=dangerous)


def _normalise_odometer(raw: dict[str, Any]) -> tuple[int | None, str | None, str | None]:
    value_raw = raw.get("odometerValue")
    value: int | None = None
    if isinstance(value_raw, int) and value_raw >= 0:
        value = value_raw
    elif isinstance(value_raw, str) and value_raw.strip().isdigit():
        value = int(value_raw.strip())
    unit_raw = str(raw.get("odometerUnit") or "").strip().lower()
    unit = unit_raw if unit_raw in {"mi", "km"} else None
    result_raw = str(raw.get("odometerResultType") or "").strip().upper()
    result = {
        "READ": "read",
        "NO_ODOMETER": "no_odometer",
        "UNREADABLE": "unreadable",
    }.get(result_raw, "other" if result_raw else None)
    if value is None:
        unit = None
    return value, unit, result


def _normalise_test(raw: Any) -> MotTestRecord:
    if not isinstance(raw, dict):
        raise MotMalformedResponse("An MOT test entry was not an object.")
    completed_at = _parse_datetime(raw.get("completedDate"))
    test_date = completed_at.date() if completed_at else _parse_date(raw.get("completedDate"))
    if test_date is None:
        raise MotMalformedResponse("An MOT test had no usable completion date.")
    defects_raw = raw.get("defects") or raw.get("rfrAndComments") or []
    if not isinstance(defects_raw, list):
        raise MotMalformedResponse("MOT test defects were not a list.")
    defects = tuple(d for d in (_normalise_defect(item) for item in defects_raw) if d is not None)
    number = raw.get("motTestNumber")
    test_number = str(number).strip()[:32] if number not in (None, "") else None
    odometer_value, odometer_unit, odometer_result = _normalise_odometer(raw)
    return MotTestRecord(
        test_number=test_number or None,
        completed_at=completed_at,
        test_date=test_date,
        expiry_date=_parse_date(raw.get("expiryDate")),
        result=_normalise_result(raw.get("testResult")),
        odometer_value=odometer_value,
        odometer_unit=odometer_unit,
        odometer_result=odometer_result,
        defects=defects,
    )


def normalise_mot_response(payload: Any) -> MotHistory:
    """Turn a DVSA registration response into a ``MotHistory``. Strict where
    a wrong answer would mislead (missing test dates, wrong types) and
    tolerant of absent optional fields. Never retains registration, make,
    model or any other field MyKhaya does not need."""
    if isinstance(payload, list) and len(payload) == 1:
        payload = payload[0]
    if not isinstance(payload, dict):
        raise MotMalformedResponse("The MOT response was not an object.")
    tests_raw = payload.get("motTests")
    if tests_raw is None:
        tests_raw = []
    if not isinstance(tests_raw, list):
        raise MotMalformedResponse("motTests was not a list.")
    tests = [_normalise_test(item) for item in tests_raw]
    # Duplicate test numbers in one response would violate history
    # uniqueness; keep the first occurrence only.
    seen: set[str] = set()
    unique: list[MotTestRecord] = []
    for test in tests:
        if test.test_number and test.test_number in seen:
            continue
        if test.test_number:
            seen.add(test.test_number)
        unique.append(test)
    unique.sort(
        key=lambda t: t.completed_at or datetime.combine(t.test_date, datetime.min.time(), UTC),
        reverse=True,
    )
    return MotHistory(
        tests=tuple(unique),
        first_mot_due_date=_parse_date(payload.get("motTestDueDate")),
    )


def canonical_vrm(registration: str) -> str:
    """DVSA expects the VRM without spaces, upper-case. Anything outside
    [A-Z0-9] cannot be a valid VRM and is rejected before any request."""
    vrm = "".join(registration.upper().split())
    if not _VRM_PATTERN.fullmatch(vrm):
        raise MotVehicleNotFound("The registration is not a valid UK registration.")
    return vrm


# --- DVSA client -------------------------------------------------------------------------


@dataclass
class _TokenCache:
    token: str | None = None
    expires_at: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# Process-wide cache: one token per process, refreshed ahead of expiry, and
# a lock so concurrent refreshes do not stampede the token endpoint.
_TOKEN_CACHE = _TokenCache()


def reset_token_cache() -> None:
    _TOKEN_CACHE.token = None
    _TOKEN_CACHE.expires_at = 0.0


class DvsaMotHistoryProvider:
    name = PROVIDER_NAME

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not settings.dvsa_configured:
            raise MotNotConfigured("The MOT provider is not configured.")
        assert settings.dvsa_token_url and settings.dvsa_client_id
        assert settings.dvsa_client_secret and settings.dvsa_api_key
        self._token_url = settings.dvsa_token_url
        self._scope = settings.dvsa_scope
        self._client_id = settings.dvsa_client_id.get_secret_value()
        self._client_secret = settings.dvsa_client_secret.get_secret_value()
        self._api_key = settings.dvsa_api_key.get_secret_value()
        self._base_url = settings.dvsa_api_base_url.rstrip("/")
        self._timeout = settings.dvsa_timeout_seconds
        self._transport = transport
        self._sleep = sleep
        self._clock = clock

    def __repr__(self) -> str:
        return "DvsaMotHistoryProvider(<credentials redacted>)"

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=self._timeout)

    async def _token(self, client: httpx.AsyncClient, *, force: bool = False) -> str:
        async with _TOKEN_CACHE.lock:
            if (
                not force
                and _TOKEN_CACHE.token
                and self._clock() < _TOKEN_CACHE.expires_at - _TOKEN_SAFETY_SECONDS
            ):
                return _TOKEN_CACHE.token
            try:
                response = await client.post(
                    self._token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "scope": self._scope,
                    },
                )
            except httpx.HTTPError:
                raise MotUnavailable("The MOT provider token service is unavailable.") from None
            if response.status_code in {400, 401, 403}:
                raise MotAuthFailed("The MOT provider rejected the configured credentials.")
            if response.status_code >= 400:
                raise MotUnavailable("The MOT provider token service is unavailable.")
            try:
                body = response.json()
                token = body["access_token"]
                lifetime = float(body.get("expires_in", 3600))
            except (ValueError, KeyError, TypeError):
                raise MotMalformedResponse(
                    "The MOT provider token response was malformed."
                ) from None
            if not isinstance(token, str) or not token:
                raise MotMalformedResponse("The MOT provider token response was malformed.")
            _TOKEN_CACHE.token = token
            _TOKEN_CACHE.expires_at = self._clock() + max(lifetime, 0.0)
            return token

    @staticmethod
    def _error_code(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return ""
        if isinstance(body, dict):
            for key in ("errorCode", "code", "error_code"):
                value = body.get(key)
                if isinstance(value, str):
                    return value.upper()
        return ""

    async def fetch(self, registration: str) -> MotHistory:
        vrm = canonical_vrm(registration)
        url = f"{self._base_url}/registration/{quote(vrm, safe='')}"
        async with self._client() as client:
            refreshed_token = False
            attempt = 0
            while True:
                attempt += 1
                token = await self._token(client)
                try:
                    response = await client.get(
                        url,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "X-API-Key": self._api_key,
                            "Accept": "application/json",
                        },
                    )
                except (httpx.TimeoutException, httpx.TransportError):
                    if attempt < MAX_ATTEMPTS:
                        await self._sleep(0.5 * attempt)
                        continue
                    raise MotUnavailable("The MOT provider did not respond in time.") from None
                status = response.status_code
                if status == 200:
                    try:
                        payload = response.json()
                    except ValueError:
                        raise MotMalformedResponse("The MOT response was not JSON.") from None
                    return normalise_mot_response(payload)
                code = self._error_code(response)
                if status == 404 or code in {"MOTH-NF-01", "MOTH-IV-03"}:
                    raise MotVehicleNotFound("The vehicle was not found by the MOT provider.")
                if status == 429 or code.startswith("MOTH-RL"):
                    raise MotRateLimited("The MOT provider rate limit was reached.")
                if status in {401, 403}:
                    # An expired/rejected token gets exactly one fresh-token retry.
                    if not refreshed_token and code in {"MOTH-FB-02", "MOTH-UA-01", ""}:
                        refreshed_token = True
                        await self._token(client, force=True)
                        continue
                    raise MotAuthFailed("The MOT provider rejected the request credentials.")
                if status >= 500:
                    if attempt < MAX_ATTEMPTS:
                        await self._sleep(0.5 * attempt)
                        continue
                    raise MotUnavailable("The MOT provider is unavailable.")
                # Remaining 4xx: a request MyKhaya built wrongly — not retried.
                raise MotUnavailable("The MOT provider rejected the request.")
