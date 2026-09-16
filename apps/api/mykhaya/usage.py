"""Privacy-minimised product usage events and UTC daily aggregation."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import structlog
from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.models import (
    ManagedDemoHome,
    ProductUsageDailyAggregate,
    ProductUsageEvent,
    ProductUsageEventName,
    ProductUsageModule,
    ProductUsagePlatform,
)

log = structlog.get_logger("product_usage")
RAW_RETENTION = timedelta(days=90)


def platform_from_request(request: Request) -> ProductUsagePlatform:
    """Use the existing native client header for attribution only."""
    value = request.headers.get("X-MyKhaya-Platform", "").strip().lower()
    if value in {ProductUsagePlatform.ios.value, "iphone", "ipad"}:
        return ProductUsagePlatform.ios
    if value == ProductUsagePlatform.android.value:
        return ProductUsagePlatform.android
    return ProductUsagePlatform.web


async def record_usage_event(
    db: AsyncSession,
    *,
    event_name: ProductUsageEventName,
    platform: ProductUsagePlatform,
    user_id: uuid.UUID | None,
    group_id: uuid.UUID | None = None,
    module: ProductUsageModule | None = None,
    app_version: str | None = None,
    usage_session_id: str | None = None,
    event_key: str | None = None,
) -> ProductUsageEvent | None:
    """Insert a server-timed event. Analytics failures never escape callers."""
    try:
        row = ProductUsageEvent(
            event_name=event_name,
            occurred_at=datetime.now(UTC),
            user_id=user_id,
            group_id=group_id,
            platform=platform,
            module=module,
            app_version=app_version,
            usage_session_id=usage_session_id,
            event_key=event_key,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row
    except IntegrityError:
        await db.rollback()
        return await db.scalar(
            select(ProductUsageEvent).where(ProductUsageEvent.event_key == event_key)
        ) if event_key else None
    except Exception:  # noqa: BLE001 - analytics must not break product flows
        await db.rollback()
        log.warning("usage_event_record_failed", event_name=event_name.value)
        return None


async def purge_expired_usage_events(db: AsyncSession, *, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now(UTC)) - RAW_RETENTION
    result = await db.execute(
        delete(ProductUsageEvent).where(ProductUsageEvent.occurred_at < cutoff)
    )
    return int(result.rowcount or 0)


async def aggregate_usage_day(db: AsyncSession, reporting_date: date) -> int:
    """Recompute one UTC day; deleting the day first makes reruns idempotent."""
    start = datetime(reporting_date.year, reporting_date.month, reporting_date.day, tzinfo=UTC)
    end = start + timedelta(days=1)
    rows = (
        await db.scalars(
            select(ProductUsageEvent)
            .where(ProductUsageEvent.occurred_at >= start, ProductUsageEvent.occurred_at < end)
            .order_by(ProductUsageEvent.occurred_at)
        )
    ).all()
    managed_home_ids = set(await db.scalars(select(ManagedDemoHome.home_id)))
    managed_owner_ids = set(await db.scalars(select(ManagedDemoHome.owner_user_id)))
    rows = [
        row for row in rows
        if row.group_id not in managed_home_ids and row.user_id not in managed_owner_ids
    ]
    await db.execute(
        delete(ProductUsageDailyAggregate).where(
            ProductUsageDailyAggregate.reporting_date == reporting_date
        )
    )
    dimensions: list[tuple[str, ProductUsageModule | None, ProductUsagePlatform | None, int]] = []
    dimensions.append(("active_users", None, None, len({r.user_id for r in rows if r.user_id})))
    dimensions.append(("active_homes", None, None, len({r.group_id for r in rows if r.group_id})))
    session_ids = {r.usage_session_id for r in rows if r.usage_session_id}
    dimensions.append(("usage_sessions", None, None, len(session_ids)))
    dimensions.append(("event_count", None, None, len(rows)))
    for platform in ProductUsagePlatform:
        platform_rows = [r for r in rows if r.platform == platform]
        dimensions.append(
            ("active_users", None, platform, len({r.user_id for r in platform_rows if r.user_id}))
        )
        dimensions.append(("event_count", None, platform, len(platform_rows)))
    for module in ProductUsageModule:
        module_rows = [r for r in rows if r.module == module]
        if module_rows:
            dimensions.append(
                ("active_users", module, None, len({r.user_id for r in module_rows if r.user_id}))
            )
            dimensions.append(("event_count", module, None, len(module_rows)))
    for metric, module, platform, value in dimensions:
        db.add(ProductUsageDailyAggregate(
            reporting_date=reporting_date, metric=metric, module=module,
            platform=platform, value=value,
        ))
    await db.commit()
    return len(dimensions)


async def aggregate_recent_usage(db: AsyncSession, *, now: datetime | None = None) -> int:
    current = now or datetime.now(UTC)
    return await aggregate_usage_day(db, (current - timedelta(days=1)).date())
