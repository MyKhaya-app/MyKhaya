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

from mykhaya.models import NotificationChannel, NotificationTemplate
from mykhaya.notifications.default_templates import TEMPLATES, TemplateDefault

log = structlog.get_logger()

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


class UnknownTemplateVariable(ValueError):
    pass


def substitute(text: str, variables: dict[str, str], allowed: frozenset[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in allowed:
            raise UnknownTemplateVariable(key)
        return str(variables[key])

    return _PLACEHOLDER.sub(replace, text)


def validate_override_text(text: str, allowed: frozenset[str]) -> None:
    """Raises UnknownTemplateVariable if `text` references a placeholder outside the
    allowlist — used to reject a bad save before it ever reaches a real send."""
    for match in _PLACEHOLDER.finditer(text):
        if match.group(1) not in allowed:
            raise UnknownTemplateVariable(match.group(1))


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
    db: AsyncSession, template_type: str, variables: dict[str, str]
) -> tuple[str, str]:
    """Renders a template's (subject, body): the admin's override if one exists,
    enabled, and renders cleanly, otherwise the trusted built-in default."""
    default: TemplateDefault = TEMPLATES[template_type]
    override = await get_override(db, template_type)

    if override is not None and override.enabled:
        try:
            subject = substitute(
                override.subject or default.subject, variables, default.allowed_variables
            )
            body = substitute(
                override.body_text or default.body, variables, default.allowed_variables
            )
            return subject, body
        except UnknownTemplateVariable as exc:
            await log.awarning(
                "notification_template_render_fallback",
                template_type=template_type,
                unknown_variable=str(exc),
            )

    subject = substitute(default.subject, variables, default.allowed_variables)
    body = substitute(default.body, variables, default.allowed_variables)
    return subject, body
