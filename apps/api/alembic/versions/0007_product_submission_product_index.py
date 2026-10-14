"""Index all submission periods for product cascade lookups."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_product_submission_idx"
down_revision: str = "0006_product_topic_labels"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_product_submissions_product_id", "product_submissions", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_product_submissions_product_id", table_name="product_submissions")
