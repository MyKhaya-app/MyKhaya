# ruff: noqa: E501

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.audit import audit
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context
from mykhaya.household_permissions import Capability, require_capability
from mykhaya.models import (
    ChildProfile,
    HomeCalendarHighlightSettings,
    HomeHolidaySubscription,
    Membership,
    PlatformHolidayDate,
    PlatformHolidaySource,
    User,
)
from mykhaya.schemas import (
    CalendarHighlightsBirthday,
    CalendarHighlightsHoliday,
    CalendarHighlightsResponse,
    CalendarHighlightsSettingsResponse,
    HolidaySourceResponse,
    HomeCalendarHighlightsUpdate,
    HomeHolidaySubscriptionCreate,
    HomeHolidaySubscriptionResponse,
    HomeHolidaySubscriptionUpdate,
)

router = APIRouter(prefix="/homes", tags=["calendar-highlights"])


async def _source_response(db: AsyncSession, source: PlatformHolidaySource) -> HolidaySourceResponse:
    count = await db.scalar(select(func.count()).select_from(PlatformHolidayDate).where(PlatformHolidayDate.source_id == source.id))
    return HolidaySourceResponse(
        id=source.id, country_code=source.country_code, country_name=source.country_name,
        flag_emoji=source.flag_emoji, region_code=source.region_code, region_name=source.region_name,
        provider=source.provider, source_url=source.source_url, enabled=source.enabled,
        sync_status=source.sync_status, last_successful_sync=source.last_successful_sync,
        next_scheduled_sync=source.next_scheduled_sync, last_sync_error=source.last_sync_error,
        cached_holiday_count=count or 0,
    )


@router.get("/{home_id}/calendar-highlights", response_model=CalendarHighlightsSettingsResponse)
async def get_calendar_highlights_settings(
    home_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> CalendarHighlightsSettingsResponse:
    await require_capability(home_id, Capability.calendar_view, auth, db)
    settings = await db.scalar(select(HomeCalendarHighlightSettings).where(HomeCalendarHighlightSettings.group_id == home_id))
    sources = (await db.scalars(select(PlatformHolidaySource).where(PlatformHolidaySource.enabled.is_(True)).order_by(PlatformHolidaySource.country_name, PlatformHolidaySource.region_name))).all()
    subscriptions = (await db.scalars(select(HomeHolidaySubscription).where(HomeHolidaySubscription.group_id == home_id).order_by(HomeHolidaySubscription.created_at))).all()
    source_map = {source.id: source for source in sources}
    all_source_rows = (await db.scalars(select(PlatformHolidaySource).where(PlatformHolidaySource.id.in_([row.source_id for row in subscriptions])))).all() if subscriptions else []
    source_map.update({source.id: source for source in all_source_rows})
    return CalendarHighlightsSettingsResponse(
        birthdays_enabled=settings.birthdays_enabled if settings else False,
        available_sources=[await _source_response(db, source) for source in sources],
        subscriptions=[HomeHolidaySubscriptionResponse(id=row.id, source=await _source_response(db, source_map[row.source_id]), enabled=row.enabled) for row in subscriptions if row.source_id in source_map],
    )


@router.put("/{home_id}/calendar-highlights", response_model=CalendarHighlightsSettingsResponse)
async def update_calendar_highlights_settings(
    home_id: uuid.UUID,
    body: HomeCalendarHighlightsUpdate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> CalendarHighlightsSettingsResponse:
    await require_capability(home_id, Capability.calendar_edit_all, auth, db)
    row = await db.scalar(select(HomeCalendarHighlightSettings).where(HomeCalendarHighlightSettings.group_id == home_id).with_for_update())
    if row is None:
        row = HomeCalendarHighlightSettings(group_id=home_id, birthdays_enabled=body.birthdays_enabled)
        db.add(row)
    else:
        row.birthdays_enabled = body.birthdays_enabled
    audit(db, request, "calendar.highlights.birthdays_updated", auth.user.id, home_id, "home", home_id)
    await db.commit()
    return await get_calendar_highlights_settings(home_id, auth, db)


@router.post("/{home_id}/calendar-highlights/holiday-calendars", response_model=HomeHolidaySubscriptionResponse, status_code=201)
async def add_holiday_calendar(
    home_id: uuid.UUID,
    body: HomeHolidaySubscriptionCreate,
    request: Request,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> HomeHolidaySubscriptionResponse:
    await require_capability(home_id, Capability.calendar_edit_all, auth, db)
    source = await db.scalar(select(PlatformHolidaySource).where(PlatformHolidaySource.id == body.source_id, PlatformHolidaySource.enabled.is_(True)))
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That holiday calendar is not available.")
    row = await db.scalar(select(HomeHolidaySubscription).where(HomeHolidaySubscription.group_id == home_id, HomeHolidaySubscription.source_id == source.id).with_for_update())
    if row is None:
        row = HomeHolidaySubscription(group_id=home_id, source_id=source.id, enabled=True)
        db.add(row)
    else:
        row.enabled = True
    audit(db, request, "calendar.highlights.holiday_added", auth.user.id, home_id, "holiday_source", source.id)
    await db.commit()
    await db.refresh(row)
    return HomeHolidaySubscriptionResponse(id=row.id, source=await _source_response(db, source), enabled=row.enabled)


@router.patch("/{home_id}/calendar-highlights/holiday-calendars/{subscription_id}", response_model=HomeHolidaySubscriptionResponse)
async def update_holiday_calendar(
    home_id: uuid.UUID, subscription_id: uuid.UUID, body: HomeHolidaySubscriptionUpdate, request: Request,
    auth: AuthContext = Depends(auth_context), db: AsyncSession = Depends(get_db),
) -> HomeHolidaySubscriptionResponse:
    await require_capability(home_id, Capability.calendar_edit_all, auth, db)
    row = await db.scalar(select(HomeHolidaySubscription).where(HomeHolidaySubscription.id == subscription_id, HomeHolidaySubscription.group_id == home_id).with_for_update())
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That holiday subscription could not be found.")
    row.enabled = body.enabled
    source = await db.get(PlatformHolidaySource, row.source_id)
    audit(db, request, "calendar.highlights.holiday_toggled", auth.user.id, home_id, "holiday_source", row.source_id)
    await db.commit()
    assert source is not None
    return HomeHolidaySubscriptionResponse(id=row.id, source=await _source_response(db, source), enabled=row.enabled)


@router.delete("/{home_id}/calendar-highlights/holiday-calendars/{subscription_id}", status_code=204)
async def remove_holiday_calendar(
    home_id: uuid.UUID, subscription_id: uuid.UUID, request: Request,
    auth: AuthContext = Depends(auth_context), db: AsyncSession = Depends(get_db),
) -> None:
    await require_capability(home_id, Capability.calendar_edit_all, auth, db)
    row = await db.scalar(select(HomeHolidaySubscription).where(HomeHolidaySubscription.id == subscription_id, HomeHolidaySubscription.group_id == home_id).with_for_update())
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That holiday subscription could not be found.")
    source_id = row.source_id
    await db.delete(row)
    audit(db, request, "calendar.highlights.holiday_removed", auth.user.id, home_id, "holiday_source", source_id)
    await db.commit()


@router.get("/{home_id}/calendar-highlights/dates", response_model=CalendarHighlightsResponse)
async def list_calendar_highlight_dates(
    home_id: uuid.UUID,
    start_date: date = Query(...),
    end_date: date = Query(...),
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> CalendarHighlightsResponse:
    await require_capability(home_id, Capability.calendar_view, auth, db)
    if end_date < start_date or (end_date - start_date).days > 370:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Highlight range must be 0 to 370 days.")
    settings = await db.scalar(select(HomeCalendarHighlightSettings).where(HomeCalendarHighlightSettings.group_id == home_id))
    items: list[CalendarHighlightsBirthday | CalendarHighlightsHoliday] = []
    subscriptions = (await db.scalars(select(HomeHolidaySubscription).where(HomeHolidaySubscription.group_id == home_id, HomeHolidaySubscription.enabled.is_(True)))).all()
    source_ids = [row.source_id for row in subscriptions]
    if source_ids:
        holidays = (await db.execute(select(PlatformHolidayDate, PlatformHolidaySource).join(PlatformHolidaySource, PlatformHolidaySource.id == PlatformHolidayDate.source_id).where(PlatformHolidayDate.source_id.in_(source_ids), PlatformHolidayDate.holiday_date >= start_date, PlatformHolidayDate.holiday_date <= end_date))).all()
        items.extend(CalendarHighlightsHoliday(kind="holiday", date=row.holiday_date, label=row.name, country_code=source.country_code, flag_emoji=source.flag_emoji, source_id=source.id) for row, source in holidays)
    if settings and settings.birthdays_enabled:
        memberships = (await db.scalars(select(Membership).where(Membership.group_id == home_id, Membership.removed_at.is_(None)))).all()
        for membership in memberships:
            user = await db.get(User, membership.user_id)
            profile = await db.scalar(select(ChildProfile).where(ChildProfile.membership_id == membership.id))
            if profile is not None:
                if not profile.birthday_visible or profile.birth_month is None or profile.birth_day is None:
                    continue
                month, day, name = profile.birth_month, profile.birth_day, user.display_name if user else ""
            elif user and user.birth_month is not None and user.birth_day is not None:
                month, day, name = user.birth_month, user.birth_day, user.display_name
            else:
                continue
            current = start_date.year
            while current <= end_date.year:
                try:
                    birthday = date(current, month, day)
                except ValueError:
                    birthday = date(current, 2, 28)
                if start_date <= birthday <= end_date:
                    items.append(CalendarHighlightsBirthday(kind="birthday", date=birthday, label=f"{name}'s birthday", names=[name]))
                current += 1
    return CalendarHighlightsResponse(items=items)
