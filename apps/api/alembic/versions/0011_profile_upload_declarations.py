"""Persist declared profile upload size and media type."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_profile_upload_declarations"
down_revision: str | None = "0010_review_read_indexes"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("photo_uploads", sa.Column("declared_byte_count", sa.Integer(), nullable=True))
    op.add_column("photo_uploads", sa.Column("declared_media_type", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_photo_uploads_declared_byte_count",
        "photo_uploads",
        "declared_byte_count IS NULL OR "
        "(declared_byte_count > 0 AND declared_byte_count <= 5242880)",
    )
    op.create_check_constraint(
        "ck_photo_uploads_declared_media_type",
        "photo_uploads",
        "declared_media_type IS NULL OR declared_media_type IN "
        "('image/jpeg', 'image/png', 'image/webp')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_photo_uploads_declared_media_type", "photo_uploads", type_="check")
    op.drop_constraint("ck_photo_uploads_declared_byte_count", "photo_uploads", type_="check")
    op.drop_column("photo_uploads", "declared_media_type")
    op.drop_column("photo_uploads", "declared_byte_count")
