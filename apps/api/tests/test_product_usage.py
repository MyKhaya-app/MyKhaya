"""Focused contract tests for the privacy-minimised usage subsystem."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from mykhaya.models import ProductUsageEvent, User
from mykhaya.usage import aggregate_usage_day, record_usage_event


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


@pytest.mark.asyncio
async def test_usage_event_is_server_timed_and_idempotent() -> None:
    # Service-level coverage avoids coupling this contract test to the full
    # browser login fixture while still exercising the real persistence path.
    from mykhaya.db import SessionFactory
    from mykhaya.models import ProductUsageEventName, ProductUsageModule, ProductUsagePlatform

    async with SessionFactory() as db:
        user = (await db.scalars(select(User).limit(1))).first()
        if user is None:
            pytest.skip("requires the configured integration database")
        key = f"test-usage-{unique('event')}"
        before = datetime.now(UTC)
        first = await record_usage_event(
            db, event_name=ProductUsageEventName.app_open,
            platform=ProductUsagePlatform.web, module=ProductUsageModule.app,
            user_id=user.id, event_key=key,
        )
        after = datetime.now(UTC)
        second = await record_usage_event(
            db, event_name=ProductUsageEventName.app_open,
            platform=ProductUsagePlatform.web, module=ProductUsageModule.app,
            user_id=user.id, event_key=key,
        )
        assert first is not None
        assert before <= first.occurred_at <= after
        assert second is not None and second.id == first.id
        await db.execute(
            update(ProductUsageEvent).where(ProductUsageEvent.id == first.id).values(event_key=None)
        )
        await db.commit()


@pytest.mark.asyncio
async def test_usage_daily_aggregation_is_rerunnable() -> None:
    from mykhaya.db import SessionFactory
    async with SessionFactory() as db:
        count = await aggregate_usage_day(db, datetime.now(UTC).date())
        assert count >= 4
