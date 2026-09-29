"""Add private product drafts, submission periods, and staff status."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_product_drafts_submission"
down_revision: str = "0004_profile_link_query"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("role", sa.Text(), server_default="member", nullable=False))
    op.add_column("accounts", sa.Column("suspended_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_accounts_role", "accounts", "role IN ('member', 'reviewer', 'admin')"
    )
    op.create_table(
        "account_admin_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("target_account_id", sa.Uuid(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("before_state", sa.Text(), nullable=False),
        sa.Column("after_state", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_account_admin_actions_target_created",
        "account_admin_actions",
        ["target_account_id", "created_at"],
    )
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("founder_id", sa.Uuid(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("status", sa.Text(), server_default="draft", nullable=False),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("name", sa.Text()),
        sa.Column("pitch", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("website_url", sa.Text()),
        sa.Column("website_key", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('draft', 'submitted')", name="ck_products_status"),
        sa.CheckConstraint("version >= 0", name="ck_products_version"),
        sa.CheckConstraint(
            "name IS NULL OR (length(trim(name)) BETWEEN 1 AND 80)", name="ck_products_name"
        ),
        sa.CheckConstraint(
            "pitch IS NULL OR (length(trim(pitch)) BETWEEN 1 AND 160)", name="ck_products_pitch"
        ),
        sa.CheckConstraint(
            "description IS NULL OR (length(trim(description)) BETWEEN 1 AND 5000)",
            name="ck_products_description",
        ),
        sa.CheckConstraint(
            "website_url IS NULL OR (length(website_url) <= 2048 AND website_url ~ '^https://[^/@?#[:space:]]+')",
            name="ck_products_website",
        ),
        sa.CheckConstraint(
            "website_key IS NULL OR length(website_key) <= 2048", name="ck_products_website_key"
        ),
        sa.CheckConstraint(
            "status = 'draft' OR (name IS NOT NULL AND pitch IS NOT NULL "
            "AND description IS NOT NULL AND website_url IS NOT NULL "
            "AND website_key IS NOT NULL)",
            name="ck_products_submitted_fields",
        ),
    )
    op.create_index(
        "ix_products_founder_status_updated",
        "products",
        ["founder_id", "status", "updated_at", "id"],
    )
    op.create_index("ix_products_website_key", "products", ["website_key"])
    op.create_table(
        "product_submissions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "product_id",
            sa.Uuid(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("product_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending', 'withdrawn')", name="ck_product_submissions_state"
        ),
        sa.CheckConstraint("product_version >= 0", name="ck_product_submissions_version"),
        sa.CheckConstraint(
            "(state = 'pending' AND closed_at IS NULL) OR "
            "(state = 'withdrawn' AND closed_at IS NOT NULL)",
            name="ck_product_submissions_closed",
        ),
    )
    op.create_index(
        "uq_product_submissions_pending_product",
        "product_submissions",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text("state = 'pending'"),
    )
    op.create_index(
        "ix_product_submissions_pending_queue",
        "product_submissions",
        ["submitted_at", "id"],
        postgresql_where=sa.text("state = 'pending'"),
    )
    op.create_table(
        "topics",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("name_key", sa.Text(), nullable=False),
        sa.Column("first_launched_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "display_name = trim(display_name) AND length(display_name) BETWEEN 1 AND 40",
            name="ck_topics_display_name",
        ),
        sa.CheckConstraint(
            "name_key = lower(trim(name_key)) AND length(name_key) BETWEEN 1 AND 40",
            name="ck_topics_name_key",
        ),
    )
    op.create_index("uq_topics_name_key", "topics", ["name_key"], unique=True)
    op.create_index(
        "ix_topics_first_launched_name",
        "topics",
        ["first_launched_at", "name_key"],
        postgresql_where=sa.text("first_launched_at IS NOT NULL"),
    )
    op.create_table(
        "product_topics",
        sa.Column(
            "product_id",
            sa.Uuid(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("topic_id", sa.Uuid(), sa.ForeignKey("topics.id"), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("position BETWEEN 1 AND 3", name="ck_product_topics_position"),
    )
    op.create_index(
        "uq_product_topics_product_position",
        "product_topics",
        ["product_id", "position"],
        unique=True,
    )
    op.create_table(
        "product_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "product_id",
            sa.Uuid(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("staging_key", sa.Text(), nullable=False, unique=True),
        sa.Column("clean_key", sa.Text(), unique=True),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("attached_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('logo', 'screenshot')", name="ck_product_assets_kind"),
        sa.CheckConstraint(
            "state IN ('pending', 'clean', 'failed', 'detached')", name="ck_product_assets_state"
        ),
        sa.CheckConstraint(
            "media_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name="ck_product_assets_media_type",
        ),
        sa.CheckConstraint("byte_count BETWEEN 1 AND 5242880", name="ck_product_assets_byte_count"),
        sa.CheckConstraint(
            "position IS NULL OR (kind = 'screenshot' AND position BETWEEN 1 AND 10)",
            name="ck_product_assets_position",
        ),
        sa.CheckConstraint(
            "attached_at IS NULL OR (state = 'clean' AND (kind = 'logo' OR position IS NOT NULL))",
            name="ck_product_assets_attached",
        ),
    )
    op.create_index(
        "uq_product_assets_attached_logo",
        "product_assets",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'logo' AND attached_at IS NOT NULL"),
    )
    op.create_index(
        "uq_product_assets_attached_screenshot_position",
        "product_assets",
        ["product_id", "position"],
        unique=True,
        postgresql_where=sa.text("kind = 'screenshot' AND attached_at IS NOT NULL"),
    )
    op.create_index(
        "ix_product_assets_pending_expiry",
        "product_assets",
        ["expires_at", "id"],
        postgresql_where=sa.text("state = 'pending'"),
    )
    op.create_index("ix_product_assets_product_state", "product_assets", ["product_id", "state"])


def downgrade() -> None:
    raise RuntimeError(
        "Destructive rollback of product and audit records requires an explicit plan"
    )
