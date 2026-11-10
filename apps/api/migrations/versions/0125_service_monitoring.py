"""Automated service monitoring: components, observations, transitions,
overrides and administrator alerts; automated-incident support on the
existing public incident tables.

Additive only. Existing incidents keep their author and become
source="manual"; created_by becomes nullable solely so monitoring can open
and update incidents without impersonating an administrator.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0125_service_monitoring"
down_revision: str | None = "0124_legal_evidence_provider_msg"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "public_incidents",
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
    )
    op.add_column("public_incidents", sa.Column("monitor_service_key", sa.String(60)))
    op.create_index(
        "ix_public_incidents_monitor_service_key", "public_incidents", ["monitor_service_key"]
    )
    op.alter_column("public_incidents", "created_by", existing_type=sa.Uuid(), nullable=True)
    op.alter_column("status_incident_updates", "created_by", existing_type=sa.Uuid(), nullable=True)

    op.create_table(
        "monitor_components",
        sa.Column("key", sa.String(60), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("failure_threshold", sa.Integer(), nullable=False),
        sa.Column("recovery_threshold", sa.Integer(), nullable=False),
        sa.Column("public_visible", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("confidence", sa.String(20)),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_successes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column("last_latency_ms", sa.Integer()),
        sa.Column("last_failure_category", sa.String(40)),
        sa.Column("last_failure_detail", sa.String(300)),
        sa.Column("state_changed_at", sa.DateTime(timezone=True)),
        sa.Column("simulate_failure_until", sa.DateTime(timezone=True)),
        sa.Column("simulate_failure_severity", sa.String(20)),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_by_administrator_id",
            sa.Uuid(),
            sa.ForeignKey("platform_administrators.id", ondelete="SET NULL"),
        ),
    )
    op.create_table(
        "monitor_observations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "component_key",
            sa.String(60),
            sa.ForeignKey("monitor_components.key", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("failure_severity", sa.String(20)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("failure_category", sa.String(40)),
        sa.Column("detail", sa.String(300)),
        sa.Column("trigger", sa.String(20), nullable=False, server_default="scheduled"),
    )
    op.create_index(
        "ix_monitor_observations_component",
        "monitor_observations",
        ["component_key", "observed_at"],
    )
    op.create_index("ix_monitor_observations_observed_at", "monitor_observations", ["observed_at"])
    op.create_table(
        "monitor_transitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "component_key",
            sa.String(60),
            sa.ForeignKey("monitor_components.key", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("from_state", sa.String(20), nullable=False),
        sa.Column("to_state", sa.String(20), nullable=False),
        sa.Column("consecutive_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_category", sa.String(40)),
        sa.Column("detail", sa.String(300)),
        sa.Column(
            "incident_id",
            sa.Uuid(),
            sa.ForeignKey("public_incidents.id", ondelete="SET NULL"),
        ),
    )
    op.create_index(
        "ix_monitor_transitions_component",
        "monitor_transitions",
        ["component_key", "occurred_at"],
    )
    op.create_index("ix_monitor_transitions_occurred_at", "monitor_transitions", ["occurred_at"])
    op.create_table(
        "monitor_overrides",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("service_key", sa.String(60), nullable=False),
        sa.Column("forced_state", sa.String(30)),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("platform_administrators.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "revoked_by",
            sa.Uuid(),
            sa.ForeignKey("platform_administrators.id", ondelete="SET NULL"),
        ),
    )
    op.create_index("ix_monitor_overrides_service_key", "monitor_overrides", ["service_key"])
    op.create_table(
        "monitor_alerts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column(
            "component_key",
            sa.String(60),
            sa.ForeignKey("monitor_components.key", ondelete="SET NULL"),
        ),
        sa.Column(
            "transition_id",
            sa.Uuid(),
            sa.ForeignKey("monitor_transitions.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "incident_id",
            sa.Uuid(),
            sa.ForeignKey("public_incidents.id", ondelete="SET NULL"),
        ),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("summary", sa.String(1000), nullable=False),
        sa.Column("suppressed_reason", sa.String(100)),
        sa.Column("recipient_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column(
            "acknowledged_by",
            sa.Uuid(),
            sa.ForeignKey("platform_administrators.id", ondelete="SET NULL"),
        ),
        sa.UniqueConstraint("dedupe_key", name="uq_monitor_alerts_dedupe_key"),
    )
    op.create_index("ix_monitor_alerts_component_key", "monitor_alerts", ["component_key"])


def downgrade() -> None:
    op.drop_index("ix_monitor_alerts_component_key", table_name="monitor_alerts")
    op.drop_table("monitor_alerts")
    op.drop_index("ix_monitor_overrides_service_key", table_name="monitor_overrides")
    op.drop_table("monitor_overrides")
    op.drop_index("ix_monitor_transitions_occurred_at", table_name="monitor_transitions")
    op.drop_index("ix_monitor_transitions_component", table_name="monitor_transitions")
    op.drop_table("monitor_transitions")
    op.drop_index("ix_monitor_observations_observed_at", table_name="monitor_observations")
    op.drop_index("ix_monitor_observations_component", table_name="monitor_observations")
    op.drop_table("monitor_observations")
    op.drop_table("monitor_components")
    # Automated incidents have no author; they cannot survive a NOT NULL
    # created_by, so they are removed before the constraint is restored.
    op.execute("DELETE FROM public_incidents WHERE created_by IS NULL")
    op.execute("DELETE FROM status_incident_updates WHERE created_by IS NULL")
    op.alter_column(
        "status_incident_updates", "created_by", existing_type=sa.Uuid(), nullable=False
    )
    op.alter_column("public_incidents", "created_by", existing_type=sa.Uuid(), nullable=False)
    op.drop_index("ix_public_incidents_monitor_service_key", table_name="public_incidents")
    op.drop_column("public_incidents", "monitor_service_key")
    op.drop_column("public_incidents", "source")
