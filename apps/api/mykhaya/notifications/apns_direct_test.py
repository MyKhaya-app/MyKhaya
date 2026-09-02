"""Temporary console-only direct APNs delivery diagnostic.

This module performs one read-only device lookup and one direct production APNs
request. It is intentionally not part of the notification worker or HTTP API.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections.abc import Sequence

import httpx
from sqlalchemy import select

from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.models import NativePushDevice
from mykhaya.notifications.push import (
    _build_apns_bearer,
    apns_failure_diagnostics,
    resolve_apns_config,
)

APNS_DIRECT_PAYLOAD = {
    "aps": {
        "alert": {
            "title": "MyKhaya APNs Test",
            "body": "Direct APNs connectivity test",
        },
        "sound": "default",
    }
}


async def _find_device(user_id: uuid.UUID | None) -> NativePushDevice | None:
    statement = select(NativePushDevice).where(
        NativePushDevice.platform == "ios",
        NativePushDevice.disabled_at.is_(None),
    )
    if user_id is not None:
        statement = statement.where(NativePushDevice.user_id == user_id)
    statement = statement.order_by(
        NativePushDevice.last_seen_at.desc().nullslast(),
        NativePushDevice.created_at.desc(),
    ).limit(1)
    async with SessionFactory() as db:
        return await db.scalar(statement)


def _send_apns_request(device: NativePushDevice, bearer: str, topic: str) -> httpx.Response:
    with httpx.Client(http2=True, timeout=10) as client:
        return client.post(
            f"https://api.push.apple.com/3/device/{device.token}",
            headers={
                "authorization": f"bearer {bearer}",
                "apns-topic": topic,
                "apns-push-type": "alert",
                "apns-priority": "10",
            },
            json=APNS_DIRECT_PAYLOAD,
        )


async def _run(
    user_id: uuid.UUID | None, supplied_jwt: str | None = None
) -> tuple[int, str, str, bool]:
    settings = get_settings()
    config = resolve_apns_config(settings)
    if not config.configured:
        return 0, "configuration_unavailable", "unknown", False

    device = await _find_device(user_id)
    if device is None:
        return 0, "no_active_ios_device", "unknown", False

    topic = config.bundle_id or "app.mykhaya.mobile"
    bearer = supplied_jwt
    if bearer is None:
        bearer = _build_apns_bearer(config, topic=topic, emit_diagnostics=False)
    try:
        response = await asyncio.to_thread(_send_apns_request, device, bearer, topic)
    except Exception:
        return 0, "request_failed", "unknown", False

    details = apns_failure_diagnostics(response)
    return (
        int(details["status"]),
        str(details["reason"]),
        str(details["request_id"]),
        200 <= int(details["status"]) < 300,
    )


def _parse_user_id(value: str | None) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise SystemExit("user-id must be a UUID") from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Temporary direct APNs test.")
    parser.add_argument("--user-id", help="Only use an active iOS registration for this user UUID.")
    parser.add_argument(
        "--jwt-stdin",
        action="store_true",
        help="Read one provider JWT from stdin instead of generating one.",
    )
    args = parser.parse_args(argv)
    supplied_jwt = sys.stdin.read().strip() if args.jwt_stdin else None
    if args.jwt_stdin and not supplied_jwt:
        print("status=0")
        print("reason=missing_jwt")
        print("request_id=unknown")
        print("success=false")
        return 1
    try:
        status, reason, request_id, success = asyncio.run(
            _run(_parse_user_id(args.user_id), supplied_jwt)
        )
    except Exception:
        status, reason, request_id, success = 0, "diagnostic_failed", "unknown", False
    print(f"status={status}")
    print(f"reason={reason}")
    print(f"request_id={request_id}")
    print(f"success={str(success).lower()}")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
