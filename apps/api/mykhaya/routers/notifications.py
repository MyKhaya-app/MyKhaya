import uuid
from datetime import UTC, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings, get_settings
from mykhaya.db import get_db
from mykhaya.dependencies import AuthContext, auth_context
from mykhaya.models import (
    BriefingDays,
    LockScreenPreviewLevel,
    NativePushDevice,
    Notification,
    PushSubscription,
)
from mykhaya.notifications.deep_links import resolve_path
from mykhaya.notifications.engine import get_or_create_preferences
from mykhaya.notifications.push import resolve_push_config
from mykhaya.schemas import (
    NativePushDeviceCreate,
    NativePushDeviceResponse,
    NotificationListResponse,
    NotificationPreferencesResponse,
    NotificationPreferencesUpdate,
    NotificationResponse,
    PushPublicKeyResponse,
    PushSubscriptionCreate,
    PushSubscriptionResponse,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])

PAGE_SIZE = 30


def native_device_response(row: NativePushDevice) -> NativePushDeviceResponse:
    return NativePushDeviceResponse(
        id=row.id,
        platform=row.platform,
        device_label=row.device_label,
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
        disabled_at=row.disabled_at,
    )


@router.post("/native-devices", status_code=status.HTTP_201_CREATED)
async def register_native_device(
    body: NativePushDeviceCreate,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> NativePushDeviceResponse:
    row = await db.scalar(
        select(NativePushDevice).where(
            NativePushDevice.platform == body.platform,
            NativePushDevice.installation_id == body.installation_id,
        )
    )
    now = datetime.now(UTC)
    if row is None:
        row = NativePushDevice(
            user_id=auth.user.id,
            platform=body.platform,
            token=body.token,
            installation_id=body.installation_id,
            device_label=body.device_label,
            last_seen_at=now,
        )
        db.add(row)
    else:
        row.user_id = auth.user.id
        row.token = body.token
        row.device_label = body.device_label
        row.last_seen_at = now
        row.disabled_at = None
        row.disabled_reason = None
    await db.commit()
    await db.refresh(row)
    return native_device_response(row)


@router.delete("/native-devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_native_device(
    device_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await db.scalar(
        select(NativePushDevice).where(
            NativePushDevice.id == device_id,
            NativePushDevice.user_id == auth.user.id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Native device not found.")
    row.disabled_at = datetime.now(UTC)
    row.disabled_reason = "Removed by account owner."
    await db.commit()


def _time_str(value: time | None) -> str | None:
    return value.isoformat(timespec="minutes") if value else None


@router.get("/preferences")
async def get_preferences(
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> NotificationPreferencesResponse:
    prefs = await get_or_create_preferences(db, auth.user.id)
    await db.commit()
    return NotificationPreferencesResponse(
        push_enabled=prefs.push_enabled,
        in_app_enabled=prefs.in_app_enabled,
        email_enabled=prefs.email_enabled,
        event_reminders_enabled=prefs.event_reminders_enabled,
        event_invitations_enabled=prefs.event_invitations_enabled,
        event_changes_enabled=prefs.event_changes_enabled,
        household_reminders_enabled=prefs.household_reminders_enabled,
        list_assignments_enabled=prefs.list_assignments_enabled,
        wishlist_sharing_enabled=prefs.wishlist_sharing_enabled,
        daily_briefing_enabled=prefs.daily_briefing_enabled,
        briefing_time=_time_str(prefs.briefing_time) or "07:30",
        briefing_days=prefs.briefing_days.value,
        empty_day_briefing_enabled=prefs.empty_day_briefing_enabled,
        lock_screen_preview_level=prefs.lock_screen_preview_level.value,
        quiet_hours_start=_time_str(prefs.quiet_hours_start),
        quiet_hours_end=_time_str(prefs.quiet_hours_end),
        quiet_hours_critical_only=prefs.quiet_hours_critical_only,
    )


@router.put("/preferences")
async def update_preferences(
    body: NotificationPreferencesUpdate,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> NotificationPreferencesResponse:
    prefs = await get_or_create_preferences(db, auth.user.id)
    prefs.push_enabled = body.push_enabled
    prefs.in_app_enabled = body.in_app_enabled
    prefs.email_enabled = body.email_enabled
    prefs.event_reminders_enabled = body.event_reminders_enabled
    prefs.event_invitations_enabled = body.event_invitations_enabled
    prefs.event_changes_enabled = body.event_changes_enabled
    prefs.household_reminders_enabled = body.household_reminders_enabled
    prefs.list_assignments_enabled = body.list_assignments_enabled
    prefs.wishlist_sharing_enabled = body.wishlist_sharing_enabled
    prefs.daily_briefing_enabled = body.daily_briefing_enabled
    prefs.briefing_time = time.fromisoformat(body.briefing_time)
    prefs.briefing_days = BriefingDays(body.briefing_days)
    prefs.empty_day_briefing_enabled = body.empty_day_briefing_enabled
    prefs.lock_screen_preview_level = LockScreenPreviewLevel(body.lock_screen_preview_level)
    prefs.quiet_hours_start = (
        time.fromisoformat(body.quiet_hours_start) if body.quiet_hours_start else None
    )
    prefs.quiet_hours_end = (
        time.fromisoformat(body.quiet_hours_end) if body.quiet_hours_end else None
    )
    prefs.quiet_hours_critical_only = body.quiet_hours_critical_only
    await db.commit()
    return await get_preferences(auth=auth, db=db)


@router.get("")
async def list_notifications(
    page: int = Query(default=1, ge=1, le=1000),
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> NotificationListResponse:
    offset = (page - 1) * PAGE_SIZE
    rows = (
        await db.scalars(
            select(Notification)
            .where(Notification.recipient_user_id == auth.user.id)
            .order_by(Notification.created_at.desc())
            .offset(offset)
            .limit(PAGE_SIZE + 1)
        )
    ).all()
    has_more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    unread_count = (
        await db.scalar(
            select(func.count(Notification.id)).where(
                Notification.recipient_user_id == auth.user.id,
                Notification.read_at.is_(None),
            )
        )
        or 0
    )
    return NotificationListResponse(
        items=[
            NotificationResponse(
                id=row.id,
                notification_type=row.notification_type,
                title=row.title,
                body=row.body,
                related_entity_type=row.related_entity_type,
                related_entity_id=row.related_entity_id,
                deep_link_path=resolve_path(row.deep_link),
                read_at=row.read_at,
                created_at=row.created_at,
            )
            for row in rows
        ],
        unread_count=unread_count,
        next_page=page + 1 if has_more else None,
    )


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    notification = await db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.recipient_user_id == auth.user.id,
        )
    )
    if notification is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found.")
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        await db.commit()
    return {"message": "Marked as read."}


@router.post("/read-all")
async def mark_all_notifications_read(
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    await db.execute(
        update(Notification)
        .where(
            Notification.recipient_user_id == auth.user.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=func.now())
    )
    await db.commit()
    return {"message": "All notifications marked as read."}


@router.get("/push/public-key")
async def push_public_key(
    _: AuthContext = Depends(auth_context),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> PushPublicKeyResponse:
    config = await resolve_push_config(settings, db)
    return PushPublicKeyResponse(configured=config.configured, public_key=config.public_key)


@router.get("/push-subscriptions")
async def list_push_subscriptions(
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[PushSubscriptionResponse]:
    rows = (
        await db.scalars(
            select(PushSubscription)
            .where(PushSubscription.user_id == auth.user.id)
            .order_by(PushSubscription.created_at.desc())
        )
    ).all()
    return [
        PushSubscriptionResponse(
            id=row.id,
            device_label=row.device_label,
            user_agent=row.user_agent,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            disabled_at=row.disabled_at,
        )
        for row in rows
    ]


@router.post("/push-subscriptions", status_code=status.HTTP_201_CREATED)
async def register_push_subscription(
    body: PushSubscriptionCreate,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> PushSubscriptionResponse:
    existing = await db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    )
    if existing is not None:
        # Re-subscribing (e.g. the browser rotated the endpoint) always re-associates to
        # the current signed-in user — a subscription only ever belongs to whoever most
        # recently registered it from that browser.
        existing.user_id = auth.user.id
        existing.p256dh_key = body.keys.p256dh
        existing.auth_key = body.keys.auth
        existing.device_label = body.device_label
        existing.user_agent = body.user_agent
        existing.disabled_at = None
        existing.disabled_reason = None
        existing.last_seen_at = datetime.now(UTC)
        row = existing
    else:
        row = PushSubscription(
            user_id=auth.user.id,
            endpoint=body.endpoint,
            p256dh_key=body.keys.p256dh,
            auth_key=body.keys.auth,
            device_label=body.device_label,
            user_agent=body.user_agent,
            last_seen_at=datetime.now(UTC),
        )
        db.add(row)
    await db.commit()
    await db.refresh(row)
    return PushSubscriptionResponse(
        id=row.id,
        device_label=row.device_label,
        user_agent=row.user_agent,
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
        disabled_at=row.disabled_at,
    )


@router.delete("/push-subscriptions/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_push_subscription(
    subscription_id: uuid.UUID,
    auth: AuthContext = Depends(auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await db.scalar(
        select(PushSubscription).where(
            PushSubscription.id == subscription_id,
            PushSubscription.user_id == auth.user.id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Push subscription not found.")
    await db.delete(row)
    await db.commit()
