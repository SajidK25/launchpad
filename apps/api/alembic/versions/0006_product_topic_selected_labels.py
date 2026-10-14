"""Retain the founder-selected spelling on each private topic association."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_product_topic_labels"
down_revision: str = "0005_product_drafts_submission"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("product_topics", sa.Column("selected_label", sa.Text(), nullable=True))
    op.execute(
        "UPDATE product_topics AS association "
        "SET selected_label = topic.name_key "
        "FROM topics AS topic WHERE topic.id = association.topic_id"
    )
    op.alter_column("product_topics", "selected_label", nullable=False)
    op.create_check_constraint(
        "ck_product_topics_selected_label",
        "product_topics",
        "selected_label = trim(selected_label) AND length(selected_label) BETWEEN 1 AND 40",
    )


def downgrade() -> None:
    raise RuntimeError("Dropping founder-selected topic labels requires an explicit plan")
