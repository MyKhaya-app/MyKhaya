"""Extend the public-status incident model with multi-service impact and an
append-only public update timeline.

Additive and backwards compatible:

- `public_incidents.service`/`state` (the original single-service columns)
  are made nullable rather than dropped, and every existing row is
  backfilled into the new `status_incident_services` table so no historical
  data is lost or reinterpreted.
- `public_incidents.lifecycle_state` (new) and `internal_notes` (new,
  nullable) are additive columns; `lifecycle_state` is backfilled from
  `resolved_at` (resolved rows -> 'resolved', still-active rows ->
  'investigating' — the closest honest default for pre-existing incidents,
  which predate this lifecycle concept).
- `status_incident_updates` (new) gets one backfilled row per existing
  incident (its original title/message/starts_at), so every incident still
  has at least one timeline entry after this migration.

No existing row's `id`, `title`, `service`, `state`, `starts_at` or
`resolved_at` is modified.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040_status_incident_timeline"
down_revision: str | None = "0039_event_recurrence_end_date"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

service_state = postgresql.ENUM(
    "operational",
    "degraded_performance",
    "partial_outage",
    "major_outage",
    "maintenance",
    name="service_state",
    create_type=False,
)
incident_lifecycle_state = postgresql.ENUM(
    "investigating",
    "identified",
    "monitoring",
    "resolved",
    name="incident_lifecycle_state",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(
        "investigating",
        "identified",
        "monitoring",
        "resolved",
        name="incident_lifecycle_state",
    ).create(bind)

    op.add_column(
        "public_incidents",
        sa.Column(
            "lifecycle_state",
            incident_lifecycle_state,
            nullable=False,
            server_default="investigating",
        ),
    )
    op.add_column("public_incidents", sa.Column("internal_notes", sa.String(2000)))
    op.alter_column("public_incidents", "service", existing_type=sa.String(40), nullable=True)
    op.alter_column("public_incidents", "state", existing_type=service_state, nullable=True)
    op.execute(
        "UPDATE public_incidents SET lifecycle_state = "
        "CASE WHEN resolved_at IS NOT NULL THEN 'resolved' ELSE 'investigating' END"
        "::incident_lifecycle_state"
    )

    op.create_table(
        "status_incident_services",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "incident_id",
            sa.Uuid(),
            sa.ForeignKey("public_incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("service", sa.String(40), nullable=False),
        sa.Column("impact", service_state, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("incident_id", "service", name="uq_incident_service"),
    )
    op.create_index(
        "ix_status_incident_services_incident_id", "status_incident_services", ["incident_id"]
    )

    op.create_table(
        "status_incident_updates",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "incident_id",
            sa.Uuid(),
            sa.ForeignKey("public_incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lifecycle_state", incident_lifecycle_state, nullable=False),
        sa.Column("message", sa.String(1000), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("platform_administrators.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_status_incident_updates_incident_id", "status_incident_updates", ["incident_id"]
    )

    op.execute(
        """
        INSERT INTO status_incident_services
            (id, incident_id, service, impact, created_at, updated_at)
        SELECT
            gen_random_uuid(), id, service, state, created_at, updated_at
        FROM public_incidents
        WHERE service IS NOT NULL AND state IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO status_incident_updates
            (id, incident_id, lifecycle_state, message, occurred_at,
             created_by, created_at, updated_at)
        SELECT
            gen_random_uuid(), id, lifecycle_state, message, starts_at,
            created_by, created_at, updated_at
        FROM public_incidents
        """
    )

    op.alter_column("public_incidents", "lifecycle_state", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_status_incident_updates_incident_id", table_name="status_incident_updates")
    op.drop_table("status_incident_updates")
    op.drop_index("ix_status_incident_services_incident_id", table_name="status_incident_services")
    op.drop_table("status_incident_services")
    # service/state are left nullable on downgrade: some incidents created
    # after this migration may have multiple affected services, which
    # cannot be losslessly folded back into a single (service, state) pair
    # without discarding data — re-enforcing NOT NULL here would risk
    # failing the downgrade outright on such rows.
    op.drop_column("public_incidents", "internal_notes")
    op.drop_column("public_incidents", "lifecycle_state")
    bind = op.get_bind()
    postgresql.ENUM(name="incident_lifecycle_state").drop(bind)
