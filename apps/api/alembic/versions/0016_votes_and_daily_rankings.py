"""Add durable vote history, moderation audit, and frozen daily rankings.

Revision ID: 0016_votes_and_daily_rankings
Revises: 0015_public_catalog_search
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_votes_and_daily_rankings"
down_revision: str | None = "0015_public_catalog_search"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Create voting tables without modifying existing account or product rows."""

    op.create_table(
        "votes",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("member_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("product_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("cast_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default="active"),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
        sa.Column("invalidated_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["member_id"], ["accounts.id"], ondelete="RESTRICT", name="fk_votes_member"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], ondelete="RESTRICT", name="fk_votes_product"
        ),
        sa.CheckConstraint(
            "state IN ('active', 'withdrawn', 'invalidated')", name="ck_votes_state"
        ),
        sa.CheckConstraint(
            "(state = 'active' AND withdrawn_at IS NULL AND invalidated_at IS NULL) OR "
            "(state = 'withdrawn' AND withdrawn_at IS NOT NULL AND invalidated_at IS NULL) OR "
            "(state = 'invalidated' AND invalidated_at IS NOT NULL)",
            name="ck_votes_state_timestamps",
        ),
    )
    op.create_index(
        "uq_votes_active_member_product",
        "votes",
        ["member_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )
    op.create_index("ix_votes_product_cast", "votes", ["product_id", "cast_at", "id"])
    op.create_index("ix_votes_member_product", "votes", ["member_id", "product_id", "cast_at"])
    op.create_index(
        "ix_votes_active_product_cast",
        "votes",
        ["product_id", "cast_at", "id"],
        postgresql_where=sa.text("state = 'active'"),
    )

    op.create_table(
        "vote_idempotency_receipts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("member_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("vote_id", sa.Uuid(as_uuid=True)),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["member_id"], ["accounts.id"], ondelete="RESTRICT", name="fk_vote_receipts_member"
        ),
        sa.ForeignKeyConstraint(
            ["vote_id"], ["votes.id"], ondelete="RESTRICT", name="fk_vote_receipts_vote"
        ),
        sa.CheckConstraint("command IN ('cast', 'withdraw')", name="ck_vote_receipts_command"),
        sa.CheckConstraint("length(request_fingerprint) = 64", name="ck_vote_receipts_fingerprint"),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 255 AND idempotency_key = trim(idempotency_key)",
            name="ck_vote_receipts_key",
        ),
    )
    op.create_index(
        "uq_vote_receipts_member_key",
        "vote_idempotency_receipts",
        ["member_id", "idempotency_key"],
        unique=True,
    )
    op.create_index("ix_vote_receipts_vote", "vote_idempotency_receipts", ["vote_id"])

    op.create_table(
        "vote_risk_flags",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("vote_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("member_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("signal_code", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["vote_id"], ["votes.id"], ondelete="RESTRICT", name="fk_vote_flags_vote"
        ),
        sa.ForeignKeyConstraint(
            ["member_id"], ["accounts.id"], ondelete="RESTRICT", name="fk_vote_flags_member"
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'cleared', 'invalidated')", name="ck_vote_flags_state"
        ),
        sa.CheckConstraint("length(signal_code) BETWEEN 1 AND 80", name="ck_vote_flags_signal"),
    )
    op.create_index(
        "ix_vote_flags_pending_created",
        "vote_risk_flags",
        ["created_at", "id"],
        postgresql_where=sa.text("state = 'pending'"),
    )
    op.create_index("ix_vote_flags_vote", "vote_risk_flags", ["vote_id", "created_at"])

    op.create_table(
        "vote_review_decisions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("flag_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("reviewer_account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["flag_id"], ["vote_risk_flags.id"], ondelete="RESTRICT", name="fk_vote_decisions_flag"
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_account_id"],
            ["accounts.id"],
            ondelete="RESTRICT",
            name="fk_vote_decisions_reviewer",
        ),
        sa.CheckConstraint(
            "outcome IN ('cleared', 'invalidated')", name="ck_vote_decisions_outcome"
        ),
        sa.CheckConstraint(
            "length(trim(reason)) BETWEEN 1 AND 2000", name="ck_vote_decisions_reason"
        ),
    )
    op.create_index(
        "ix_vote_decisions_flag_created", "vote_review_decisions", ["flag_id", "created_at", "id"]
    )

    op.create_table(
        "daily_ranking_snapshots",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("launch_date", sa.Date(), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("algorithm_version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("algorithm_version >= 1", name="ck_daily_snapshots_algorithm_version"),
        sa.UniqueConstraint("launch_date", name="uq_daily_ranking_snapshots_date"),
    )
    op.create_table(
        "daily_ranking_entries",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("snapshot_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("product_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Numeric(24, 12), nullable=False),
        sa.Column("active_vote_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["daily_ranking_snapshots.id"],
            ondelete="RESTRICT",
            name="fk_daily_entries_snapshot",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], ondelete="RESTRICT", name="fk_daily_entries_product"
        ),
        sa.CheckConstraint("rank >= 1", name="ck_daily_entries_rank"),
        sa.CheckConstraint("active_vote_count >= 0", name="ck_daily_entries_vote_count"),
        sa.CheckConstraint("score >= 0", name="ck_daily_entries_score"),
        sa.UniqueConstraint("snapshot_id", "product_id", name="uq_daily_entries_snapshot_product"),
        sa.UniqueConstraint("snapshot_id", "rank", name="uq_daily_entries_snapshot_rank"),
    )
    op.create_index(
        "ix_daily_entries_product", "daily_ranking_entries", ["product_id", "snapshot_id"]
    )
    op.create_table(
        "voting_feature_state",
        sa.Column("singleton_id", sa.Integer(), primary_key=True, server_default="1"),
        sa.Column("enabled_from", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("singleton_id = 1", name="ck_voting_feature_state_singleton"),
    )


def downgrade() -> None:
    """Drop only an unused schema; retain any vote, audit, or snapshot records."""

    bind = op.get_bind()
    has_retained_data = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM votes) "
            "OR EXISTS (SELECT 1 FROM vote_idempotency_receipts) "
            "OR EXISTS (SELECT 1 FROM vote_risk_flags) "
            "OR EXISTS (SELECT 1 FROM vote_review_decisions) "
            "OR EXISTS (SELECT 1 FROM daily_ranking_snapshots) "
            "OR EXISTS (SELECT 1 FROM daily_ranking_entries) "
            "OR EXISTS (SELECT 1 FROM voting_feature_state)"
        )
    ).scalar_one()
    if has_retained_data:
        raise RuntimeError(
            "Downgrade refused: vote history, moderation audit, or daily snapshots exist. "
            "Use a separately reviewed retention migration before removing this schema."
        )
    op.drop_table("daily_ranking_entries")
    op.drop_table("daily_ranking_snapshots")
    op.drop_table("vote_review_decisions")
    op.drop_table("vote_risk_flags")
    op.drop_table("vote_idempotency_receipts")
    op.drop_table("votes")
    op.drop_table("voting_feature_state")
