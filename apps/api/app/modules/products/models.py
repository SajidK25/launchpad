"""Private product draft, submission, topic, and asset mappings."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, Uuid, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class ProductBase(DeclarativeBase):
    """Metadata owned by the products feature."""


class Product(ProductBase):
    """Founder-owned private listing; submission does not publish it."""

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'submitted')", name="ck_products_status"),
        CheckConstraint("version >= 0", name="ck_products_version"),
        CheckConstraint(
            "name IS NULL OR (length(trim(name)) BETWEEN 1 AND 80)", name="ck_products_name"
        ),
        CheckConstraint(
            "pitch IS NULL OR (length(trim(pitch)) BETWEEN 1 AND 160)", name="ck_products_pitch"
        ),
        CheckConstraint(
            "description IS NULL OR (length(trim(description)) BETWEEN 1 AND 5000)",
            name="ck_products_description",
        ),
        CheckConstraint(
            "website_url IS NULL OR (length(website_url) <= 2048 AND website_url ~ '^https://[^/@?#[:space:]]+')",
            name="ck_products_website",
        ),
        CheckConstraint(
            "website_key IS NULL OR length(website_key) <= 2048", name="ck_products_website_key"
        ),
        CheckConstraint(
            "status = 'draft' OR (name IS NOT NULL AND pitch IS NOT NULL "
            "AND description IS NOT NULL AND website_url IS NOT NULL "
            "AND website_key IS NOT NULL)",
            name="ck_products_submitted_fields",
        ),
        Index("ix_products_founder_status_updated", "founder_id", "status", "updated_at", "id"),
        Index("ix_products_website_key", "website_key"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    founder_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Text, default="draft", server_default="draft", nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    pitch: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    website_url: Mapped[str | None] = mapped_column(Text)
    website_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProductSubmission(ProductBase):
    """One historical submission period; only one may remain pending."""

    __tablename__ = "product_submissions"
    __table_args__ = (
        CheckConstraint("state IN ('pending', 'withdrawn')", name="ck_product_submissions_state"),
        CheckConstraint("product_version >= 0", name="ck_product_submissions_version"),
        CheckConstraint(
            "(state = 'pending' AND closed_at IS NULL) OR "
            "(state = 'withdrawn' AND closed_at IS NOT NULL)",
            name="ck_product_submissions_closed",
        ),
        Index("ix_product_submissions_product_id", "product_id"),
        Index(
            "uq_product_submissions_pending_product",
            "product_id",
            unique=True,
            postgresql_where=text("state = 'pending'"),
        ),
        Index(
            "ix_product_submissions_pending_queue",
            "submitted_at",
            "id",
            postgresql_where=text("state = 'pending'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    product_version: Mapped[int] = mapped_column(Integer, nullable=False)


class Topic(ProductBase):
    """Canonical label, hidden publicly until first launch."""

    __tablename__ = "topics"
    __table_args__ = (
        CheckConstraint(
            "display_name = trim(display_name) AND length(display_name) BETWEEN 1 AND 40",
            name="ck_topics_display_name",
        ),
        CheckConstraint(
            "name_key = lower(trim(name_key)) AND length(name_key) BETWEEN 1 AND 40",
            name="ck_topics_name_key",
        ),
        Index("uq_topics_name_key", "name_key", unique=True),
        Index(
            "ix_topics_first_launched_name",
            "first_launched_at",
            "name_key",
            postgresql_where=text("first_launched_at IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    name_key: Mapped[str] = mapped_column(Text, nullable=False)
    first_launched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductTopic(ProductBase):
    """Ordered current topic choice."""

    __tablename__ = "product_topics"
    __table_args__ = (
        CheckConstraint("position BETWEEN 1 AND 3", name="ck_product_topics_position"),
        CheckConstraint(
            "selected_label = trim(selected_label) AND length(selected_label) BETWEEN 1 AND 40",
            name="ck_product_topics_selected_label",
        ),
        Index("uq_product_topics_product_position", "product_id", "position", unique=True),
    )

    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("topics.id"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_label: Mapped[str] = mapped_column(Text, nullable=False)


class ProductAsset(ProductBase):
    """Private signed-upload intent and validated image reference."""

    __tablename__ = "product_assets"
    __table_args__ = (
        CheckConstraint("kind IN ('logo', 'screenshot')", name="ck_product_assets_kind"),
        CheckConstraint(
            "state IN ('pending', 'clean', 'failed', 'detached')", name="ck_product_assets_state"
        ),
        CheckConstraint(
            "media_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name="ck_product_assets_media_type",
        ),
        CheckConstraint("byte_count BETWEEN 1 AND 5242880", name="ck_product_assets_byte_count"),
        CheckConstraint(
            "position IS NULL OR (kind = 'screenshot' AND position BETWEEN 1 AND 10)",
            name="ck_product_assets_position",
        ),
        CheckConstraint(
            "attached_at IS NULL OR (state = 'clean' AND (kind = 'logo' OR position IS NOT NULL))",
            name="ck_product_assets_attached",
        ),
        Index(
            "uq_product_assets_attached_logo",
            "product_id",
            unique=True,
            postgresql_where=text("kind = 'logo' AND attached_at IS NOT NULL"),
        ),
        Index(
            "uq_product_assets_attached_screenshot_position",
            "product_id",
            "position",
            unique=True,
            postgresql_where=text("kind = 'screenshot' AND attached_at IS NOT NULL"),
        ),
        Index(
            "ix_product_assets_pending_expiry",
            "expires_at",
            "id",
            postgresql_where=text("state = 'pending'"),
        ),
        Index("ix_product_assets_product_state", "product_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    staging_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    clean_key: Mapped[str | None] = mapped_column(Text, unique=True)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    byte_count: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
