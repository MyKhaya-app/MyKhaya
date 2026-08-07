"""Regression tests for the outbox retry/backoff fix.

Before this fix, mykhaya.scheduler marked OutboxEvent.processed_at the
moment a job was dequeued into Redis — before it was actually processed —
so a failed job could never be selected again: it was permanently silently
lost. See docs/design/visual-identity.md context and the fix itself in
mykhaya/worker.py and mykhaya/scheduler.py.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from mykhaya.db import SessionFactory
from mykhaya.models import OutboxEvent, WorkerJobRecord
from mykhaya.worker import MAX_ATTEMPTS, _backoff_seconds, process


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
