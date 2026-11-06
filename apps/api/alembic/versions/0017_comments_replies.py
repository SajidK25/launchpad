"""Add immutable comments, one-level replies, and retry receipts.

Revision ID: 0017_comments_replies
Revises: 0016_votes_and_daily_rankings
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_comments_replies"
down_revision: str | None = "0016_votes_and_daily_rankings"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Add discussion storage without changing existing account or product rows."""

    op.create_table(
        "comments",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("product_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("author_account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("depth", sa.SmallInteger(), nullable=False),
        sa.Column("parent_id", sa.Uuid(as_uuid=True)),
        sa.Column("parent_depth", sa.SmallInteger()),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("body_fingerprint", sa.Text(), nullable=False),
        sa.Column("moderation_status", sa.Text(), nullable=False, server_default="visible"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], ondelete="RESTRICT", name="fk_comments_product"
        ),
        sa.ForeignKeyConstraint(
            ["author_account_id"],
            ["accounts.id"],
            ondelete="RESTRICT",
            name="fk_comments_author",
        ),
        sa.UniqueConstraint("id", "product_id", "depth", name="uq_comments_parent_target"),
        sa.ForeignKeyConstraint(
            ["parent_id", "product_id", "parent_depth"],
            ["comments.id", "comments.product_id", "comments.depth"],
            ondelete="RESTRICT",
            name="fk_comments_parent",
        ),
        sa.CheckConstraint("depth IN (0, 1)", name="ck_comments_depth"),
        sa.CheckConstraint(
            "(depth = 0 AND parent_id IS NULL AND parent_depth IS NULL) OR "
            "(depth = 1 AND parent_id IS NOT NULL AND parent_depth = 0)",
            name="ck_comments_topology",
        ),
        sa.CheckConstraint("char_length(trim(body)) BETWEEN 1 AND 2000", name="ck_comments_body"),
        sa.CheckConstraint(
            "char_length(body_fingerprint) = 64", name="ck_comments_body_fingerprint"
        ),
        sa.CheckConstraint(
            "moderation_status IN ('visible')", name="ck_comments_moderation_status"
        ),
    )
    op.create_index(
        "ix_comments_visible_product_created",
        "comments",
        ["product_id", sa.text("created_at DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("moderation_status = 'visible' AND depth = 0"),
    )
    op.create_index(
        "ix_comments_visible_parent_created",
        "comments",
        ["parent_id", sa.text("created_at DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("moderation_status = 'visible' AND depth = 1"),
    )
    op.create_index(
        "ix_comments_author_created",
        "comments",
        ["author_account_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_comments_duplicate_lookup",
        "comments",
        [
            "author_account_id",
            "product_id",
            "body_fingerprint",
            sa.text("created_at DESC"),
        ],
    )

    op.create_table(
        "comment_idempotency_receipts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("author_account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("comment_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["author_account_id"],
            ["accounts.id"],
            ondelete="RESTRICT",
            name="fk_comment_receipts_author",
        ),
        sa.ForeignKeyConstraint(
            ["comment_id"],
            ["comments.id"],
            ondelete="RESTRICT",
            name="fk_comment_receipts_comment",
        ),
        sa.CheckConstraint(
            "char_length(idempotency_key) BETWEEN 1 AND 255 "
            "AND idempotency_key = trim(idempotency_key)",
            name="ck_comment_receipts_key",
        ),
        sa.CheckConstraint(
            "char_length(request_fingerprint) = 64",
            name="ck_comment_receipts_fingerprint",
        ),
    )
    op.create_index(
        "uq_comment_receipts_author_key",
        "comment_idempotency_receipts",
        ["author_account_id", "idempotency_key"],
        unique=True,
    )
    op.create_index("ix_comment_receipts_comment", "comment_idempotency_receipts", ["comment_id"])


def downgrade() -> None:
    """Remove only an unused comment schema; never discard retained discussion."""

    bind = op.get_bind()
    has_retained_data = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM comments) OR "
            "EXISTS (SELECT 1 FROM comment_idempotency_receipts)"
        )
    ).scalar_one()
    if has_retained_data:
        raise RuntimeError(
            "Downgrade refused: comment history or idempotency receipts exist. "
            "Disable the feature and use a separately reviewed retention migration."
        )
    op.drop_table("comment_idempotency_receipts")
    op.drop_table("comments")
