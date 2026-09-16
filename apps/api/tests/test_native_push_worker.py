"""Worker-level coverage for native push provider dispatch (Phase 5): proves
device.platform alone decides APNs vs FCM, that each provider's permanent-error
handling disables the device with a provider-specific reason exactly like the
pre-existing APNs-only behaviour, that an unsupported platform fails safely
without raising, and that an FCM failure never falls back to APNs (or vice
versa) for the same delivery.
"""

import uuid

import pytest
from sqlalchemy import select

from mykhaya import worker as worker_module
from mykhaya.db import SessionFactory
from mykhaya.models import (
    NativePushDevice,
    NotificationDelivery,
    NotificationDeliveryStatus,
    OutboxEvent,
    User,
)
from mykhaya.notifications.push import ApnsConfig, ApnsPermanentError, FcmConfig, FcmPermanentError
from mykhaya.worker import process


def unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


async def _setup_native_delivery(platform: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Creates a user, a NativePushDevice, an outbox event, and the matching
    NotificationDelivery row a real notify()/enqueue_native_push() call would
    have produced — returns (event_id, device_id, user_id)."""
    async with SessionFactory() as db:
        user = User(email=unique_email(f"native-{platform}"), display_name="Native Device Owner")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        device = NativePushDevice(
            user_id=user.id,
            platform=platform,
            token=f"{platform}-token-{uuid.uuid4().hex}",
            installation_id=f"installation-{uuid.uuid4().hex}",
            apns_environment="production" if platform == "ios" else None,
        )
        db.add(device)
        await db.commit()
        await db.refresh(device)
        key = f"native-worker-{platform}:{uuid.uuid4()}"
        event = OutboxEvent(
            topic="notification.native_push",
            payload={
                "native_push_device_id": str(device.id),
                "title": "T",
                "body": "B",
                "deep_link": None,
                "delivery_idempotency_key": key,
                "notification_type": "test",
                "recipient_user_id": str(user.id),
            },
        )
        db.add(event)
        await db.commit()
        db.add(
            NotificationDelivery(
                channel="push",
                recipient_user_id=user.id,
                notification_type="test",
                idempotency_key=key,
                outbox_event_id=event.id,
                native_push_device_id=device.id,
            )
        )
        await db.commit()
        return event.id, device.id, user.id


def _configured_apns_config(_settings: object) -> ApnsConfig:
    return ApnsConfig(configured=True, team_id="T", key_id="K", bundle_id="app", private_key="k")


def _configured_fcm_config(_settings: object) -> FcmConfig:
    return FcmConfig(configured=True, project_id="p", client_email="e", private_key="k")


@pytest.mark.asyncio
async def test_worker_dispatches_ios_device_to_apns_and_not_fcm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_id, device_id, _user_id = await _setup_native_delivery("ios")
    apns_calls = []
    fcm_calls = []
    monkeypatch.setattr(worker_module, "resolve_apns_config", _configured_apns_config)
    monkeypatch.setattr(worker_module, "resolve_fcm_config", _configured_fcm_config)
    monkeypatch.setattr(
        worker_module, "send_apns", lambda *a, **k: apns_calls.append((a, k))
    )
    monkeypatch.setattr(worker_module, "send_fcm", lambda *a, **k: fcm_calls.append((a, k)))

    await process(event_id)

    assert len(apns_calls) == 1
    assert fcm_calls == []
    async with SessionFactory() as db:
        device = await db.get(NativePushDevice, device_id)
        assert device is not None
        assert device.disabled_at is None


@pytest.mark.asyncio
async def test_worker_dispatches_android_device_to_fcm_and_not_apns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_id, device_id, _user_id = await _setup_native_delivery("android")
    apns_calls = []
    fcm_calls = []
    monkeypatch.setattr(worker_module, "resolve_apns_config", _configured_apns_config)
    monkeypatch.setattr(worker_module, "resolve_fcm_config", _configured_fcm_config)
    monkeypatch.setattr(
        worker_module, "send_apns", lambda *a, **k: apns_calls.append((a, k))
    )
    monkeypatch.setattr(worker_module, "send_fcm", lambda *a, **k: fcm_calls.append((a, k)))

    await process(event_id)

    assert len(fcm_calls) == 1
    assert apns_calls == []
    async with SessionFactory() as db:
        device = await db.get(NativePushDevice, device_id)
        assert device is not None
        assert device.disabled_at is None
        delivery = await db.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.native_push_device_id == device_id
            )
        )
        assert delivery is not None
        assert delivery.status == NotificationDeliveryStatus.sent


@pytest.mark.asyncio
async def test_worker_disables_android_device_on_fcm_permanent_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_id, device_id, _user_id = await _setup_native_delivery("android")

    def fail(*_a: object, **_k: object) -> None:
        raise FcmPermanentError("FCM rejected this device registration")

    monkeypatch.setattr(worker_module, "resolve_fcm_config", _configured_fcm_config)
    monkeypatch.setattr(worker_module, "send_fcm", fail)

    await process(event_id)

    async with SessionFactory() as db:
        device = await db.get(NativePushDevice, device_id)
        assert device is not None
        assert device.disabled_at is not None
        assert device.disabled_reason == "FCM rejected this device registration."
        delivery = await db.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.native_push_device_id == device_id
            )
        )
        assert delivery is not None
        assert delivery.status == NotificationDeliveryStatus.cancelled
        event = await db.get(OutboxEvent, event_id)
        assert event is not None
        assert event.processed_at is not None


@pytest.mark.asyncio
async def test_worker_disables_ios_device_on_apns_permanent_error_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard: the pre-existing APNs disable path must behave
    identically after the platform-dispatch refactor."""
    event_id, device_id, _user_id = await _setup_native_delivery("ios")

    def fail(*_a: object, **_k: object) -> None:
        raise ApnsPermanentError("APNs rejected this device registration")

    monkeypatch.setattr(worker_module, "resolve_apns_config", _configured_apns_config)
    monkeypatch.setattr(worker_module, "send_apns", fail)

    await process(event_id)

    async with SessionFactory() as db:
        device = await db.get(NativePushDevice, device_id)
        assert device is not None
        assert device.disabled_at is not None
        assert device.disabled_reason == "APNs rejected this device registration."


@pytest.mark.asyncio
async def test_fcm_failure_never_falls_back_to_apns(monkeypatch: pytest.MonkeyPatch) -> None:
    event_id, _device_id, _user_id = await _setup_native_delivery("android")
    apns_calls = []

    def fail(*_a: object, **_k: object) -> None:
        raise RuntimeError("FCM delivery is not configured")

    monkeypatch.setattr(worker_module, "resolve_fcm_config", _configured_fcm_config)
    monkeypatch.setattr(worker_module, "send_fcm", fail)
    monkeypatch.setattr(
        worker_module, "send_apns", lambda *a, **k: apns_calls.append((a, k))
    )

    await process(event_id)

    assert apns_calls == []


@pytest.mark.asyncio
async def test_worker_handles_unsupported_platform_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    event_id, device_id, _user_id = await _setup_native_delivery("ios")
    async with SessionFactory() as db:
        device = await db.get(NativePushDevice, device_id)
        assert device is not None
        device.platform = "windows"
        await db.commit()

    warnings: list[tuple[str, dict[str, object]]] = []

    async def fake_awarning(event: str, **kwargs: object) -> None:
        warnings.append((event, kwargs))

    monkeypatch.setattr(worker_module.log, "awarning", fake_awarning)

    await process(event_id)

    async with SessionFactory() as db:
        delivery = await db.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.native_push_device_id == device_id
            )
        )
        assert delivery is not None
        assert delivery.status == NotificationDeliveryStatus.cancelled
        event = await db.get(OutboxEvent, event_id)
        assert event is not None
        assert event.processed_at is not None
    assert warnings == [
        ("native_push_unsupported_platform", {"platform": "windows", "device_id": str(device_id)})
    ]
