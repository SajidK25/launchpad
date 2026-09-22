"""Transactional outbox creation, claiming, retry, and completion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import select
from uuid6 import uuid7

from app.shared.events.models import EmailDelivery, OutboxMessage

MAX_ATTEMPTS = 8
BASE_RETRY_SECONDS = 30


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    """Immutable event input produced inside a domain transaction."""

    event_type: str
    aggregate_id: UUID
    key_id: str
    encrypted_payload: bytes
    available_at: datetime
    id: UUID | None = None


class OutboxRepository:
    """Persistence boundary for event producers and the delivery worker."""

    async def add(self, session: AsyncSession, event: OutboxEvent) -> UUID:
        """Insert an event using the caller's transaction and return its stable ID."""

        event_id = event.id or uuid7()
        session.add(
            OutboxMessage(
                id=event_id,
                event_type=event.event_type,
                aggregate_id=event.aggregate_id,
                encrypted_payload=event.encrypted_payload,
                key_id=event.key_id,
                available_at=_utc(event.available_at),
            )
        )
        await session.flush()
        return event_id

    async def claim_due(
        self,
        session: AsyncSession,
        *,
        now: datetime | None = None,
        limit: int = 50,
    ) -> list[OutboxMessage]:
        """Claim due pending events using row locks held by the caller's transaction."""

        current = _utc(now or datetime.now(UTC))
        rows = list(
            (
                await session.scalars(
                    select(OutboxMessage)
                    .where(
                        OutboxMessage.state == "pending",
                        OutboxMessage.available_at <= current,
                        OutboxMessage.attempts < MAX_ATTEMPTS,
                    )
                    .order_by(OutboxMessage.available_at, OutboxMessage.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for row in rows:
            row.state = "claimed"
            row.claimed_at = current
            row.attempts += 1
        await session.flush()
        return rows

    async def retry(
        self,
        session: AsyncSession,
        event_id: UUID,
        *,
        now: datetime | None = None,
        delay_seconds: int | None = None,
    ) -> None:
        """Return a claimed event to pending with bounded exponential backoff."""

        current = _utc(now or datetime.now(UTC))
        event = await session.get(OutboxMessage, event_id, with_for_update=True)
        if event is None or event.state != "claimed":
            return
        delay = delay_seconds if delay_seconds is not None else _retry_delay(event.attempts)
        event.state = "pending"
        event.claimed_at = None
        event.available_at = current + timedelta(seconds=max(0, delay))
        if event.attempts >= MAX_ATTEMPTS:
            event.state = "dead"
        await session.flush()

    async def complete(
        self,
        session: AsyncSession,
        event_id: UUID,
        *,
        message_id: str,
        sent_at: datetime | None = None,
    ) -> None:
        """Record idempotent delivery, then clear ciphertext from the completed event."""

        event = await session.get(OutboxMessage, event_id, with_for_update=True)
        if event is None:
            return
        delivered_at = _utc(sent_at or datetime.now(UTC))
        await session.execute(
            insert(EmailDelivery)
            .values(event_id=event_id, message_id=message_id, sent_at=delivered_at)
            .on_conflict_do_nothing(index_elements=[EmailDelivery.event_id])
        )
        event.state = "completed"
        event.completed_at = delivered_at
        event.claimed_at = None
        event.encrypted_payload = None
        await session.flush()

    async def release_expired_claims(
        self,
        session: AsyncSession,
        *,
        now: datetime | None = None,
        lease_seconds: int = 300,
    ) -> int:
        """Requeue or dead-letter claims whose worker lease expired."""

        current = _utc(now or datetime.now(UTC))
        expired = OutboxMessage.claimed_at < current - timedelta(seconds=max(0, lease_seconds))
        dead_result = await session.execute(
            update(OutboxMessage)
            .where(
                OutboxMessage.state == "claimed",
                OutboxMessage.claimed_at.is_not(None),
                expired,
                OutboxMessage.attempts >= MAX_ATTEMPTS,
            )
            .values(state="dead", claimed_at=None)
        )
        pending_result = await session.execute(
            update(OutboxMessage)
            .where(
                OutboxMessage.state == "claimed",
                OutboxMessage.claimed_at.is_not(None),
                expired,
                OutboxMessage.attempts < MAX_ATTEMPTS,
            )
            .values(
                state="pending",
                claimed_at=None,
                available_at=current + timedelta(seconds=BASE_RETRY_SECONDS),
            )
        )
        await session.flush()
        dead_count: int = cast(CursorResult[Any], dead_result).rowcount
        pending_count: int = cast(CursorResult[Any], pending_result).rowcount
        return dead_count + pending_count


def _retry_delay(attempts: int) -> int:
    return min(BASE_RETRY_SECONDS * (1 << max(0, attempts - 1)), 3600)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
