"""Vehicle Report email: template registration, the strict recipient rule and
the attachment lifecycle, exercised through notify() and the real worker.

No email leaves the process: the worker's send_email is replaced with a
recorder. Report email stays disabled at the router (vehicle_report_email_enabled);
these tests cover the delivery path that will be used once it is approved."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from test_driveway_reminders import (
    ORIGIN,
    create_driveway_home,
    create_verified_user,
    unique_email,
)

from mykhaya import worker
from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.legal_evidence_storage import get_legal_evidence_storage
from mykhaya.mailer import EmailPermanentError, SmtpConfig
from mykhaya.main import app
from mykhaya.models import (
    Notification,
    NotificationDelivery,
    NotificationDeliveryStatus,
    NotificationPreferences,
    OutboxEvent,
    User,
    WorkerJobRecord,
)
from mykhaya.notifications.default_templates import SAMPLE_VARIABLES, TEMPLATES
from mykhaya.notifications.engine import REQUESTED_EMAIL_TYPES, notify
from mykhaya.notifications.templates import substitute
from mykhaya.vehicle_report_storage import get_vehicle_report_storage

PDF = b"%PDF-1.7 synthetic vehicle report"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as value:
        yield value


@pytest.fixture(autouse=True)
def isolated_report_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(get_settings(), "legal_evidence_storage_dir", str(tmp_path / "legal"))


class SendRecorder:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.error = error

    def __call__(self, *args: Any) -> str:
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return "synthetic-message-id"


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    async def configured(*_: Any) -> SmtpConfig:
        return SmtpConfig(source="environment", configured=True, host="smtp.invalid")

    monkeypatch.setattr(worker, "resolve_smtp_config", configured)


def test_report_template_is_registered_renders_and_can_be_switched_off() -> None:
    template = TEMPLATES["driveway_vehicle_report"]
    sample = SAMPLE_VARIABLES["driveway_vehicle_report"]
    assert template.module == "driveway" and template.disableable is True
    assert template.allowed_variables <= set(sample)
    subject = substitute(template.subject, sample, template.allowed_variables)
    body = substitute(template.body, sample, template.allowed_variables)
    assert subject == "Your MyKhaya Vehicle Report for MK21 HYA"
    assert "Full Vehicle Report for Peugeot e-208" in body
    for banned in ("buyer", "sale report"):
        assert banned not in (subject + body).lower()


async def _queue_report_email(
    client: AsyncClient, *, storage_kind: str = "vehicle_report"
) -> tuple[uuid.UUID, str, str, str]:
    """Queue exactly what the router queues; returns (event id, delivery key,
    storage key, the recipient's verified address)."""
    email = unique_email("dw-report-delivery")
    user_id = await create_verified_user(client, email, "Report Owner")
    home_id = await create_driveway_home(client, "Report Delivery Home")
    key = f"vehicle-report-{uuid.uuid4()}.pdf"
    if storage_kind == "vehicle_report":
        await get_vehicle_report_storage(get_settings()).save(key, PDF)
    else:
        await get_legal_evidence_storage(get_settings()).save_once(key, PDF)
    idempotency_key = f"driveway-vehicle-report:{user_id}:{home_id}:lookup:full:{uuid.uuid4()}"
    async with SessionFactory() as db:
        # Routine email stays OFF (the default, and explicitly so here): a
        # report the user asked for is still delivered (REQUESTED_EMAIL_TYPES).
        prefs = await db.scalar(
            select(NotificationPreferences).where(NotificationPreferences.user_id == user_id)
        )
        if prefs is None:
            db.add(NotificationPreferences(user_id=user_id, email_enabled=False))
        else:
            prefs.email_enabled = False
        await db.commit()
        await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="driveway_vehicle_report",
            title="Your MyKhaya Vehicle Report for MK21 HYA",
            body="Synthetic body",
            idempotency_key=idempotency_key,
            group_id=home_id,
            related_entity_type="lookup",
            attachment_storage_key=key,
            attachment_filename="MyKhaya-Vehicle-Report-MK21-HYA-2026-11-18.pdf",
            attachment_storage_kind=storage_kind,
            attachment_cleanup=True,
        )
        await db.commit()
        delivery_key = f"{idempotency_key}:email"
        events = (
            await db.scalars(select(OutboxEvent).where(OutboxEvent.topic == "notification.email"))
        ).all()
        event = next(e for e in events if e.payload.get("delivery_idempotency_key") == delivery_key)
        user = await db.get(User, user_id)
        assert user is not None and user.email
    return event.id, delivery_key, key, user.email


async def _cleanup(event_id: uuid.UUID) -> None:
    async with SessionFactory() as db:
        await db.execute(delete(WorkerJobRecord).where(WorkerJobRecord.outbox_event_id == event_id))
        await db.execute(delete(OutboxEvent).where(OutboxEvent.id == event_id))
        await db.commit()


async def _delivery_status(delivery_key: str) -> NotificationDeliveryStatus:
    async with SessionFactory() as db:
        delivery = await db.scalar(
            select(NotificationDelivery).where(NotificationDelivery.idempotency_key == delivery_key)
        )
    assert delivery is not None
    return delivery.status


async def test_report_goes_only_to_the_verified_account_email_and_is_then_deleted(
    client: AsyncClient, smtp: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    sender = SendRecorder()
    monkeypatch.setattr(worker, "send_email", sender)
    event_id, delivery_key, key, verified_email = await _queue_report_email(client)
    try:
        await worker.process(event_id)
        assert len(sender.calls) == 1
        _config, recipient, _subject, _body, _html, attachment = sender.calls[0]
        assert recipient == verified_email
        assert attachment == (
            "MyKhaya-Vehicle-Report-MK21-HYA-2026-11-18.pdf",
            PDF,
            "application/pdf",
        )
        assert await _delivery_status(delivery_key) == NotificationDeliveryStatus.sent
        assert await get_vehicle_report_storage(get_settings()).load(key) is None
    finally:
        await _cleanup(event_id)


async def test_report_attachment_is_deleted_after_a_permanent_failure(
    client: AsyncClient, smtp: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker, "send_email", SendRecorder(EmailPermanentError("rejected")))
    event_id, delivery_key, key, _ = await _queue_report_email(client)
    try:
        await worker.process(event_id)
        assert await _delivery_status(delivery_key) == NotificationDeliveryStatus.cancelled
        assert await get_vehicle_report_storage(get_settings()).load(key) is None
    finally:
        await _cleanup(event_id)


async def test_cleanup_never_deletes_retained_legal_evidence(
    client: AsyncClient, smtp: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker, "send_email", SendRecorder())
    event_id, _, key, _ = await _queue_report_email(client, storage_kind="legal_evidence")
    try:
        await worker.process(event_id)
        assert await get_legal_evidence_storage(get_settings()).load(key) == PDF
    finally:
        await _cleanup(event_id)


async def test_requested_report_is_email_only_despite_routine_email_being_off(
    client: AsyncClient,
) -> None:
    assert "driveway_vehicle_report" in REQUESTED_EMAIL_TYPES
    event_id, delivery_key, _, verified_email = await _queue_report_email(client)
    try:
        async with SessionFactory() as db:
            event = await db.get(OutboxEvent, event_id)
            assert event is not None and event.payload["recipient_email"] == verified_email
            prefs = await db.scalar(
                select(NotificationPreferences).where(
                    NotificationPreferences.user_id == uuid.UUID(event.payload["recipient_user_id"])
                )
            )
            assert prefs is not None and prefs.email_enabled is False
            # No in-app or push copy of a message the user explicitly requested.
            in_app = await db.scalar(
                select(Notification.id).where(
                    Notification.recipient_user_id == prefs.user_id,
                    Notification.notification_type == "driveway_vehicle_report",
                )
            )
            assert in_app is None
            push = (
                await db.scalars(
                    select(OutboxEvent).where(OutboxEvent.topic == "notification.push")
                )
            ).all()
            assert not [e for e in push if e.payload.get("recipient_user_id") == str(prefs.user_id)]
        assert await _delivery_status(delivery_key) == NotificationDeliveryStatus.queued
    finally:
        await _cleanup(event_id)


async def test_requested_report_is_never_sent_to_an_unverified_or_supplied_address(
    client: AsyncClient,
) -> None:
    email = unique_email("dw-report-unverified")
    user_id = await create_verified_user(client, email, "Report Owner")
    home_id = await create_driveway_home(client, "Report Unverified Home")
    async with SessionFactory() as db:
        user = await db.get(User, user_id)
        assert user is not None
        user.email_verified_at = None
        await db.commit()
        key = f"driveway-vehicle-report:{user_id}:{home_id}:lookup:full:{uuid.uuid4()}"
        await notify(
            db,
            settings=get_settings(),
            recipient_user_id=user_id,
            notification_type="driveway_vehicle_report",
            title="Vehicle Report",
            body="Synthetic body",
            idempotency_key=key,
            group_id=home_id,
        )
        await db.commit()
        delivery = await db.scalar(
            select(NotificationDelivery.id).where(
                NotificationDelivery.idempotency_key == f"{key}:email"
            )
        )
        assert delivery is None  # the router turns this into a clear 409
        with pytest.raises(ValueError):
            await notify(
                db,
                settings=get_settings(),
                recipient_user_id=user_id,
                recipient_email="someone-else@example.test",
                notification_type="driveway_vehicle_report",
                title="Vehicle Report",
                body="Synthetic body",
                idempotency_key=f"{key}:supplied",
                group_id=home_id,
            )
