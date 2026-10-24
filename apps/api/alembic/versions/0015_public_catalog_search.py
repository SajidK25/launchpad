"""Index launched products for public catalog search."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015_public_catalog_search"
down_revision: str | None = "0014_public_launch_index"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_products_launched_name_trgm ON products "
        "USING gin (name gin_trgm_ops) WHERE status = 'launched'"
    )
    op.execute(
        "CREATE INDEX ix_products_launched_pitch_trgm ON products "
        "USING gin (pitch gin_trgm_ops) WHERE status = 'launched'"
    )
    op.execute(
        "CREATE INDEX ix_products_launched_description_trgm ON products "
        "USING gin (description gin_trgm_ops) WHERE status = 'launched'"
    )
    op.execute(
        "CREATE INDEX ix_products_launched_catalog_order ON products "
        "(launched_at DESC, lower(name), id) WHERE status = 'launched'"
    )
    op.create_index("ix_product_topics_topic_product", "product_topics", ["topic_id", "product_id"])


def downgrade() -> None:
    op.drop_index("ix_product_topics_topic_product", table_name="product_topics")
    op.drop_index("ix_products_launched_catalog_order", table_name="products")
    op.drop_index("ix_products_launched_description_trgm", table_name="products")
    op.drop_index("ix_products_launched_pitch_trgm", table_name="products")
    op.drop_index("ix_products_launched_name_trgm", table_name="products")
