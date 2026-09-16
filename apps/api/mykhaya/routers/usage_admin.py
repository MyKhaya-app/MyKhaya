"""PCC-only aggregate reporting for product usage."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import get_settings
from mykhaya.db import get_db
from mykhaya.models import (
    Group,
    ManagedDemoHome,
    ManagedDemoType,
    PlatformRole,
    ProductUsageEvent,
    ProductUsageEventName,
    ProductUsageModule,
    ProductUsagePlatform,
    User,
)
from mykhaya.platform_security import PlatformContext, require_recent_auth, require_roles

router = APIRouter(prefix="/platform/usage", tags=["platform-usage"])


class UsageClassification(StrEnum):
    production = "production"
    all = "all"
    demo = "demo"
    test = "test"
    apple_review = "apple_review"


def _date_range(days: int, end: date | None) -> tuple[datetime, datetime, date]:
    if days not in (7, 30, 90):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "days must be 7, 30, or 90")
    last = end or datetime.now(UTC).date()
    start = last - timedelta(days=days - 1)
    return (
        datetime.combine(start, datetime.min.time(), tzinfo=UTC),
        datetime.combine(last + timedelta(days=1), datetime.min.time(), tzinfo=UTC),
        start,
    )


def _classification_clause(classification: UsageClassification):
    if classification is UsageClassification.all:
        return None
    if classification is UsageClassification.production:
        return (
            or_(
                ProductUsageEvent.group_id.is_(None),
                ~ProductUsageEvent.group_id.in_(select(ManagedDemoHome.home_id)),
            ),
            or_(
                ProductUsageEvent.user_id.is_(None),
                ~ProductUsageEvent.user_id.in_(select(ManagedDemoHome.owner_user_id)),
            ),
        )
    types = {
        UsageClassification.demo: (ManagedDemoType.demo, ManagedDemoType.free_demo),
        UsageClassification.test: (ManagedDemoType.qa_test,),
        UsageClassification.apple_review: (ManagedDemoType.apple_review,),
    }[classification]
    homes = select(ManagedDemoHome.home_id).where(ManagedDemoHome.fixture_type.in_(types))
    owners = select(ManagedDemoHome.owner_user_id).where(ManagedDemoHome.fixture_type.in_(types))
    return (ProductUsageEvent.group_id.in_(homes) | ProductUsageEvent.user_id.in_(owners),)


async def _report(
    db: AsyncSession,
    *,
    days: int,
    end_date: date | None,
    classification: UsageClassification,
    platform: ProductUsagePlatform | None,
) -> dict[str, object]:
    start, end, start_date = _date_range(days, end_date)
    clauses = [ProductUsageEvent.occurred_at >= start, ProductUsageEvent.occurred_at < end]
    if platform is not None:
        clauses.append(ProductUsageEvent.platform == platform)
    classification_clauses = _classification_clause(classification)
    if classification_clauses:
        clauses.extend(classification_clauses)
    rows = (await db.scalars(select(ProductUsageEvent).where(*clauses))).all()
    # Window metrics and returning-user classification need bounded history
    # outside the selected trend period. The 90-day bound matches raw-event
    # retention and keeps this admin report predictable on large installations.
    history_start = min(start - timedelta(days=90), end - timedelta(days=30))
    history_clauses = [
        ProductUsageEvent.occurred_at >= history_start,
        ProductUsageEvent.occurred_at < end,
    ]
    if platform is not None:
        history_clauses.append(ProductUsageEvent.platform == platform)
    if classification_clauses:
        history_clauses.extend(classification_clauses)
    history_rows = (await db.scalars(select(ProductUsageEvent).where(*history_clauses))).all()
    user_ids = {row.user_id for row in rows if row.user_id}
    group_ids = {row.group_id for row in rows if row.group_id}
    users = (
        {
            user.id: user
            for user in (await db.scalars(select(User).where(User.id.in_(user_ids)))).all()
        }
        if user_ids
        else {}
    )
    active_users = len(user_ids)
    active_homes = len(group_ids)
    sessions = {row.usage_session_id for row in rows if row.usage_session_id}
    daily: list[dict[str, object]] = []
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        day_rows = [row for row in rows if row.occurred_at.astimezone(UTC).date() == day]
        daily.append(
            {
                "date": day.isoformat(),
                "active_users": len({row.user_id for row in day_rows if row.user_id}),
                "active_homes": len({row.group_id for row in day_rows if row.group_id}),
            }
        )

    def window_users(window_days: int) -> int:
        cutoff = end - timedelta(days=window_days)
        return len(
            {row.user_id for row in history_rows if row.user_id and row.occurred_at >= cutoff}
        )

    new_users = sum(
        1
        for user_id in user_ids
        if users.get(user_id) is not None
        and users[user_id].created_at >= start
        and users[user_id].created_at < end
    )
    prior_user_ids = {
        row.user_id for row in history_rows if row.user_id and row.occurred_at < start
    }
    returning_users = len(user_ids & prior_user_ids)

    modules: list[dict[str, object]] = []
    for module in ProductUsageModule:
        module_rows = [row for row in rows if row.module == module]
        if module_rows:
            module_users = len({row.user_id for row in module_rows if row.user_id})
            modules.append(
                {
                    "module": module.value,
                    "active_users": module_users,
                    "event_count": len(module_rows),
                    "share_of_active_users": round(module_users * 100 / active_users, 1)
                    if active_users
                    else 0,
                }
            )

    platforms: list[dict[str, object]] = []
    for item in ProductUsagePlatform:
        platform_rows = [row for row in rows if row.platform == item]
        platform_users = len({row.user_id for row in platform_rows if row.user_id})
        platforms.append(
            {
                "platform": item.value,
                "active_users": platform_users,
                "usage_sessions": len(
                    {row.usage_session_id for row in platform_rows if row.usage_session_id}
                ),
                "event_count": len(platform_rows),
                "share_of_global_users": round(platform_users * 100 / active_users, 1)
                if active_users
                else 0,
            }
        )
    event_breakdown = [
        {"event_name": event.value, "event_count": sum(row.event_name == event for row in rows)}
        for event in ProductUsageEventName
        if any(row.event_name == event for row in rows)
    ]
    eligible_homes = (
        await db.scalar(select(func.count(Group.id)).where(Group.is_active.is_(True))) or 0
    )
    return {
        "period": {
            "start": start_date.isoformat(),
            "end": (end - timedelta(days=1)).date().isoformat(),
            "days": days,
            "timezone": "UTC",
        },
        "filters": {
            "classification": classification.value,
            "platform": platform.value if platform else "all",
        },
        "overview": {
            "active_users": active_users,
            "active_homes": active_homes,
            "usage_sessions": len(sessions),
            "product_events": len(rows),
        },
        "engagement": {
            "dau": daily[-1]["active_users"] if daily else 0,
            "wau": window_users(7),
            "mau": window_users(30),
            "returning_users": returning_users,
            "new_users": new_users,
        },
        "homes": {"active": active_homes, "eligible": eligible_homes},
        "trend": daily,
        "modules": modules,
        "platforms": platforms,
        "events": event_breakdown,
    }


@router.get("/report")
async def usage_report(
    days: Annotated[int, Query(ge=7, le=90)] = 30,
    end_date: date | None = None,
    classification: UsageClassification = UsageClassification.production,
    platform: ProductUsagePlatform | None = None,
    context: PlatformContext = Depends(
        require_roles(PlatformRole.owner, PlatformRole.administrator, PlatformRole.support)
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    require_recent_auth(context, get_settings())
    return await _report(
        db, days=days, end_date=end_date, classification=classification, platform=platform
    )
