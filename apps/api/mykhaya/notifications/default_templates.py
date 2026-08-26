"""Trusted built-in copy for notification templates, versioned with the app rather than
the database. This is the "code default" the override-only Platform Admin template
system (mykhaya/notifications/templates.py) falls back to and validates against — see
docs/architecture/notification-engine.md.

Templates are plain text with `{{variable}}` placeholders — no HTML, no Jinja, no
`str.format`/`eval`. Each template declares its own closed set of allowed variables;
`templates.py` rejects (and falls back to the default for) any override that references
a variable outside that set.

Bump DEFAULT_TEMPLATE_VERSION whenever any template's subject/body copy changes, so a
Platform Admin with a saved override can eventually be shown "the built-in wording has
changed since you customised this" (NotificationTemplate.based_on_default_version).
"""

from __future__ import annotations

from dataclasses import dataclass

from mykhaya.models import NotificationChannel

DEFAULT_TEMPLATE_VERSION = 2


@dataclass(frozen=True)
class TemplateDefault:
    subject: str
    body: str
    allowed_variables: frozenset[str]
    description: str
    # --- Registry metadata (PCC Notifications module) -----------------------
    # None of the fields below are ever persisted to NotificationTemplate —
    # they describe the *definition* (module grouping, which channel an
    # override applies to, whether disabling is even safe), which is exactly
    # the kind of thing that must stay code-defined so a newly deployed
    # notification type shows up in PCC automatically, with no DB seed step.
    # See docs/architecture/notification-engine.md.
    module: str = "other"
    # The channel a PCC override for this template_type applies to.
    # NotificationTemplate already has a (template_type, channel) unique
    # constraint — every entry here has always implicitly meant "email" (the
    # only channel any template touched before this module), so that stays
    # the default and every pre-existing entry is unaffected.
    channel: NotificationChannel = NotificationChannel.email
    # False for account-security/mandatory-communication templates that must
    # never be silently turned off from PCC — enforced server-side in
    # routers.platform.update_notification_template, not just hidden in the
    # UI. Mirrors mykhaya.notifications.engine.MANDATORY_EMAIL_TYPES for the
    # existing email templates; extended to the new non-email ones below.
    disableable: bool = True
    security_critical: bool = False


TEMPLATES: dict[str, TemplateDefault] = {
    "email_verification": TemplateDefault(
        subject="Verify your MyKhaya email",
        body=(
            "Please verify your email address to finish setting up your MyKhaya account.\n\n"
            "Open this secure link:\n\n{{link}}\n\n"
            "If you didn't create a MyKhaya account, you can safely ignore this email."
        ),
        allowed_variables=frozenset({"link"}),
        description="Sent when someone registers or an administrator resends verification.",
        module="account_security",
        disableable=False,
        security_critical=True,
    ),
    "password_reset": TemplateDefault(
        subject="Reset your MyKhaya password",
        body=(
            "Somebody requested a password reset for your MyKhaya account.\n\n"
            "Open this secure link:\n\n{{link}}\n\n"
            "If you didn't request a password reset, you can safely ignore this email — "
            "your password has not been changed."
        ),
        allowed_variables=frozenset({"link"}),
        description="Sent when someone requests a password reset.",
        module="account_security",
        disableable=False,
        security_critical=True,
    ),
    "household_invitation": TemplateDefault(
        subject="You're invited to join a MyKhaya Home",
        body=(
            "{{inviter_display_name}} invited you to join {{home_name}}.\n\n"
            "Use this secure link to accept the invitation:\n\n"
            "{{link}}\n\n"
            "This invitation expires on {{expires_at}}.\n\n"
            "If you were not expecting this invitation, you can ignore this email."
        ),
        allowed_variables=frozenset({"inviter_display_name", "home_name", "link", "expires_at"}),
        description="Sent when a household admin or partner invites someone to join.",
        module="invitations",
        disableable=False,
        security_critical=True,
    ),
    "calendar_share_invitation": TemplateDefault(
        subject="{{home_name}} wants to share a calendar with you",
        body=(
            "{{inviter_display_name}} from {{home_name}} wants to share the "
            '"{{calendar_name}}" calendar with you on MyKhaya ({{permission}}).\n\n'
            "Use this secure link to view the invitation and accept or decline:\n\n"
            "{{link}}\n\n"
            "This invitation expires on {{expires_at}}. You don't need MyKhaya Family "
            "to accept — a free account is enough.\n\n"
            "If you were not expecting this invitation, you can ignore this email."
        ),
        allowed_variables=frozenset(
            {
                "inviter_display_name",
                "home_name",
                "calendar_name",
                "permission",
                "link",
                "expires_at",
            }
        ),
        description="Sent when a Home shares one of its calendars with someone outside the Home.",
        module="calendar_sharing",
        disableable=False,
        security_critical=True,
    ),
    "calendar_share_accepted": TemplateDefault(
        subject="{{recipient_display_name}} accepted your calendar share",
        body=(
            "{{recipient_display_name}} accepted your invitation to share the "
            '"{{calendar_name}}" calendar.'
        ),
        allowed_variables=frozenset({"recipient_display_name", "calendar_name"}),
        description="Sent to the sharer when an external calendar-share invitation is accepted.",
        module="calendar_sharing",
    ),
    "calendar_share_declined": TemplateDefault(
        subject="{{recipient_display_name}} declined your calendar share",
        body=(
            "{{recipient_display_name}} declined your invitation to share the "
            '"{{calendar_name}}" calendar.'
        ),
        allowed_variables=frozenset({"recipient_display_name", "calendar_name"}),
        description="Sent to the sharer when an external calendar-share invitation is declined.",
        module="calendar_sharing",
    ),
    "calendar_share_revoked": TemplateDefault(
        subject='Your access to "{{calendar_name}}" has been removed',
        body=(
            '{{home_name}} has removed your access to the "{{calendar_name}}" calendar. '
            "You will no longer see its events or receive notifications for it."
        ),
        allowed_variables=frozenset({"home_name", "calendar_name"}),
        description="Sent to the recipient when a Home revokes an external calendar share.",
        module="calendar_sharing",
    ),
    "platform_administrator_invitation": TemplateDefault(
        subject="You are invited to administer MyKhaya",
        body=(
            "{{inviter_display_name}} has invited you to become a Platform Administrator "
            "for this MyKhaya installation, with the role of {{role}}.\n\n"
            "This is not an invitation to a Home — it gives privileged access to manage "
            "the entire MyKhaya platform, not a single household.\n\n"
            "Use this secure link to set up your administrator account:\n\n"
            "{{link}}\n\n"
            "This invitation expires on {{expires_at}}.\n\n"
            "If you were not expecting this invitation, you can ignore this email — no "
            "account will be created unless the link above is used."
        ),
        allowed_variables=frozenset({"inviter_display_name", "role", "link", "expires_at"}),
        description="Sent when a Platform Owner invites a new global platform administrator.",
        module="platform",
        disableable=False,
        security_critical=True,
    ),
    # --- Calendar (in-app / push) --------------------------------------------
    # These four cover routers.calendar's per-event-member notifications
    # (Home-side) and notifications.calendar_shares' equivalent for external
    # calendar-share recipients — "updated"/"cancelled" wording is identical
    # between the two call sites, so they share one template each; the
    # "created" wording for a share recipient differs from the Home-side
    # "member added" wording (see calendar.event.shared_created below), so
    # that one stays separate. All four use channel=in_app: these
    # notifications are sent with one shared title/body across whichever of
    # in-app/push a recipient has enabled (see notifications.engine.notify),
    # so a single stored override channel covers both by design.
    "calendar.event.member_added": TemplateDefault(
        subject="Added to an event",
        body="{{actor_name}} added you to {{event_title}}. {{event_when}}.",
        allowed_variables=frozenset({"actor_name", "event_title", "event_when"}),
        description="Sent to a household member newly assigned to a Home calendar event.",
        module="calendar",
        channel=NotificationChannel.in_app,
    ),
    "calendar.event.member_removed": TemplateDefault(
        subject="Removed from an event",
        body="{{actor_name}} removed you from {{event_title}}.",
        allowed_variables=frozenset({"actor_name", "event_title"}),
        description="Sent to a household member removed from a Home calendar event.",
        module="calendar",
        channel=NotificationChannel.in_app,
    ),
    "calendar.event.updated": TemplateDefault(
        subject="Event updated",
        body="{{actor_name}} updated {{event_title}}. {{event_when}}.",
        allowed_variables=frozenset({"actor_name", "event_title", "event_when"}),
        description=(
            "Sent when a calendar event's details change — to assigned Home members and to "
            "external calendar-share recipients alike."
        ),
        module="calendar",
        channel=NotificationChannel.in_app,
    ),
    "calendar.event.cancelled": TemplateDefault(
        subject="Event cancelled",
        body="{{actor_name}} cancelled {{event_title}}.",
        allowed_variables=frozenset({"actor_name", "event_title"}),
        description=(
            "Sent when a calendar event is deleted — to assigned Home members and to "
            "external calendar-share recipients alike."
        ),
        module="calendar",
        channel=NotificationChannel.in_app,
    ),
    "calendar.event.shared_created": TemplateDefault(
        subject="New event",
        body="{{actor_name}} added {{event_title}}. {{event_when}}.",
        allowed_variables=frozenset({"actor_name", "event_title", "event_when"}),
        description="Sent to an external calendar-share recipient when a new event is added.",
        module="calendar",
        channel=NotificationChannel.in_app,
    ),
    "calendar.event.reminder": TemplateDefault(
        subject="{{event_title}}",
        body="{{event_title}} starts {{event_when}}{{event_location}}.",
        allowed_variables=frozenset({"event_title", "event_when", "event_location"}),
        description="Sent ahead of a calendar event, per its own reminder setting.",
        module="calendar",
        channel=NotificationChannel.in_app,
    ),
    # --- Household routines ---------------------------------------------------
    "routine.due": TemplateDefault(
        subject="{{routine_title}}",
        body="Don't forget: {{routine_title}}.",
        allowed_variables=frozenset({"routine_title"}),
        description=(
            "Fallback wording for a household routine reminder that has no custom "
            "description of its own (a routine with a description uses that verbatim "
            "instead — this template is never shown alongside one)."
        ),
        module="routines",
        channel=NotificationChannel.in_app,
    ),
    # --- Daily briefing (wording fragments only — see briefing.py) -----------
    # Deliberately NOT templated: which events/meals/birthdays appear, their
    # ordering, the empty-day rotation, and the "+N more" overflow line —
    # those are computed, not copy, and stay in mykhaya.notifications.briefing
    # exactly as today. Only the two fixed, non-computed lines are exposed.
    "briefing.title": TemplateDefault(
        subject="You have {{count_phrase}} today.",
        body="You have {{count_phrase}} today.",
        allowed_variables=frozenset({"count_phrase"}),
        description=(
            "The daily briefing's heading. {{count_phrase}} is a pre-formatted phrase "
            'such as "3 events" or "1 event" — the count and pluralisation are computed '
            "by MyKhaya, not editable here."
        ),
        module="daily_briefing",
        channel=NotificationChannel.in_app,
    ),
    "briefing.intro": TemplateDefault(
        subject="Please take care of yourself!",
        body="Please take care of yourself!",
        allowed_variables=frozenset(),
        description="The daily briefing's fixed introduction line, shown above the day's items.",
        module="daily_briefing",
        channel=NotificationChannel.in_app,
    ),
}

# Realistic placeholder values for the Platform Admin preview/test-send actions — never
# real user data, since a preview must never leak anything from an actual account.
SAMPLE_VARIABLES: dict[str, dict[str, str]] = {
    "email_verification": {"link": "https://example.com/verify-email?token=SAMPLE-TOKEN"},
    "password_reset": {"link": "https://example.com/reset-password?token=SAMPLE-TOKEN"},
    "household_invitation": {
        "inviter_display_name": "Jamie Example",
        "home_name": "The Example Family",
        "link": "https://example.com/register?invitation=SAMPLE-TOKEN",
        "expires_at": "2026-12-31",
    },
    "platform_administrator_invitation": {
        "inviter_display_name": "Jamie Example",
        "role": "Platform Administrator",
        "link": "https://admin.example.com/accept-invitation?token=SAMPLE-TOKEN",
        "expires_at": "2026-12-31",
    },
    "calendar_share_invitation": {
        "inviter_display_name": "Jamie Example",
        "home_name": "The Example Family",
        "calendar_name": "School",
        "permission": "Can view",
        "link": "https://example.com/calendar-shares/accept?token=SAMPLE-TOKEN",
        "expires_at": "2026-12-31",
    },
    "calendar_share_accepted": {
        "recipient_display_name": "Margaret Example",
        "calendar_name": "School",
    },
    "calendar_share_declined": {
        "recipient_display_name": "Margaret Example",
        "calendar_name": "School",
    },
    "calendar_share_revoked": {
        "home_name": "The Example Family",
        "calendar_name": "School",
    },
    "calendar.event.member_added": {
        "actor_name": "Megan",
        "event_title": "School Trip",
        "event_when": "Friday, 28 August at 09:00",
    },
    "calendar.event.member_removed": {
        "actor_name": "Megan",
        "event_title": "School Trip",
    },
    "calendar.event.updated": {
        "actor_name": "Megan",
        "event_title": "School Trip",
        "event_when": "Friday, 28 August at 09:00",
    },
    "calendar.event.cancelled": {
        "actor_name": "Megan",
        "event_title": "School Trip",
    },
    "calendar.event.shared_created": {
        "actor_name": "Megan",
        "event_title": "School Trip",
        "event_when": "Friday, 28 August at 09:00",
    },
    "calendar.event.reminder": {
        "event_title": "School Trip",
        "event_when": "at 09:00",
        "event_location": " at Riverside School",
    },
    "routine.due": {"routine_title": "Put the bins out"},
    "briefing.title": {"count_phrase": "3 events"},
    "briefing.intro": {},
}
