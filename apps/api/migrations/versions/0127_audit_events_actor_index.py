"""Index audit_events by actor for the PCC user Authentication tab.

The tab reads a user's recent authentication events with
``WHERE actor_user_id = :user AND action IN (...) ORDER BY created_at DESC
LIMIT 10``. audit_events previously had only (group_id, created_at), so that
read scanned the whole table. (actor_user_id, created_at) serves the filter
and the ordering directly; the short action list is checked while walking
that user's newest rows, so it is not indexed. Rows without an actor (system
and administrator-initiated events) are never queried this way and are left
out of the index.

audit_events is written by most authenticated requests, so the index is
built CONCURRENTLY (outside the migration transaction) rather than holding a
write-blocking lock while it builds.

An interrupted concurrent build leaves an INVALID index behind, which
``IF NOT EXISTS`` alone would silently keep. The upgrade therefore drops an
invalid leftover first, so re-running it after an interruption always ends
with a valid index.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0127_audit_events_actor_index"
down_revision: str | None = "0126_monitoring_internal_checks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_audit_actor_created"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        valid = op.get_bind().scalar(
            sa.text(
                "SELECT i.indisvalid FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE c.relname = :name AND c.relnamespace = 'public'::regnamespace"
            ),
            {"name": INDEX},
        )
        if valid is False:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX} "
            "ON audit_events (actor_user_id, created_at) "
            "WHERE actor_user_id IS NOT NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}")
