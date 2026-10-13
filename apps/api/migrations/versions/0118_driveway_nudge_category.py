"""Nudges: the fixed system "Driveway" category, seeded per Home.

The Driveway-managed category (``todo_categories.managed_source = 'driveway'``,
previously labelled "Vehicles" and created on first use) becomes the fixed
system category "Driveway":

1. A Home that already has its own category named "Driveway" (any case) keeps
   that row: it is adopted as the system category, and anything filed under
   the old managed "Vehicles" category moves into it.
2. Every other managed category is renamed "Driveway".
3. Every Home without one gets it (owned by the Home's creator); a Home's own
   "Driveway" category is adopted rather than duplicated.
4. Every Driveway-sourced reminder (``reminders.source_type = 'driveway'``) is
   filed under its Home's Driveway category.

No rows are deleted except a replaced "Vehicles" category whose contents have
all been moved. Downgrade renames the system category back to "Vehicles"
where that name is free; seeded categories and reminder filing are left as
they are (both are valid under the previous schema).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0118_driveway_nudge_category"
down_revision: str | None = "0117_vehicle_mot_nudge_plan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Adopt a Home's own "Driveway" category where a managed one also exists.
    op.execute(
        """
        CREATE TEMP TABLE driveway_category_merge ON COMMIT DROP AS
        SELECT DISTINCT ON (managed.id) managed.id AS old_id, own.id AS new_id
        FROM todo_categories managed
        JOIN todo_categories own
          ON own.group_id = managed.group_id
         AND own.id <> managed.id
         AND lower(own.name) = 'driveway'
        WHERE managed.managed_source = 'driveway'
        ORDER BY managed.id, own.created_at, own.id
        """
    )
    op.execute(
        """
        UPDATE reminders t SET category_id = m.new_id
        FROM driveway_category_merge m WHERE t.category_id = m.old_id
        """
    )
    op.execute(
        """
        UPDATE todos t SET category_id = m.new_id
        FROM driveway_category_merge m WHERE t.category_id = m.old_id
        """
    )
    op.execute(
        """
        UPDATE household_routines t SET category_id = m.new_id
        FROM driveway_category_merge m WHERE t.category_id = m.old_id
        """
    )
    op.execute(
        "DELETE FROM todo_categories WHERE id IN (SELECT old_id FROM driveway_category_merge)"
    )
    op.execute(
        """
        UPDATE todo_categories SET managed_source = 'driveway'
        WHERE id IN (SELECT new_id FROM driveway_category_merge)
        """
    )

    # 2. Rename the remaining managed categories.
    op.execute(
        """
        UPDATE todo_categories SET name = 'Driveway', updated_at = now()
        WHERE managed_source = 'driveway' AND name <> 'Driveway'
        """
    )

    # 3. Seed: adopt a Home's own "Driveway" category, else create one.
    op.execute(
        """
        UPDATE todo_categories SET managed_source = 'driveway'
        WHERE id IN (
            SELECT DISTINCT ON (c.group_id) c.id
            FROM todo_categories c
            WHERE lower(c.name) = 'driveway' AND c.managed_source IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM todo_categories m
                WHERE m.group_id = c.group_id AND m.managed_source = 'driveway'
              )
            ORDER BY c.group_id, c.created_at, c.id
        )
        """
    )
    op.execute(
        """
        INSERT INTO todo_categories (id, group_id, name, created_by, managed_source)
        SELECT gen_random_uuid(), g.id, 'Driveway', g.created_by, 'driveway'
        FROM groups g
        WHERE NOT EXISTS (
            SELECT 1 FROM todo_categories c
            WHERE c.group_id = g.id AND c.managed_source = 'driveway'
        )
        """
    )

    # 4. File every Driveway-sourced reminder under its Home's category.
    op.execute(
        """
        UPDATE reminders r SET category_id = c.id
        FROM todo_categories c
        WHERE r.source_type = 'driveway'
          AND c.group_id = r.group_id
          AND c.managed_source = 'driveway'
          AND r.category_id IS DISTINCT FROM c.id
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE todo_categories c SET name = 'Vehicles'
        WHERE c.managed_source = 'driveway'
          AND NOT EXISTS (
            SELECT 1 FROM todo_categories o
            WHERE o.group_id = c.group_id AND o.id <> c.id AND lower(o.name) = 'vehicles'
          )
        """
    )
