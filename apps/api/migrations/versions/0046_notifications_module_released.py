"""Promote the Notifications module from beta/off to released/on globally.

The Communications Engine (notify(), NotificationDelivery, templates,
diagnostics) was closed out as permanent foundational infrastructure, but the
FeatureKey.notifications module gating it was still registered
beta/default_enabled=False in mykhaya.module_registry — and that
default_enabled flag was never actually consulted anywhere (is_feature_enabled
only ever reads FeatureFlag/FeatureOverride rows, defaulting to False when
neither exists). The practical effect: on any Home that never explicitly
visited Household Modules and turned "Notifications" on, every reminder that
depends on it — calendar event reminders, Routine reminders, birthday
reminders, daily briefings — was silently a no-op, with the calendar/Routine
UI never mentioning the module even existed.

This seeds the missing global FeatureFlag row so the module resolves enabled
everywhere by default, matching module_registry.py's now-released state,
while leaving any Home's own FeatureOverride row (if one exists) untouched —
overrides still win, so a Home that explicitly disabled it stays disabled.

Revision ID: 0046_notifications_released
Revises: 0045_calendar_colour_hex
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0046_notifications_released"
down_revision: str | None = "0045_calendar_colour_hex"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO feature_flags (id, created_at, updated_at, key, enabled, release_state)
        VALUES (gen_random_uuid(), now(), now(), 'notifications', true, 'released')
        ON CONFLICT (key) DO UPDATE
        SET enabled = true, release_state = 'released', updated_at = now()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE feature_flags
        SET enabled = false, release_state = 'beta', updated_at = now()
        WHERE key = 'notifications'
        """
    )
