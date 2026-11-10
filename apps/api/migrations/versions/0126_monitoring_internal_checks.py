"""Monitoring: MyKhaya's own web/API/auth checks now run over the internal
Docker network instead of public hostnames.

Their stored history measured a different (public) route, which a
NetBird-protected deployment deliberately does not allow from inside, so it
is reset to Unknown: the next internal check establishes the real state with
no false recovery alert. They are also no longer "awaiting live validation",
so they become public-reporting checks again, unless an administrator has
explicitly configured them (updated_by_administrator_id set), in which case
that choice is kept. Data only; no schema change.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0126_monitoring_internal_checks"
down_revision: str | None = "0125_service_monitoring"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEYS = "('web.http', 'api.ready', 'auth.endpoint')"


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE monitor_components
        SET state = 'unknown',
            consecutive_failures = 0,
            consecutive_successes = 0,
            confidence = NULL,
            last_checked_at = NULL,
            last_failure_category = NULL,
            last_failure_detail = NULL,
            state_changed_at = NULL,
            public_visible = CASE
                WHEN updated_by_administrator_id IS NULL THEN true
                ELSE public_visible
            END
        WHERE key IN {_KEYS}
        """
    )


def downgrade() -> None:
    # Nothing to restore: the reset history described a route no longer used.
    pass
