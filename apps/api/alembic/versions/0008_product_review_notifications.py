"""Extend private product review states and add durable review records."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_product_review_notices"
down_revision: str = "0007_product_submission_idx"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_products_status", "products", type_="check")
    op.create_check_constraint(
        "ck_products_status",
        "products",
        "status IN ('draft', 'submitted', 'changes_requested', 'approved', 'rejected')",
    )
    op.drop_constraint("ck_products_submitted_fields", "products", type_="check")
    op.create_check_constraint(
        "ck_products_submitted_fields",
        "products",
        "status IN ('draft', 'changes_requested') OR "
        "(name IS NOT NULL AND pitch IS NOT NULL AND description IS NOT NULL "
        "AND website_url IS NOT NULL AND website_key IS NOT NULL)",
    )
    op.create_index(
        "ix_products_approved_updated",
        "products",
        ["updated_at", "id"],
        postgresql_where=sa.text("status = 'approved'"),
    )
    op.drop_constraint("ck_product_submissions_state", "product_submissions", type_="check")
    op.create_check_constraint(
        "ck_product_submissions_state",
        "product_submissions",
        "state IN ('pending', 'withdrawn', 'changes_requested', 'approved', 'rejected')",
    )
    op.drop_constraint("ck_product_submissions_closed", "product_submissions", type_="check")
    op.create_check_constraint(
        "ck_product_submissions_closed",
        "product_submissions",
        "(state = 'pending' AND closed_at IS NULL) OR "
        "(state IN ('withdrawn', 'changes_requested', 'approved', 'rejected') "
        "AND closed_at IS NOT NULL)",
    )
    op.create_table(
        "product_review_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "submission_id",
            sa.Uuid(),
            sa.ForeignKey("product_submissions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("from_status", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("reviewed_product_version", sa.Integer(), nullable=False),
        sa.Column("feedback", sa.Text()),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(from_status = 'submitted' AND outcome IN "
            "('approved', 'rejected', 'changes_requested')) OR "
            "(from_status = 'approved' AND outcome = 'changes_requested')",
            name="ck_product_review_decisions_transition",
        ),
        sa.CheckConstraint(
            "(outcome = 'approved' AND feedback IS NULL) OR "
            "(outcome IN ('rejected', 'changes_requested') AND "
            "feedback = trim(feedback) AND length(feedback) BETWEEN 1 AND 2000)",
            name="ck_product_review_decisions_feedback",
        ),
        sa.CheckConstraint(
            "reviewed_product_version >= 0",
            name="ck_product_review_decisions_version",
        ),
        sa.CheckConstraint(
            "idempotency_key = trim(idempotency_key) AND length(idempotency_key) BETWEEN 1 AND 255",
            name="ck_product_review_decisions_idempotency_key",
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64",
            name="ck_product_review_decisions_fingerprint",
        ),
    )
    op.create_index(
        "uq_product_review_decisions_submission_from",
        "product_review_decisions",
        ["submission_id", "from_status"],
        unique=True,
    )
    op.create_index(
        "uq_product_review_decisions_actor_key",
        "product_review_decisions",
        ["actor_account_id", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_product_review_decisions_submission_created",
        "product_review_decisions",
        ["submission_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "recipient_account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "review_decision_id",
            sa.Uuid(),
            sa.ForeignKey("product_review_decisions.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "kind IN ('review_approved', 'review_rejected', 'review_changes_requested')",
            name="ck_notifications_kind",
        ),
    )
    op.create_index(
        "ix_notifications_recipient_created",
        "notifications",
        ["recipient_account_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_notifications_unread_recipient",
        "notifications",
        ["recipient_account_id"],
        postgresql_where=sa.text("read_at IS NULL"),
    )


def downgrade() -> None:
    raise RuntimeError("Review decisions and notifications require an explicit retention plan")
