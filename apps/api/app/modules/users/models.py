"""User-owned profile mappings; account authorization remains in auth."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class UsersBase(DeclarativeBase):
    """Metadata for tables owned by the users feature."""


class Profile(UsersBase):
    """Private-by-default profile state."""

    __tablename__ = "profiles"
    __table_args__ = (
        CheckConstraint("visibility IN ('private', 'public')", name="ck_profiles_visibility"),
        CheckConstraint("version >= 0", name="ck_profiles_version"),
        CheckConstraint(
            "bio IS NULL OR (length(bio) <= 160 AND position(E'\\n' in bio) = 0 "
            "AND position(E'\\r' in bio) = 0)",
            name="ck_profiles_bio",
        ),
        CheckConstraint(
            "visibility <> 'public' OR (published_at IS NOT NULL "
            "AND nullif(btrim(display_name), '') IS NOT NULL "
            "AND nullif(btrim(bio), '') IS NOT NULL "
            "AND nullif(btrim(photo_key), '') IS NOT NULL)",
            name="ck_profiles_public_local_fields",
        ),
        Index(
            "ix_profiles_public_account",
            "account_id",
            postgresql_where=text("visibility = 'public'"),
        ),
    )

    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", name="fk_profiles_account"), primary_key=True
    )
    display_name: Mapped[str | None] = mapped_column(Text)
    bio: Mapped[str | None] = mapped_column(Text)
    photo_key: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(Text, nullable=False, server_default="private")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class ProfileLink(UsersBase):
    """Ordered HTTPS link attached to a profile."""

    __tablename__ = "profile_links"
    __table_args__ = (
        CheckConstraint(
            "url ~ '^https://[^/@?#[:space:]]+(/[^?#[:space:]]*)?(\\?[^#[:space:]]*)?$'",
            name="ck_profile_links_https",
        ),
        CheckConstraint("position >= 0", name="ck_profile_links_position"),
        UniqueConstraint("account_id", "position", name="uq_profile_links_position"),
        Index("ix_profile_links_account_id", "account_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("profiles.account_id", name="fk_profile_links_profile"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class PhotoUpload(UsersBase):
    """Owner-authorized private staging and cleaned-photo metadata."""

    __tablename__ = "photo_uploads"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'cleaned', 'expired')", name="ck_photo_uploads_state"
        ),
        CheckConstraint(
            "byte_count IS NULL OR (byte_count > 0 AND byte_count <= 5242880)",
            name="ck_photo_uploads_size",
        ),
        CheckConstraint(
            "media_type IS NULL OR media_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name="ck_photo_uploads_media_type",
        ),
        Index("ix_photo_uploads_account_id", "account_id"),
        Index(
            "ix_photo_uploads_pending_expiry",
            "expires_at",
            postgresql_where=text("state = 'pending'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("accounts.id", name="fk_photo_uploads_account"),
        nullable=False,
    )
    staging_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    clean_key: Mapped[str | None] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    byte_count: Mapped[int | None] = mapped_column(Integer)
    media_type: Mapped[str | None] = mapped_column(Text)
