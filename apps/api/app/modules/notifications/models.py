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
            "(review_decision_id IS NOT NULL AND launch_booking_id IS NULL AND "
            "kind IN ('review_approved', 'review_rejected', 'review_changes_requested')) OR "
            "(review_decision_id IS NULL AND launch_booking_id IS NOT NULL AND "
            "kind IN ('launch_reminder', 'launch_live', 'launch_failed'))",
            name="ck_notifications_kind",
        ),
        CheckConstraint(
            "(review_decision_id IS NULL) <> (launch_booking_id IS NULL)",
            name="ck_notifications_source",
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
        Index("ix_notifications_product_id", "product_id"),
        Index(
            "uq_notifications_review_decision",
            "review_decision_id",
            unique=True,
            postgresql_where=text("review_decision_id IS NOT NULL"),
        ),
        Index(
            "uq_notifications_launch_booking_kind",
            "launch_booking_id",
            "kind",
            unique=True,
            postgresql_where=text("launch_booking_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    recipient_account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    review_decision_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("product_review_decisions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    launch_booking_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("launch_bookings.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LaunchNotificationPreference(NotificationBase):
    """Independent default-on email and inbox choices for launch notices."""

    __tablename__ = "launch_notification_preferences"
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), primary_key=True
    )
    reminder_email: Mapped[bool] = mapped_column(
        default=True, server_default="true", nullable=False
    )
    reminder_in_site: Mapped[bool] = mapped_column(
        default=True, server_default="true", nullable=False
    )
    live_email: Mapped[bool] = mapped_column(default=True, server_default="true", nullable=False)
    live_in_site: Mapped[bool] = mapped_column(default=True, server_default="true", nullable=False)
    failure_email: Mapped[bool] = mapped_column(default=True, server_default="true", nullable=False)
    failure_in_site: Mapped[bool] = mapped_column(
        default=True, server_default="true", nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
