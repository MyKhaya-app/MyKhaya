"""Human-readable labels for notification_type/channel/status values — shared by the
Platform Admin Communications Timeline and Diagnostics pages so "what happened" reads
as a short story ("Morning briefing · Delivered") rather than raw enum values.
"""

from __future__ import annotations

NOTIFICATION_TYPE_LABELS: dict[str, str] = {
    "email_verification": "Email verification",
    "password_reset": "Password reset",
    "household_invitation": "Household invitation",
    "calendar_share_invitation": "Calendar share invitation",
    "calendar_share_accepted": "Calendar share accepted",
    "calendar_share_declined": "Calendar share declined",
    "calendar_share_revoked": "Calendar share revoked",
    "event_reminder": "Calendar reminder",
    "event_invitation": "Event invitation",
    "event_updated": "Event updated",
    "event_cancelled": "Event cancelled",
    "household_routine_reminder": "Routine reminder",
    "birthday_reminder": "Birthday reminder",
    "daily_briefing": "Morning briefing",
    "test_push": "Test push",
}


def notification_type_label(notification_type: str) -> str:
    return NOTIFICATION_TYPE_LABELS.get(
        notification_type, notification_type.replace("_", " ").capitalize()
    )


def channel_label(channel: str) -> str:
    return {"email": "Email", "push": "Push", "in_app": "In-app"}.get(channel, channel.title())


def friendly_status(status: str, channel: str, retry_pending: bool) -> str:
    if status == "sent":
        return "Delivered"
    if status == "failed":
        base = f"{channel_label(channel)} failed"
        return f"{base} · Retry scheduled" if retry_pending else base
    if status == "cancelled":
        return "Cancelled"
    return "Queued"
