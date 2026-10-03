"""Application service for durable review outcome notifications."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.modules.notifications.models import Notification
from app.modules.notifications.policies import review_notification_kind
from app.modules.notifications.repository import NotificationRepository
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.outbox import OutboxEvent, OutboxRepository


class ReviewDecision(Protocol):
    """Minimal review decision data needed to create founder notifications."""

    id: UUID
    outcome: str


class NotificationService:
    """Persist inbox and dispatch intents inside the caller-owned transaction."""

    def __init__(
        self,
        *,
        repository: NotificationRepository | None = None,
        outbox_repository: OutboxRepository | None = None,
        payload_codec: EmailPayloadCodec,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository or NotificationRepository()
        self.outbox_repository = outbox_repository or OutboxRepository()
        self.payload_codec = payload_codec
        self.clock = clock or (lambda: datetime.now(UTC))

    async def record_review_outcome(
        self,
        session: AsyncSession,
        *,
        decision: ReviewDecision,
        founder_id: UUID,
    ) -> Notification:
        """Add one durable notice and two encrypted outbox requests atomically."""

        existing = await self.repository.find_review_notification(session, decision.id)
        if existing is not None:
            return existing

        notification = Notification(
            id=uuid7(),
            recipient_account_id=founder_id,
            review_decision_id=decision.id,
            kind=review_notification_kind(decision.outcome),
            created_at=self.clock(),
            read_at=None,
        )
        await self.repository.add(session, notification)

        email_key, email_payload = self.payload_codec.encode(
            {
                "recipient_account_id": founder_id,
                "review_decision_id": decision.id,
                "notification_id": notification.id,
                "kind": notification.kind,
            }
        )
        await self.outbox_repository.add(
            session,
            OutboxEvent(
                event_type="review.outcome_email_requested.v1",
                aggregate_id=decision.id,
                key_id=email_key,
                encrypted_payload=email_payload,
                available_at=self.clock(),
            ),
        )

        live_key, live_payload = self.payload_codec.encode(
            {
                "recipient_account_id": founder_id,
                "notification_id": notification.id,
                "kind": notification.kind,
            }
        )
        await self.outbox_repository.add(
            session,
            OutboxEvent(
                event_type="notification.changed.v1",
                aggregate_id=decision.id,
                key_id=live_key,
                encrypted_payload=live_payload,
                available_at=self.clock(),
            ),
        )
        return notification
