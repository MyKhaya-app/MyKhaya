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

DEFAULT_TEMPLATE_VERSION = 4


@dataclass(frozen=True)
class TemplateDefault:
    subject: str
    body: str
    allowed_variables: frozenset[str]
    description: str
    # Placeholders that MUST remain present (in the subject and/or the body —
    # combined, not per-field, since no current template needs a variable
    # pinned to one specific field) for an override to be considered valid.
    # Always a subset of allowed_variables (enforced below, at import time).
    # Empty for every template where dropping a variable makes the wording
    # merely different, not broken/misleading/unusable — see
    # docs/architecture/notification-engine.md.
    required_variables: frozenset[str] = frozenset()
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
    "mfa_email_code": TemplateDefault(
        subject="Your MyKhaya verification code",
        body=(
            "Your verification code\n\n"
            "{{code}}\n\n"
            "Use this code to finish signing in to MyKhaya.\n\n"
            "This code expires in 15 minutes.\n\n"
            "If you didn't try to sign in, you can safely ignore this email."
        ),
        allowed_variables=frozenset({"code"}),
        required_variables=frozenset({"code"}),
        description="Sent when a browser sign-in needs email MFA verification.",
        module="account_security",
        disableable=False,
        security_critical=True,
    ),
    "email_verification": TemplateDefault(
        subject="Verify your MyKhaya email",
        body=(
            "Please verify your email address to finish setting up your MyKhaya account.\n\n"
            "Open this secure link:\n\n{{link}}\n\n"
            "If you didn't create a MyKhaya account, you can safely ignore this email."
        ),
        allowed_variables=frozenset({"link"}),
        required_variables=frozenset({"link"}),
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
        required_variables=frozenset({"link"}),
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
        required_variables=frozenset({"link"}),
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
        required_variables=frozenset({"link"}),
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
        required_variables=frozenset({"link"}),
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
    # --- Standalone reminders ---------------------------------------------------
    "reminder.due": TemplateDefault(
        subject="{{reminder_title}}",
        body="Reminder: {{reminder_title}}.",
        allowed_variables=frozenset({"reminder_title"}),
        description=(
            "A standalone Reminder's due (or repeat-nag) notification — the same "
            "wording is reused for every cadence tick until the reminder is "
            "completed."
        ),
        module="reminders",
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
    # --- Nudges summaries -------------------------------------------------
    # Daily Nudge Summary — see mykhaya.notifications.nudges.
    # deliver_daily_nudge_summary(). A user-configurable *morning* digest
    # ("what do I need to do today?"), entirely distinct from Daily Briefing
    # ("what's happening today?", briefing.title/briefing.intro above) and
    # from the *evening* nudges.evening_cleanup/nudges.day_complete below.
    # Keyed to match its notification_type ("daily_nudge_summary") exactly,
    # not namespaced under "nudges.", so PCC's titleCase(template_type)
    # display reads unambiguously as "Daily Nudge Summary" rather than
    # colliding in wording with Daily Briefing — see migration
    # 0059_rename_nudges_summary_template for the key's prior name.
    # {{count_summary}} is a pre-formatted, correctly-pluralised phrase
    # (e.g. "1 routine, 2 to-dos and 0 reminders") computed in the
    # notification service — this template engine only does plain
    # {{variable}} substitution with no conditional/plural support, so
    # raw counts are never interpolated directly into prose here.
    "daily_nudge_summary": TemplateDefault(
        subject="Your Nudges today",
        body="You have {{count_summary}} today.\n\n{{item_summary}}",
        allowed_variables=frozenset(
            {
                "user_display_name",
                "routine_count",
                "todo_count",
                "reminder_count",
                "total_count",
                "count_summary",
                "item_summary",
                "delivery_date",
                "deep_link",
            }
        ),
        description=(
            "Daily Nudge Summary: a morning digest of the recipient's outstanding "
            "Routines, Reminders and assigned To-dos for today, sent at their own "
            "configured Daily Nudge Summary time. Never sent on a day with nothing "
            "outstanding."
        ),
        module="nudges",
        channel=NotificationChannel.in_app,
    ),
    "nudges.evening_cleanup": TemplateDefault(
        subject="A quick evening tidy-up",
        body="You’ve got {{outstanding_count}} things still open today.\n\n{{summary}}",
        allowed_variables=frozenset({"first_name", "outstanding_count", "routine_count", "todo_count", "overdue_count", "summary", "deep_link"}),
        description="A calm summary of relevant outstanding Nudges at the end of the day.",
        module="nudges",
        channel=NotificationChannel.in_app,
    ),
    "nudges.day_complete": TemplateDefault(
        subject="You’re all caught up 🌿",
        body="Everything you needed to deal with today is done.",
        allowed_variables=frozenset({"first_name", "completed_count", "deep_link"}),
        description="A positive acknowledgement when the user's relevant Nudges are clear.",
        module="nudges",
        channel=NotificationChannel.in_app,
    ),
    # --- Birthdays --------------------------------------------------------
    # notifications.birthdays sends exactly two wording variants — never a
    # third — regardless of whether the birthday belongs to an adult user or
    # a child: the birthday person themself (self) sees one message, every
    # other household member (other) sees a different one naming them. The
    # *external* notify() notification_type stays the single, unchanged
    # "birthday_reminder" for both — preferences, idempotency keys and
    # existing delivery-log/analytics rows keyed on that string are
    # unaffected; only these two internal template keys are new.
    "birthday.reminder.self": TemplateDefault(
        subject="Happy Birthday!",
        body="Happy Birthday! We hope you have a wonderful day.",
        allowed_variables=frozenset(),
        description="Sent to a household member on their own birthday.",
        module="birthdays",
        channel=NotificationChannel.in_app,
    ),
    "birthday.reminder.other": TemplateDefault(
        subject="{{display_name}}'s birthday",
        body="Today is {{display_name}}'s birthday.",
        allowed_variables=frozenset({"display_name"}),
        description=(
            "Sent to everyone else in the household when it's a member's or child's "
            "birthday."
        ),
        module="birthdays",
        channel=NotificationChannel.in_app,
    ),
    # --- Lists ----------------------------------------------------------------
    "list_item_assigned": TemplateDefault(
        subject="List item assigned",
        body='{{actor_display_name}} assigned "{{item_name}}" to you on {{list_name}}.',
        allowed_variables=frozenset({"actor_display_name", "item_name", "list_name"}),
        description="Sent to a household member newly assigned a shared list item.",
        module="lists",
        channel=NotificationChannel.in_app,
    ),
    # --- Wishlists --------------------------------------------------------
    # {{recipient_scope}}/{{access_scope}} are pre-formatted by MyKhaya, not
    # independently editable here — a wishlist can be shared with a single
    # named recipient ("you") or with an entire Home ("your Home"), and the
    # wording needs to read naturally either way. Both call shapes use the
    # same notification_type/template, so this is one canonical template
    # covering both contexts rather than two near-duplicate keys.
    "wishlist_share_created": TemplateDefault(
        subject="Wishlist shared with {{recipient_scope}}",
        body='{{actor_display_name}} shared "{{wishlist_name}}" with {{recipient_scope}}.',
        allowed_variables=frozenset(
            {"actor_display_name", "wishlist_name", "recipient_scope"}
        ),
        description=(
            "Sent when a wishlist is shared with a specific person or made visible to "
            "a whole Home."
        ),
        module="wishlists",
        channel=NotificationChannel.in_app,
    ),
    "wishlist_share_revoked": TemplateDefault(
        subject="Wishlist access removed",
        body='{{actor_display_name}} removed {{access_scope}} access to "{{wishlist_name}}".',
        allowed_variables=frozenset({"actor_display_name", "wishlist_name", "access_scope"}),
        description=(
            "Sent when a wishlist share is revoked, or Home-wide visibility is turned off."
        ),
        module="wishlists",
        channel=NotificationChannel.in_app,
    ),
    # --- Meal plans -------------------------------------------------------
    # Deliberately NOT fully decomposed, matching the same principle as
    # Daily Briefing's briefing.title/briefing.intro: date-relativity
    # ("today" vs. a weekday name), capitalisation and the optional cook
    # attribution line are computed by mykhaya.notifications.meal_plans, not
    # copy — {{meal_date}}/{{meal_day}}/{{meal_slot_lower}}/{{meal_time}}/
    # {{cook_line}} are pre-formatted, not independently editable here.
    # meal_plan_removed's {{removal_reason}} covers two genuinely different
    # sentence shapes under one notification_type (the whole entry was
    # deleted, vs. you personally were unassigned from a still-existing
    # entry) — kept as one pre-composed phrase rather than forcing both into
    # an artificial shared sentence structure.
    "meal_plan_created": TemplateDefault(
        subject="{{meal_slot}} planned for {{meal_date}}",
        body="{{meal_name}}{{meal_time}}{{cook_line}}",
        allowed_variables=frozenset(
            {"meal_slot", "meal_date", "meal_name", "meal_time", "cook_line"}
        ),
        description="Sent to a meal plan entry's participants and cook when it is added.",
        module="meal_plans",
        channel=NotificationChannel.in_app,
    ),
    "meal_plan_updated": TemplateDefault(
        subject="{{meal_day}}'s {{meal_slot_lower}} changed",
        body="{{meal_name}}{{meal_time}}{{cook_line}}",
        allowed_variables=frozenset(
            {"meal_day", "meal_slot_lower", "meal_name", "meal_time", "cook_line"}
        ),
        description=(
            "Sent to a meal plan entry's participants and cook when its details change."
        ),
        module="meal_plans",
        channel=NotificationChannel.in_app,
    ),
    "meal_plan_removed": TemplateDefault(
        subject="{{removal_reason}}",
        body="{{meal_name}}{{meal_time}}{{cook_line}}",
        allowed_variables=frozenset({"removal_reason", "meal_name", "meal_time", "cook_line"}),
        description=(
            "Sent when a meal plan entry is deleted, or when a participant is removed "
            "from one that still exists for others."
        ),
        module="meal_plans",
        channel=NotificationChannel.in_app,
    ),
    # --- Home join requests -------------------------------------------------
    # Best-effort, not mandatory: a Home Admin who never sees this in-app is
    # still not locked out of the flow — the request stays fully visible from
    # Members/pending-requests regardless (see routers.home_join). Ordinary
    # disableable notification, not a MANDATORY_EMAIL_TYPES-style workflow.
    "home_join_request": TemplateDefault(
        subject="New Home join request",
        body="{{requester_display_name}} wants to join {{home_name}} using your Home join code.",
        allowed_variables=frozenset({"requester_display_name", "home_name"}),
        description="Sent to a Home Admin when someone requests to join using a join code.",
        module="households",
        channel=NotificationChannel.in_app,
    ),
}

for _template_type, _default in TEMPLATES.items():
    _unknown_required = _default.required_variables - _default.allowed_variables
    if _unknown_required:
        raise AssertionError(
            f"{_template_type}: required_variables {sorted(_unknown_required)} "
            "must be a subset of allowed_variables"
        )
del _template_type, _default, _unknown_required

# Realistic placeholder values for the Platform Admin preview/test-send actions — never
# real user data, since a preview must never leak anything from an actual account.
SAMPLE_VARIABLES: dict[str, dict[str, str]] = {
    "daily_nudge_summary": {
        "user_display_name": "Jamie",
        "routine_count": "2",
        "todo_count": "3",
        "reminder_count": "1",
        "total_count": "6",
        "count_summary": "2 routines, 3 to-dos and 1 reminder",
        "item_summary": "• Take Tablet\n• Sign school trip form",
        "delivery_date": "2026-01-01",
        "deep_link": "/settings/routines-reminders",
    },
    "nudges.evening_cleanup": {"first_name": "Jamie", "outstanding_count": "2", "routine_count": "1", "todo_count": "1", "overdue_count": "1", "summary": "Overdue\n• Call plumber", "deep_link": "/settings/routines-reminders"},
    "nudges.day_complete": {"first_name": "Jamie", "completed_count": "5", "deep_link": "/settings/routines-reminders"},
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
    "reminder.due": {"reminder_title": "Call the dentist"},
    "briefing.title": {"count_phrase": "3 events"},
    "briefing.intro": {},
    "birthday.reminder.self": {},
    "birthday.reminder.other": {"display_name": "Megan"},
    "list_item_assigned": {
        "actor_display_name": "Megan",
        "item_name": "Milk",
        "list_name": "Weekly shop",
    },
    "wishlist_share_created": {
        "actor_display_name": "Megan",
        "wishlist_name": "Birthday ideas",
        "recipient_scope": "you",
    },
    "wishlist_share_revoked": {
        "actor_display_name": "Megan",
        "wishlist_name": "Birthday ideas",
        "access_scope": "your",
    },
    "meal_plan_created": {
        "meal_slot": "Dinner",
        "meal_date": "Friday",
        "meal_name": "Lasagne",
        "meal_time": " at 18:30",
        "cook_line": "\nMegan is cooking",
    },
    "meal_plan_updated": {
        "meal_day": "Friday",
        "meal_slot_lower": "dinner",
        "meal_name": "Lasagne",
        "meal_time": " at 18:30",
        "cook_line": "\nMegan is cooking",
    },
    "meal_plan_removed": {
        "removal_reason": "Friday's dinner was removed",
        "meal_name": "Lasagne",
        "meal_time": " at 18:30",
        "cook_line": "",
    },
    "home_join_request": {
        "requester_display_name": "Megan",
        "home_name": "The Example Family",
    },
}
