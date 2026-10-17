"""Founder-owned launch bookings and their retained outcomes."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Text, Uuid, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class LaunchBase(DeclarativeBase):
    """Metadata owned by the launches feature."""


class LaunchBooking(LaunchBase):
    """One immutable booking identity with mutable state until it closes."""

    __tablename__ = "launch_bookings"
    __table_args__ = (
        CheckConstraint(
            "state IN ('scheduled', 'replaced', 'cancelled', 'launched', 'missed_day', "
            "'suspension_blocked', 'returned_for_changes')",
            name="ck_launch_bookings_state",
        ),
        CheckConstraint(
            "(state = 'scheduled' AND closed_at IS NULL) OR "
            "(state <> 'scheduled' AND closed_at IS NOT NULL)",
            name="ck_launch_bookings_closed",
        ),
        CheckConstraint(
            "launch_at = (launch_date::timestamp AT TIME ZONE 'UTC')",
            name="ck_launch_bookings_utc_midnight",
        ),
        CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 255 AND "
            "idempotency_key = trim(idempotency_key) AND "
            "length(request_fingerprint) = 64",
            name="ck_launch_bookings_idempotency",
        ),
        CheckConstraint(
            "(closed_by_idempotency_key IS NULL AND close_request_fingerprint IS NULL) OR "
            "(closed_by_idempotency_key IS NOT NULL AND "
            "length(closed_by_idempotency_key) BETWEEN 1 AND 255 AND "
            "closed_by_idempotency_key = trim(closed_by_idempotency_key) AND "
            "length(close_request_fingerprint) = 64)",
            name="ck_launch_bookings_close_idempotency",
        ),
        CheckConstraint(
            "(state IN ('missed_day', 'suspension_blocked') AND failure_reason IS NOT NULL) OR "
            "(state NOT IN ('missed_day', 'suspension_blocked') AND failure_reason IS NULL)",
            name="ck_launch_bookings_failure_reason",
        ),
        CheckConstraint(
            "failure_reason IS NULL OR failure_reason IN ('missed_day', 'suspension_blocked')",
            name="ck_launch_bookings_failure_reason_value",
        ),
        Index(
            "uq_launch_bookings_active_product",
            "product_id",
            unique=True,
            postgresql_where=text("state = 'scheduled'"),
        ),
        Index(
            "ix_launch_bookings_founder_date_active",
            "founder_id",
            "launch_date",
            postgresql_where=text("state = 'scheduled'"),
        ),
        Index(
            "ix_launch_bookings_due",
            "state",
            "launch_at",
            postgresql_where=text("state = 'scheduled'"),
        ),
        Index(
            "uq_launch_bookings_founder_idempotency",
            "founder_id",
            "idempotency_key",
            unique=True,
        ),
        Index(
            "uq_launch_bookings_founder_close_idempotency",
            "founder_id",
            "closed_by_idempotency_key",
            unique=True,
            postgresql_where=text("closed_by_idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    founder_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    launch_date: Mapped[date] = mapped_column(Date, nullable=False)
    launch_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    closed_by_idempotency_key: Mapped[str | None] = mapped_column(Text)
    close_request_fingerprint: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
