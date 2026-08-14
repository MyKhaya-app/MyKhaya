"""Backfill scheduler occurrence keys for legacy notification outbox rows.

The original idempotency migration added the unique column, but legacy reminder,
routine, and birthday rows had NULL keys. A later scan could therefore create a
new keyed row for an occurrence that had already been processed. Historical rows
are retained; only their keys are normalized so the canonical occurrence remains
unique without deleting audit history.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025_scheduler_occurrence_backfill"
down_revision: str | None = "0024_routine_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_outbox_events_dedupe_key", "outbox_events", type_="unique")
    op.execute(
        """
        WITH candidates AS (
            SELECT id,
                   CASE topic
                       WHEN 'notification.daily_briefing' THEN
                           'daily-briefing:' || (payload->>'user_id') || ':' || (payload->>'date')
                       WHEN 'notification.household_routine' THEN
                           'routine:' || (payload->>'routine_id') || ':' ||
                           (payload->>'occurrence_date') || ':' || (payload->>'timing')
                       WHEN 'notification.event_reminder' THEN
                           'reminder:' || (payload->>'event_id') || ':' ||
                           (payload->>'occurrence_start') || ':' || (payload->>'reminder_minutes')
                       WHEN 'notification.birthday' THEN
                           'birthday:' || (payload->>'owner_type') || ':' ||
                           (payload->>'owner_id') || ':' || (payload->>'year')
                       ELSE NULL
                   END AS occurrence_key
            FROM outbox_events
            WHERE dedupe_key IS NULL
        ), ranked AS (
            SELECT id, occurrence_key,
                   row_number() OVER (
                       PARTITION BY occurrence_key ORDER BY id ASC
                   ) AS occurrence_rank
            FROM candidates
            WHERE occurrence_key IS NOT NULL
        )
        UPDATE outbox_events AS event
        SET dedupe_key = CASE
            WHEN ranked.occurrence_rank = 1 THEN ranked.occurrence_key
            ELSE ranked.occurrence_key || ':legacy:' || event.id::text
        END
        FROM ranked
        WHERE event.id = ranked.id
        """
    )
    op.create_unique_constraint(
        "uq_outbox_events_dedupe_key", "outbox_events", ["dedupe_key"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_outbox_events_dedupe_key", "outbox_events", type_="unique")
    op.create_unique_constraint(
        "uq_outbox_events_dedupe_key", "outbox_events", ["dedupe_key"]
    )
