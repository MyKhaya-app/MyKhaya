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

DEFAULT_TEMPLATE_VERSION = 2


@dataclass(frozen=True)
class TemplateDefault:
    subject: str
    body: str
    allowed_variables: frozenset[str]
    description: str


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
    ),
    "calendar_share_accepted": TemplateDefault(
        subject="{{recipient_display_name}} accepted your calendar share",
        body=(
            "{{recipient_display_name}} accepted your invitation to share the "
            '"{{calendar_name}}" calendar.'
        ),
        allowed_variables=frozenset({"recipient_display_name", "calendar_name"}),
        description="Sent to the sharer when an external calendar-share invitation is accepted.",
    ),
    "calendar_share_declined": TemplateDefault(
        subject="{{recipient_display_name}} declined your calendar share",
        body=(
            "{{recipient_display_name}} declined your invitation to share the "
            '"{{calendar_name}}" calendar.'
        ),
        allowed_variables=frozenset({"recipient_display_name", "calendar_name"}),
        description="Sent to the sharer when an external calendar-share invitation is declined.",
    ),
    "calendar_share_revoked": TemplateDefault(
        subject='Your access to "{{calendar_name}}" has been removed',
        body=(
            '{{home_name}} has removed your access to the "{{calendar_name}}" calendar. '
            "You will no longer see its events or receive notifications for it."
        ),
        allowed_variables=frozenset({"home_name", "calendar_name"}),
        description="Sent to the recipient when a Home revokes an external calendar share.",
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
}
