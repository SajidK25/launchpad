"""Add the operations-owned demo seed ownership ledger.

Revision ID: 0017_demo_seed_ownership
Revises: 0016_votes_and_daily_rankings
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision: str = "0017_demo_seed_ownership"
down_revision: str | None = "0016_votes_and_daily_rankings"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Add target manifest and stable artifact ownership records."""

    op.create_table(
        "demo_seed_datasets",
        sa.Column("target_id", sa.Text(), primary_key=True),
        sa.Column("dataset_version", sa.Text(), nullable=False),
        sa.Column("anchor_utc_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(target_id) BETWEEN 1 AND 120 AND target_id = trim(target_id)",
            name="ck_demo_seed_datasets_target",
        ),
        sa.CheckConstraint(
            "length(dataset_version) BETWEEN 1 AND 80 AND dataset_version = trim(dataset_version)",
            name="ck_demo_seed_datasets_version",
        ),
    )
    op.create_table(
        "demo_seed_artifacts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column("seed_key", sa.Text(), nullable=False),
        sa.Column("artifact_kind", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["demo_seed_datasets.target_id"],
            ondelete="RESTRICT",
            name="fk_demo_seed_artifacts_dataset",
        ),
        sa.CheckConstraint(
            "length(seed_key) BETWEEN 1 AND 160 AND seed_key = trim(seed_key)",
            name="ck_demo_seed_artifacts_key",
        ),
        sa.CheckConstraint(
            "artifact_kind IN ('account', 'profile', 'product', 'booking', 'notification')",
            name="ck_demo_seed_artifacts_kind",
        ),
        sa.UniqueConstraint("target_id", "seed_key", name="uq_demo_seed_artifacts_target_key"),
    )
    op.create_index(
        "ix_demo_seed_artifacts_target_kind", "demo_seed_artifacts", ["target_id", "artifact_kind"]
    )


def downgrade() -> None:
    """Refuse to drop ownership records while a seed dataset is retained."""

    connection = op.get_bind()
    dataset_count = connection.scalar(text("SELECT count(*) FROM demo_seed_datasets"))
    artifact_count = connection.scalar(text("SELECT count(*) FROM demo_seed_artifacts"))
    if dataset_count or artifact_count:
        raise RuntimeError("Downgrade refused: demo seed ownership data must be retained.")
    op.drop_index("ix_demo_seed_artifacts_target_kind", table_name="demo_seed_artifacts")
    op.drop_table("demo_seed_artifacts")
    op.drop_table("demo_seed_datasets")
