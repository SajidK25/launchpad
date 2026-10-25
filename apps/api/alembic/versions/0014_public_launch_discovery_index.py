"""Index launched products by publication time."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_public_launch_index"
down_revision: str | None = "0013_launch_history_index"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_products_launched_at",
        "products",
        ["launched_at"],
        postgresql_where=sa.text("status = 'launched'"),
    )


def downgrade() -> None:
    op.drop_index("ix_products_launched_at", table_name="products")
