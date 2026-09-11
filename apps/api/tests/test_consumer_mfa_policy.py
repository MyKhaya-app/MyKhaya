from types import SimpleNamespace
import uuid
from unittest.mock import AsyncMock

import pytest

from mykhaya.config import get_settings
from mykhaya.consumer_mfa_policy import resolve_consumer_mfa_policy
from mykhaya.models import ConsumerMfaPolicy


def fake_db(*, platform: dict | None, homes: list[tuple[uuid.UUID, ConsumerMfaPolicy, list[str] | None]], user_policy: ConsumerMfaPolicy = ConsumerMfaPolicy.inherit, user_methods: list[str] | None = None):
    db = SimpleNamespace()
    db.scalar = AsyncMock(return_value=SimpleNamespace(value=platform) if platform else None)
    db.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: homes))
    db.get = AsyncMock(return_value=SimpleNamespace(mfa_policy=user_policy, mfa_allowed_methods=user_methods))
    return db


@pytest.mark.asyncio
async def test_platform_required_cannot_be_weakened_by_inherited_home_or_user() -> None:
    db = fake_db(
        platform={"policy": "required", "allowed_methods": ["totp", "email"]},
        homes=[(uuid.uuid4(), ConsumerMfaPolicy.inherit, None)],
    )
    result = await resolve_consumer_mfa_policy(db, uuid.uuid4(), get_settings())
    assert result.required is True
    assert result.source == "platform"


@pytest.mark.asyncio
async def test_home_required_is_stricter_than_optional_platform() -> None:
    db = fake_db(
        platform={"policy": "optional", "allowed_methods": ["totp", "email"]},
        homes=[(uuid.uuid4(), ConsumerMfaPolicy.required, None)],
    )
    result = await resolve_consumer_mfa_policy(db, uuid.uuid4(), get_settings())
    assert result.required is True
    assert result.source == "home"


@pytest.mark.asyncio
async def test_user_required_is_stricter_than_inherited_home() -> None:
    db = fake_db(
        platform={"policy": "optional", "allowed_methods": ["totp", "email"]},
        homes=[(uuid.uuid4(), ConsumerMfaPolicy.optional, None)],
        user_policy=ConsumerMfaPolicy.required,
    )
    result = await resolve_consumer_mfa_policy(db, uuid.uuid4(), get_settings())
    assert result.required is True
    assert result.source == "user"


@pytest.mark.asyncio
async def test_lower_scope_method_restrictions_intersect_parent_methods() -> None:
    db = fake_db(
        platform={"policy": "required", "allowed_methods": ["totp", "email"]},
        homes=[(uuid.uuid4(), ConsumerMfaPolicy.inherit, ["email"])],
        user_methods=["email"],
    )
    result = await resolve_consumer_mfa_policy(db, uuid.uuid4(), get_settings())
    assert result.allowed_methods == frozenset({"email"})
