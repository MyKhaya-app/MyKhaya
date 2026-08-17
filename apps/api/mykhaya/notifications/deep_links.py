"""A small, closed registry mapping a logical notification target to an actual app path.

Every notification (push payload, in-app row, email action link) stores a structured
target dict, never a raw URL — a template controls wording only, never where a tap or
click actually goes. This is a logical identifier resolved to a normal `https://` route,
not a registered custom URL scheme: a scheme like `mykhaya://` isn't usable from a web
push payload or an installed iOS Safari PWA.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal, TypedDict

DeepLinkType = Literal[
    "calendar_event",
    "calendar_today",
    "member",
    "routine",
    "notifications",
    "settings",
    "home",
]


class DeepLinkTarget(TypedDict, total=False):
    type: DeepLinkType
    id: str


def target(kind: DeepLinkType, entity_id: uuid.UUID | str | None = None) -> DeepLinkTarget:
    value: DeepLinkTarget = {"type": kind}
    if entity_id is not None:
        value["id"] = str(entity_id)
    return value


def resolve_path(link: dict[str, Any] | None) -> str:
    """Resolve a stored deep-link target to the app path a client should navigate to.

    Falls back to /home for anything unrecognised or missing — never a dead link, and
    never a bare "open the app" for a target that could have been made specific.
    """
    if not link:
        return "/home"
    kind = link.get("type")
    entity_id = link.get("id")
    if kind == "calendar_event" and entity_id:
        return f"/calendar?event={entity_id}"
    if kind == "calendar_today":
        return "/calendar"
    if kind == "routine" and entity_id:
        return f"/home?routine={entity_id}"
    if kind == "member" and entity_id:
        return "/people"
    if kind == "notifications":
        return "/home?notifications=1"
    if kind == "settings":
        return "/settings/notifications"
    return "/home"
