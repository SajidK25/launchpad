"""Durable account-scoped notification mappings."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, Uuid, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class NotificationBase(DeclarativeBase):
    """Metadata owned by the notifications feature."""


class Notification(NotificationBase):
    """One persistent review outcome in a founder's private inbox."""

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('review_approved', 'review_rejected', 'review_changes_requested')",
            name="ck_notifications_kind",
        ),
        Index(
            "ix_notifications_recipient_created",
            "recipient_account_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
        Index(
            "ix_notifications_unread_recipient",
            "recipient_account_id",
            postgresql_where=text("read_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    recipient_account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    review_decision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("product_review_decisions.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
