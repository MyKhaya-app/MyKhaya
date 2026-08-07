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

DEFAULT_TEMPLATE_VERSION = 1


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
            "Open this secure link:\n\n{{link}}\n\n"
            "If you did not request this, you can ignore it."
        ),
        allowed_variables=frozenset({"link"}),
        description="Sent when someone registers or an administrator resends verification.",
    ),
    "password_reset": TemplateDefault(
        subject="Reset your MyKhaya password",
        body=(
            "Open this secure link:\n\n{{link}}\n\n"
            "If you did not request this, you can ignore it."
        ),
        allowed_variables=frozenset({"link"}),
        description="Sent when someone requests a password reset.",
    ),
    "household_invitation": TemplateDefault(
        subject="You are invited to a MyKhaya Home",
        body=(
            "{{inviter_display_name}} invited you to join {{home_name}}.\n\n"
            "Use this secure link to accept the invitation:\n\n"
            "{{link}}\n\n"
            "This invitation expires on {{expires_at}}.\n\n"
            "If you were not expecting this invitation, you can ignore this email."
        ),
        allowed_variables=frozenset(
            {"inviter_display_name", "home_name", "link", "expires_at"}
        ),
        description="Sent when a household admin or partner invites someone to join.",
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
}
