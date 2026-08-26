"""Override-only template rendering: a DB row in `notification_templates` customises a
built-in default from `default_templates.py`, never replaces or duplicates it. See
docs/architecture/notification-engine.md.

Rendering is plain `{{variable}}` substitution against a closed, per-template-type
allowlist — no `str.format`, no Jinja, no `eval`. A broken override (references a
variable outside the allowlist) never blocks a send: it's logged and the trusted
built-in default is used instead.
"""

from __future__ import annotations

import re

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mykhaya.config import Settings
from mykhaya.email_branding import render_email_html
from mykhaya.models import NotificationChannel, NotificationTemplate
from mykhaya.notifications.default_templates import TEMPLATES, TemplateDefault

log = structlog.get_logger()

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


class UnknownTemplateVariable(ValueError):
    pass


class MissingRequiredTemplateVariable(ValueError):
    """Raised when subject+body between them drop a placeholder the template
    declares as required (TemplateDefault.required_variables) — e.g. a
    security template's {{link}}. Carries every missing variable, not just
    the first, so a single save attempt/log entry can report all of them."""

    def __init__(self, missing: frozenset[str]) -> None:
        self.missing = sorted(missing)
        super().__init__(f"missing required variable(s): {', '.join(self.missing)}")


def substitute(text: str, variables: dict[str, str], allowed: frozenset[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in allowed:
            raise UnknownTemplateVariable(key)
        return str(variables[key])

    return _PLACEHOLDER.sub(replace, text)


def used_variables(text: str) -> set[str]:
    return {match.group(1) for match in _PLACEHOLDER.finditer(text)}


def validate_override_text(text: str, allowed: frozenset[str]) -> None:
    """Raises UnknownTemplateVariable if `text` references a placeholder outside the
    allowlist — used to reject a bad save before it ever reaches a real send."""
    for match in _PLACEHOLDER.finditer(text):
        if match.group(1) not in allowed:
            raise UnknownTemplateVariable(match.group(1))


def validate_required_variables(subject: str, body: str, required: frozenset[str]) -> None:
    """Raises MissingRequiredTemplateVariable if any of `required` is present in
    neither `subject` nor `body` — e.g. an admin's edited wording for
    `password_reset` no longer contains {{link}} anywhere. Checked across both
    fields combined rather than per-field: no current template pins a
    required variable to one specific field, so the smaller, combined check
    is sufficient and avoids inventing per-field required-variable sets that
    nothing yet needs."""
    present = used_variables(subject) | used_variables(body)
    missing = required - present
    if missing:
        raise MissingRequiredTemplateVariable(frozenset(missing))


async def get_override(
    db: AsyncSession, template_type: str, channel: NotificationChannel = NotificationChannel.email
) -> NotificationTemplate | None:
    result: NotificationTemplate | None = await db.scalar(
        select(NotificationTemplate).where(
            NotificationTemplate.template_type == template_type,
            NotificationTemplate.channel == channel,
        )
    )
    return result


async def render_notification(
    db: AsyncSession,
    template_type: str,
    variables: dict[str, str],
    channel: NotificationChannel | None = None,
) -> tuple[str, str]:
    """Renders a template's (subject, body): the admin's override if one exists,
    enabled, and renders cleanly, otherwise the trusted built-in default.

    `channel` selects which per-channel override row to look up — defaults to
    the template's own registered channel (`TemplateDefault.channel`), which
    for every template that existed before this parameter was added is
    `NotificationChannel.email`, so no existing call site's behaviour
    changes. A caller only needs to pass `channel` explicitly if it's
    resolving a template for a channel other than the one it's registered
    under, which no current call site does."""
    default: TemplateDefault = TEMPLATES[template_type]
    override = await get_override(db, template_type, channel or default.channel)

    if override is not None and override.enabled:
        override_subject = override.subject or default.subject
        override_body = override.body_text or default.body
        try:
            # An override saved before `default.required_variables` gained an
            # entry (or before this template existed at all in an older
            # release) can be a legacy row that would no longer pass today's
            # save-time validation. Re-checking it here — not just at save
            # time — is what keeps a stale/legacy override from silently
            # breaking a real send: it is treated exactly like any other
            # invalid override and the trusted default is used instead.
            validate_required_variables(override_subject, override_body, default.required_variables)
            subject = substitute(override_subject, variables, default.allowed_variables)
            body = substitute(override_body, variables, default.allowed_variables)
            return subject, body
        except (UnknownTemplateVariable, MissingRequiredTemplateVariable) as exc:
            await log.awarning(
                "notification_template_render_fallback",
                template_type=template_type,
                reason=str(exc),
            )

    subject = substitute(default.subject, variables, default.allowed_variables)
    body = substitute(default.body, variables, default.allowed_variables)
    return subject, body


async def render_notification_email(
    db: AsyncSession, settings: Settings, template_type: str, variables: dict[str, str]
) -> tuple[str, str, str]:
    """Like render_notification, but also returns the branded HTML companion
    (mykhaya.email_branding) for the email channel specifically — push/in-app
    keep using render_notification's plain text alone. HTML is built from the
    same resolved (override-aware) subject/body, so a customised template's
    wording is reflected in both, and user-controlled variables are
    HTML-escaped by email_branding before reaching markup."""
    subject, body = await render_notification(db, template_type, variables)
    html = render_email_html(settings, template_type, subject, body, variables.get("link"))
    return subject, body, html
