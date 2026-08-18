"""Regression tests for the outbox retry/backoff fix.

Before this fix, mykhaya.scheduler marked OutboxEvent.processed_at the
moment a job was dequeued into Redis — before it was actually processed —
so a failed job could never be selected again: it was permanently silently
lost. See docs/design/visual-identity.md context and the fix itself in
mykhaya/worker.py and mykhaya/scheduler.py.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from mykhaya import worker
from mykhaya.config import get_settings
from mykhaya.db import SessionFactory
from mykhaya.models import (
    NotificationChannel,
    NotificationDelivery,
    NotificationDeliveryStatus,
    OutboxEvent,
    PlatformSmtpSettings,
    SmtpConnectionSecurity,
    WorkerJobRecord,
)
from mykhaya.secrets_crypto import encrypt_secret
from mykhaya.worker import MAX_ATTEMPTS, _backoff_seconds, process


@pytest.mark.asyncio
async def test_database_rejects_duplicate_scheduler_occurrence() -> None:
    key = "synthetic-scheduler-occurrence:2026-08-13T23:59:00Z"
    async with SessionFactory() as db:
        first = OutboxEvent(topic="notification.test", payload={}, dedupe_key=key)
        db.add(first)
        await db.commit()
        try:
            db.add(OutboxEvent(topic="notification.test", payload={}, dedupe_key=key))
            with pytest.raises(IntegrityError):
                await db.commit()
        finally:
            await db.rollback()
            await db.execute(delete(OutboxEvent).where(OutboxEvent.id == first.id))
            await db.commit()


def test_backoff_grows_and_is_capped() -> None:
    assert _backoff_seconds(1) == 30
    assert _backoff_seconds(2) == 60
    assert _backoff_seconds(3) == 120
    # Must not grow forever — capped so a permanently-failing job doesn't
    # end up scheduled a year in the future.
    assert _backoff_seconds(20) == 3600


@pytest.mark.asyncio
async def test_failed_job_is_not_marked_processed_and_gets_backoff() -> None:
    async with SessionFactory() as db:
        event = OutboxEvent(
            topic="notification.email",
            payload={},  # missing required keys — forces a genuine failure to test retry
        )
        db.add(event)
        await db.commit()
        event_id = event.id

    try:
        with pytest.raises(Exception):  # noqa: B017 - re-raised by design, see worker.py
            await process(event_id)

        async with SessionFactory() as db:
            refreshed = await db.get(OutboxEvent, event_id)
            assert refreshed is not None
            # The core bug: a failed job must remain selectable for retry, not
            # be silently marked complete.
            assert refreshed.processed_at is None
            assert refreshed.attempts == 1
            assert refreshed.last_error is not None
            assert refreshed.available_at > datetime.now(UTC)

            job = await db.get(WorkerJobRecord, event_id)
            assert job is not None
            assert job.status == "failed"
    finally:
        # Deliberately left failed + unprocessed (that's the behaviour under test),
        # which also leaves a genuinely "actionable failed job" behind — clean it up
        # so it doesn't pollute anything else in the run that checks the platform
        # overview's actionable-failed-jobs count.
        async with SessionFactory() as db:
            await db.execute(
                delete(WorkerJobRecord).where(WorkerJobRecord.outbox_event_id == event_id)
            )
            await db.execute(delete(OutboxEvent).where(OutboxEvent.id == event_id))
            await db.commit()


@pytest.mark.asyncio
async def test_job_gives_up_after_max_attempts() -> None:
    async with SessionFactory() as db:
        event = OutboxEvent(
            topic="notification.email",
            payload={},  # missing required keys — forces a genuine failure to test retry
            attempts=MAX_ATTEMPTS - 1,
        )
        db.add(event)
        await db.commit()
        event_id = event.id

    with pytest.raises(Exception):  # noqa: B017 - re-raised by design, see worker.py
        await process(event_id)

    async with SessionFactory() as db:
        refreshed = await db.get(OutboxEvent, event_id)
        assert refreshed is not None
        assert refreshed.attempts == MAX_ATTEMPTS
        # Exhausted retries: processed_at is set so the row stops being
        # selected, even though the job never actually succeeded. The
        # WorkerJobRecord remains as the permanent diagnostic record.
        assert refreshed.processed_at is not None


@pytest.mark.asyncio
async def test_already_processed_event_is_not_reprocessed() -> None:
    async with SessionFactory() as db:
        event = OutboxEvent(
            topic="notification.email",
            payload={},  # missing required keys — forces a genuine failure to test retry
            processed_at=datetime.now(UTC),
        )
        db.add(event)
        await db.commit()
        event_id = event.id

    # Must return quietly, not attempt to process (and not raise) a row
    # that's already been marked processed.
    await process(event_id)

    async with SessionFactory() as db:
        job = await db.scalar(
            select(WorkerJobRecord).where(WorkerJobRecord.outbox_event_id == event_id)
        )
        assert job is None


@pytest.mark.asyncio
async def test_email_worker_uses_enabled_platform_smtp_over_local_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings().model_copy(
        update={
            "environment": "development",
            "email_delivery_configured": True,
            "smtp_host": "mailpit",
        }
    )
    event = OutboxEvent(
        topic="notification.email",
        payload={
            "recipient_email": "recipient@example.com",
            "subject": "Verify your MyKhaya email",
            "body": "Please verify your email.",
            "html_body": None,
            "delivery_idempotency_key": "worker-pcc-smtp-test:email",
        },
    )
    smtp = PlatformSmtpSettings(
        enabled=True,
        host="smtp2go.example",
        port=587,
        connection_security=SmtpConnectionSecurity.starttls,
        auth_enabled=True,
        username="smtp-user",
        encrypted_password=encrypt_secret(settings, "smtp-password"),
        sender_name="MyKhaya",
        sender_email="hello@example.com",
        timeout_seconds=10,
    )
    async with SessionFactory() as db:
        db.add_all([event, smtp])
        await db.flush()
        delivery = NotificationDelivery(
            channel=NotificationChannel.email,
            notification_type="email_verification",
            idempotency_key="worker-pcc-smtp-test:email",
            outbox_event_id=event.id,
            status=NotificationDeliveryStatus.queued,
        )
        db.add(delivery)
        await db.commit()
        event_id = event.id
        smtp_id = smtp.id

    calls: list[tuple[object, str, str, str]] = []

    def fake_send(
        config: object, recipient: str, subject: str, body: str, html: str | None
    ) -> None:
        calls.append((config, recipient, subject, body))

    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "send_email", fake_send)
    try:
        await worker.process(event_id)
        assert len(calls) == 1
        config, recipient, subject, body = calls[0]
        assert config.source == "platform_admin"
        assert config.host == "smtp2go.example"
        assert config.password == "smtp-password"
        assert recipient == "recipient@example.com"
        assert subject == "Verify your MyKhaya email"
        assert body == "Please verify your email."
        async with SessionFactory() as db:
            stored_delivery = await db.scalar(
                select(NotificationDelivery).where(
                    NotificationDelivery.idempotency_key == "worker-pcc-smtp-test:email"
                )
            )
            assert stored_delivery is not None
            assert stored_delivery.status == NotificationDeliveryStatus.sent
    finally:
        async with SessionFactory() as db:
            await db.execute(delete(WorkerJobRecord).where(WorkerJobRecord.id == event_id))
            await db.execute(
                delete(NotificationDelivery).where(NotificationDelivery.outbox_event_id == event_id)
            )
            await db.execute(delete(OutboxEvent).where(OutboxEvent.id == event_id))
            await db.execute(delete(PlatformSmtpSettings).where(PlatformSmtpSettings.id == smtp_id))
            await db.commit()
