"""Index founder launch-booking history pages."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_launch_history_index"
down_revision: str | None = "0012_launch_schedule"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_launch_bookings_founder_created",
        "launch_bookings",
        ["founder_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_launch_bookings_founder_created", table_name="launch_bookings")
