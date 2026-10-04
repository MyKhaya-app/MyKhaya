"""Small, fail-closed control plane for isolated legal test activity."""

from __future__ import annotations

import uuid
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.models import PlatformSetting

SETTING_KEY = "legal_test_mode"


class LegalTestModeConfiguration(TypedDict):
    enabled: bool
    test_user_ids: list[str]


async def configuration(db: AsyncSession, settings: Settings) -> LegalTestModeConfiguration:
    row = await db.scalar(select(PlatformSetting).where(PlatformSetting.key == SETTING_KEY))
    value = row.value if row and isinstance(row.value, dict) else {}
    enabled = bool(value.get("enabled"))
    if settings.environment == "production" and not settings.legal_test_mode_production_allowed:
        enabled = False
    users = value.get("test_user_ids", [])
    test_user_ids: list[str] = []
    if isinstance(users, list):
        for item in users:
            try:
                test_user_ids.append(str(uuid.UUID(str(item))))
            except (ValueError, AttributeError, TypeError):
                # A malformed persisted value must never widen test-mode access.
                continue
    return {"enabled": enabled, "test_user_ids": test_user_ids}


async def is_test_user(db: AsyncSession, settings: Settings, user_id: uuid.UUID) -> bool:
    state = await configuration(db, settings)
    return bool(state["enabled"]) and str(user_id) in state["test_user_ids"]
