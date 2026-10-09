"""Index approved review pages and notification product references."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_review_read_indexes"
down_revision: str | None = "0009_notification_product_link"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_product_submissions_approved_page",
        "product_submissions",
        [sa.text("closed_at DESC"), sa.text("product_id DESC")],
        postgresql_where=sa.text("state = 'approved'"),
    )
    op.create_index(
        "ix_notifications_product_id",
        "notifications",
        ["product_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_product_id", table_name="notifications")
    op.drop_index(
        "ix_product_submissions_approved_page",
        table_name="product_submissions",
    )
