"""Record each family passkey's browser-reported authenticator attachment.

Informational only (nullable, no default significance) — lets the
Biometric sign-in UI distinguish a credential registered as this device's
own platform authenticator (Face ID/Touch ID/Windows Hello/fingerprint)
from an older credential registered under the previous generic "passkey"
UX, which may have landed in a roaming/password-manager provider instead.
Existing rows get NULL, not a guessed value — nothing about them changes
functionally; they remain valid for sign-in exactly as before.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032_passkey_attachment"
down_revision: str | None = "0031_family_passkeys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_passkeys", sa.Column("authenticator_attachment", sa.String(20))
    )


def downgrade() -> None:
    op.drop_column("user_passkeys", "authenticator_attachment")
