"""Add the owner-authorized product destination to review notifications."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_notification_product_link"
down_revision: str | None = "0008_product_review_notices"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("product_id", sa.Uuid(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE notifications AS n SET product_id = s.product_id "
            "FROM product_review_decisions AS d "
            "JOIN product_submissions AS s ON s.id = d.submission_id "
            "WHERE n.review_decision_id = d.id"
        )
    )
    op.alter_column("notifications", "product_id", nullable=False)
    op.create_foreign_key(
        "fk_notifications_product_id_products",
        "notifications",
        "products",
        ["product_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_notifications_product_id_products", "notifications", type_="foreignkey")
    op.drop_column("notifications", "product_id")
