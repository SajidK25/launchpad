"""Durable immutable comments, one-level replies, and retry receipts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class CommentBase(DeclarativeBase):
    """Metadata owned by the comments feature."""


class Comment(CommentBase):
    """One immutable public comment or direct reply."""

    __tablename__ = "comments"
    __table_args__ = (
        CheckConstraint("depth IN (0, 1)", name="ck_comments_depth"),
        CheckConstraint(
            "(depth = 0 AND parent_id IS NULL AND parent_depth IS NULL) OR "
            "(depth = 1 AND parent_id IS NOT NULL AND parent_depth = 0)",
            name="ck_comments_topology",
        ),
        CheckConstraint("char_length(trim(body)) BETWEEN 1 AND 2000", name="ck_comments_body"),
        CheckConstraint("char_length(body_fingerprint) = 64", name="ck_comments_body_fingerprint"),
        CheckConstraint("moderation_status IN ('visible')", name="ck_comments_moderation_status"),
        UniqueConstraint("id", "product_id", "depth", name="uq_comments_parent_target"),
        ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            ondelete="RESTRICT",
            name="fk_comments_product",
        ),
        ForeignKeyConstraint(
            ["author_account_id"],
            ["accounts.id"],
            ondelete="RESTRICT",
            name="fk_comments_author",
        ),
        ForeignKeyConstraint(
            ["parent_id", "product_id", "parent_depth"],
            ["comments.id", "comments.product_id", "comments.depth"],
            ondelete="RESTRICT",
            name="fk_comments_parent",
        ),
        Index(
            "ix_comments_visible_product_created",
            "product_id",
            text("created_at DESC"),
            text("id DESC"),
            postgresql_where=text("moderation_status = 'visible' AND depth = 0"),
        ),
        Index(
            "ix_comments_visible_parent_created",
            "parent_id",
            text("created_at DESC"),
            text("id DESC"),
            postgresql_where=text("moderation_status = 'visible' AND depth = 1"),
        ),
        Index(
            "ix_comments_author_created",
            "author_account_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_comments_duplicate_lookup",
            "author_account_id",
            "product_id",
            "body_fingerprint",
            text("created_at DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    product_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    author_account_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    depth: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    parent_depth: Mapped[int | None] = mapped_column(SmallInteger)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    body_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    moderation_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="visible")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CommentIdempotencyReceipt(CommentBase):
    """Durable author-scoped receipt for one committed posting attempt."""

    __tablename__ = "comment_idempotency_receipts"
    __table_args__ = (
        CheckConstraint(
            "char_length(idempotency_key) BETWEEN 1 AND 255 "
            "AND idempotency_key = trim(idempotency_key)",
            name="ck_comment_receipts_key",
        ),
        ForeignKeyConstraint(
            ["author_account_id"],
            ["accounts.id"],
            ondelete="RESTRICT",
            name="fk_comment_receipts_author",
        ),
        ForeignKeyConstraint(
            ["comment_id"],
            ["comments.id"],
            ondelete="RESTRICT",
            name="fk_comment_receipts_comment",
        ),
        CheckConstraint(
            "char_length(request_fingerprint) = 64",
            name="ck_comment_receipts_fingerprint",
        ),
        Index(
            "uq_comment_receipts_author_key",
            "author_account_id",
            "idempotency_key",
            unique=True,
        ),
        Index("ix_comment_receipts_comment", "comment_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    author_account_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    comment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
