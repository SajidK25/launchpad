"""Add member identity, private profiles, and durable email records.

Revision ID: 0002_member_identity_profiles
Revises: 0001_foundation
Create Date: 2026-09-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_member_identity_profiles"
down_revision: str = "0001_foundation"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Create only additive identity/profile state with database-owned invariants."""

    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("email_display", sa.Text(), nullable=False),
        sa.Column("email_key", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_epoch", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(email_display) > 0", name="ck_accounts_email_display"),
        sa.CheckConstraint("length(email_key) > 0", name="ck_accounts_email_key"),
        sa.CheckConstraint("length(password_hash) > 0", name="ck_accounts_password_hash"),
        sa.CheckConstraint("session_epoch >= 0", name="ck_accounts_session_epoch"),
        sa.UniqueConstraint("email_key", name="uq_accounts_email_key"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("secret_digest", postgresql.BYTEA(), nullable=False),
        sa.Column("session_epoch", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_sessions_account"),
        sa.CheckConstraint("octet_length(secret_digest) = 32", name="ck_sessions_digest_size"),
        sa.CheckConstraint("session_epoch >= 0", name="ck_sessions_epoch"),
        sa.CheckConstraint(
            "idle_expires_at > created_at AND absolute_expires_at > created_at",
            name="ck_sessions_expiry",
        ),
        sa.UniqueConstraint("secret_digest", name="uq_sessions_secret_digest"),
    )
    op.create_index("ix_sessions_account_id", "sessions", ["account_id"])
    for table_name in ("email_verifications", "password_resets"):
        op.create_table(
            table_name,
            sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
            sa.Column("account_id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("token_digest", postgresql.BYTEA(), nullable=False),
            sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["account_id"], ["accounts.id"], name=f"fk_{table_name}_account"
            ),
            sa.CheckConstraint(
                "octet_length(token_digest) = 32", name=f"ck_{table_name}_digest_size"
            ),
            sa.CheckConstraint("expires_at > issued_at", name=f"ck_{table_name}_expiry"),
            sa.UniqueConstraint("token_digest", name=f"uq_{table_name}_token_digest"),
        )
        op.create_index(f"ix_{table_name}_account_id", table_name, ["account_id"])
        op.create_index(
            f"uq_{table_name}_current_account",
            table_name,
            ["account_id"],
            unique=True,
            postgresql_where=sa.text("consumed_at IS NULL AND superseded_at IS NULL"),
        )

    op.create_table(
        "profiles",
        sa.Column("account_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("photo_key", sa.Text(), nullable=True),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="private"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_profiles_account"),
        sa.CheckConstraint("visibility IN ('private', 'public')", name="ck_profiles_visibility"),
        sa.CheckConstraint("version >= 0", name="ck_profiles_version"),
        sa.CheckConstraint(
            "bio IS NULL OR (length(bio) <= 160 AND position(E'\\n' in bio) = 0 "
            "AND position(E'\\r' in bio) = 0)",
            name="ck_profiles_bio",
        ),
        sa.CheckConstraint(
            "visibility <> 'public' OR (published_at IS NOT NULL "
            "AND nullif(btrim(display_name), '') IS NOT NULL "
            "AND nullif(btrim(bio), '') IS NOT NULL "
            "AND nullif(btrim(photo_key), '') IS NOT NULL)",
            name="ck_profiles_public_local_fields",
        ),
    )
    op.create_index(
        "ix_profiles_public_account",
        "profiles",
        ["account_id"],
        postgresql_where=sa.text("visibility = 'public'"),
    )
    op.create_table(
        "profile_links",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["profiles.account_id"], name="fk_profile_links_profile"
        ),
        sa.CheckConstraint("url ~ '^https://[^/ ]+'", name="ck_profile_links_https"),
        sa.CheckConstraint("position >= 0", name="ck_profile_links_position"),
        sa.UniqueConstraint("account_id", "position", name="uq_profile_links_position"),
    )
    op.create_index("ix_profile_links_account_id", "profile_links", ["account_id"])
    op.create_table(
        "photo_uploads",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("staging_key", sa.Text(), nullable=False),
        sa.Column("clean_key", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("byte_count", sa.Integer(), nullable=True),
        sa.Column("media_type", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_photo_uploads_account"),
        sa.CheckConstraint(
            "state IN ('pending', 'cleaned', 'expired')", name="ck_photo_uploads_state"
        ),
        sa.CheckConstraint(
            "byte_count IS NULL OR (byte_count > 0 AND byte_count <= 5242880)",
            name="ck_photo_uploads_size",
        ),
        sa.CheckConstraint(
            "media_type IS NULL OR media_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name="ck_photo_uploads_media_type",
        ),
        sa.UniqueConstraint("staging_key", name="uq_photo_uploads_staging_key"),
        sa.UniqueConstraint("clean_key", name="uq_photo_uploads_clean_key"),
    )
    op.create_index("ix_photo_uploads_account_id", "photo_uploads", ["account_id"])
    op.create_index(
        "ix_photo_uploads_pending_expiry",
        "photo_uploads",
        ["expires_at"],
        postgresql_where=sa.text("state = 'pending'"),
    )

    op.create_table(
        "outbox_messages",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("encrypted_payload", postgresql.BYTEA(), nullable=True),
        sa.Column("key_id", sa.Text(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.Text(), nullable=False, server_default="pending"),
        sa.CheckConstraint("length(event_type) > 0", name="ck_outbox_event_type"),
        sa.CheckConstraint("length(key_id) > 0", name="ck_outbox_key_id"),
        sa.CheckConstraint("attempts >= 0", name="ck_outbox_attempts"),
        sa.CheckConstraint(
            "state IN ('pending', 'claimed', 'completed', 'dead')", name="ck_outbox_state"
        ),
        sa.CheckConstraint(
            "state NOT IN ('pending', 'claimed') OR encrypted_payload IS NOT NULL",
            name="ck_outbox_pending_payload",
        ),
    )
    op.create_index("ix_outbox_aggregate_id", "outbox_messages", ["aggregate_id"])
    op.create_index(
        "ix_outbox_due",
        "outbox_messages",
        ["available_at", "id"],
        postgresql_where=sa.text("state = 'pending'"),
    )
    op.create_table(
        "email_deliveries",
        sa.Column("event_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("message_id", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"], ["outbox_messages.id"], name="fk_email_deliveries_event"
        ),
        sa.UniqueConstraint("message_id", name="uq_email_deliveries_message_id"),
    )


def downgrade() -> None:
    """Refuse destructive rollback; recovery uses a corrective forward revision."""

    raise RuntimeError("Member identity migration cannot be downgraded automatically.")
