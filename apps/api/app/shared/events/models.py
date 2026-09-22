"""SQLAlchemy mappings for durable outbox events and delivery metadata."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Integer, LargeBinary, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class EventsBase(DeclarativeBase):
    """Metadata owned by the shared events boundary."""


class OutboxMessage(EventsBase):
    """Encrypted, retryable event awaiting worker delivery."""

    __tablename__ = "outbox_messages"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    encrypted_payload: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    key_id: Mapped[str] = mapped_column(Text, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default="pending"
    )


class EmailDelivery(EventsBase):
    """Stable delivery record retained after payload ciphertext is cleared."""

    __tablename__ = "email_deliveries"

    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    message_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
