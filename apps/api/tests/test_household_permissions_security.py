from unittest.mock import AsyncMock

import pytest
from fastapi import Request, Response
from pydantic import ValidationError

from mykhaya.config import Settings
from mykhaya.household_permissions import Capability, capabilities_for
from mykhaya.main import security_and_limits
from mykhaya.models import HouseholdRelationship, Membership, PermissionProfile


def membership_with_overrides(overrides: dict[str, bool]) -> Membership:
    return Membership(
        relationship=HouseholdRelationship.partner,
        permission_profile=PermissionProfile.standard_partner,
        permission_overrides=overrides,
    )


@pytest.mark.asyncio
async def test_only_explicitly_delegatable_overrides_change_capabilities() -> None:
    membership = membership_with_overrides(
        {
            "calendar.delete": False,
            "calendar.create": True,
            "billing.manage": True,
            "security.manage": True,
            "household.manage": True,
            "members.manage_relationships": True,
            "future.authority": True,
        }
    )

    capabilities = await capabilities_for(AsyncMock(), membership)

    assert Capability.calendar_delete not in capabilities
    assert Capability.calendar_create in capabilities
    assert Capability.billing_manage not in capabilities
    assert Capability.security_manage not in capabilities
    assert Capability.household_manage not in capabilities
    assert Capability.members_manage_relationships not in capabilities


@pytest.mark.asyncio
async def test_legacy_home_admin_profile_on_partner_is_fail_closed() -> None:
    membership = Membership(
        relationship=HouseholdRelationship.partner,
        permission_profile=PermissionProfile.home_admin,
        permission_overrides={"billing.manage": True},
    )

    capabilities = await capabilities_for(AsyncMock(), membership)

    assert Capability.billing_manage not in capabilities
    assert Capability.household_manage not in capabilities
    assert Capability.members_manage_relationships not in capabilities
    assert Capability.calendar_view in capabilities


def test_shared_development_cannot_disable_cookie_or_pcc_mfa() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="development",
            secret_key="test-only-random-secret-value-1234567890",
            public_web_url="https://dev.mykhaya.app",
            admin_url="https://admin.dev.mykhaya.app",
            status_url="https://status.dev.mykhaya.app",
            native_api_url="https://api.dev.mykhaya.app",
            trusted_hosts=[
                "dev.mykhaya.app",
                "admin.dev.mykhaya.app",
                "status.dev.mykhaya.app",
                "api.dev.mykhaya.app",
            ],
            cors_origins=[
                "https://dev.mykhaya.app",
                "https://admin.dev.mykhaya.app",
                "https://status.dev.mykhaya.app",
            ],
            cookie_secure=False,
            admin_mfa_required=False,
        )


def test_pure_local_development_can_explicitly_disable_both_controls() -> None:
    settings = Settings(
        environment="development",
        secret_key="test-only-random-secret-value-1234567890",
        public_web_url="http://localhost:8080",
        admin_url="http://admin.localhost:8080",
        status_url="http://status.localhost:8080",
        native_api_url="http://api.localhost:8080",
        trusted_hosts=["localhost", "admin.localhost", "status.localhost", "api.localhost"],
        cors_origins=["http://localhost:8080", "http://admin.localhost:8080", "http://status.localhost:8080"],
        cookie_secure=False,
        admin_mfa_required=False,
    )
    assert settings.cookie_secure is False
    assert settings.admin_mfa_required is False


def make_request(headers: list[tuple[bytes, bytes]], body: bytes) -> Request:
    delivered = False

    async def receive() -> dict[str, object]:
        nonlocal delivered
        if delivered:
            return {"type": "http.request", "body": b"", "more_body": False}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/groups",
            "raw_path": b"/api/v1/groups",
            "query_string": b"",
            "headers": headers,
            "scheme": "http",
            "server": ("localhost", 8080),
            "client": ("127.0.0.1", 1234),
        },
        receive,
    )


@pytest.mark.asyncio
async def test_request_body_guard_rejects_malformed_length_and_chunked_overflow() -> None:
    malformed = make_request([(b"content-length", b"not-a-number")], b"{}")
    response = await security_and_limits(malformed, AsyncMock())
    assert response.status_code == 400

    oversized = make_request([], b"x" * (1_048_576 + 1))
    async def consume_body(request: Request) -> Response:
        await request.body()
        return Response("ok")

    response = await security_and_limits(oversized, consume_body)
    assert response.status_code == 413
