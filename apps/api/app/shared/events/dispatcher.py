"""Typed worker-side dispatch for transactional email and product events."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.email.codec import EmailPayloadCodec, PayloadDecodeError
from app.shared.events.models import OutboxMessage
from app.shared.events.outbox import OutboxRepository, PermanentEventError

logger = logging.getLogger(__name__)

EMAIL_EVENT_TYPES = frozenset(
    {
        "auth.verification_requested.v1",
        "auth.password_reset_requested.v1",
        "auth.password_reset_completed.v1",
        "users.profile_became_private.v1",
    }
)
REVIEW_EMAIL_EVENT_TYPES = frozenset({"review.outcome_email_requested.v1"})
LAUNCH_EMAIL_EVENT_TYPES = frozenset({"launch.notice_email_requested.v1"})
LAUNCH_EVENT_TYPES = frozenset({"launch.reminder_requested.v1", "launch.publish_requested.v1"})
NOTIFICATION_EVENT_TYPES = frozenset({"notification.changed.v1"})
PRODUCT_EVENT_TYPES = frozenset(
    {
        "product.created.v1",
        "product.saved.v1",
        "product.submitted.v1",
        "product.withdrawn.v1",
        "product.deleted.v1",
        "product.asset_changed.v1",
        "product.media_purge.v1",
    }
)
VOTE_RANKING_EVENT_TYPES = frozenset(
    {"product.launched.v1", "vote.changed.v1", "vote.review_decided.v1"}
)


class EmailSender(Protocol):
    async def send(self, payload: dict[str, object], *, message_id: str) -> None: ...


class ProductEventHandler(Protocol):
    async def handle_outbox_event(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        aggregate_id: UUID,
        payload: dict[str, object],
    ) -> None: ...


class ReviewOutcomeEmailHandler(Protocol):
    async def prepare_email(
        self,
        session: AsyncSession,
        *,
        aggregate_id: UUID,
        payload: dict[str, object],
    ) -> dict[str, object]: ...


class NotificationChangedHandler(Protocol):
    async def publish_changed(
        self,
        session: AsyncSession,
        *,
        aggregate_id: UUID,
        payload: dict[str, object],
    ) -> None: ...


class VoteRankingEventHandler(Protocol):
    async def handle_outbox_event(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        aggregate_id: UUID,
        payload: dict[str, object],
    ) -> None: ...


class LaunchNoticeEmailHandler(Protocol):
    async def prepare_email(
        self,
        session: AsyncSession,
        *,
        aggregate_id: UUID,
        payload: dict[str, object],
    ) -> dict[str, object]: ...


class LaunchEventHandler(Protocol):
    async def handle_launch_event(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        aggregate_id: UUID,
        payload: dict[str, object],
    ) -> None: ...


async def dispatch_due(
    session: AsyncSession,
    *,
    repository: OutboxRepository,
    codec: EmailPayloadCodec,
    sender: EmailSender,
    product_handler: ProductEventHandler | None = None,
    review_email_handler: ReviewOutcomeEmailHandler | None = None,
    launch_email_handler: LaunchNoticeEmailHandler | None = None,
    launch_event_handler: LaunchEventHandler | None = None,
    notification_handler: NotificationChangedHandler | None = None,
    vote_ranking_handler: VoteRankingEventHandler | None = None,
    now: datetime | None = None,
    limit: int = 20,
) -> int:
    """Claim and dispatch a bounded batch in the caller's transaction."""

    current = now or datetime.now(UTC)
    events = await repository.claim_due(session, now=current, limit=limit)
    return await dispatch_claimed(
        session,
        events=events,
        repository=repository,
        codec=codec,
        sender=sender,
        product_handler=product_handler,
        review_email_handler=review_email_handler,
        launch_email_handler=launch_email_handler,
        launch_event_handler=launch_event_handler,
        notification_handler=notification_handler,
        vote_ranking_handler=vote_ranking_handler,
        now=current,
    )


async def dispatch_claimed(
    session: AsyncSession,
    *,
    events: list[OutboxMessage],
    repository: OutboxRepository,
    codec: EmailPayloadCodec,
    sender: EmailSender,
    product_handler: ProductEventHandler | None = None,
    review_email_handler: ReviewOutcomeEmailHandler | None = None,
    launch_email_handler: LaunchNoticeEmailHandler | None = None,
    launch_event_handler: LaunchEventHandler | None = None,
    notification_handler: NotificationChangedHandler | None = None,
    vote_ranking_handler: VoteRankingEventHandler | None = None,
    now: datetime | None = None,
) -> int:
    """Dispatch previously claimed events without acquiring claim locks again."""

    current = now or datetime.now(UTC)
    completed = 0
    for event in events:
        if event.event_type not in (
            EMAIL_EVENT_TYPES
            | REVIEW_EMAIL_EVENT_TYPES
            | LAUNCH_EMAIL_EVENT_TYPES
            | LAUNCH_EVENT_TYPES
            | NOTIFICATION_EVENT_TYPES
            | PRODUCT_EVENT_TYPES
            | VOTE_RANKING_EVENT_TYPES
        ):
            await repository.dead_letter(session, event.id)
            logger.error(
                "Outbox event has no registered handler",
                extra={"event_id": str(event.id), "event_type": event.event_type},
            )
            continue
        try:
            payload = codec.decode(event.key_id, event.encrypted_payload or b"")
            if event.event_type in (
                EMAIL_EVENT_TYPES | REVIEW_EMAIL_EVENT_TYPES | LAUNCH_EMAIL_EVENT_TYPES
            ):
                if _is_expired_challenge(event, payload, current):
                    await repository.dead_letter(session, event.id, clear_payload=True)
                    continue
                email_payload = payload
                if event.event_type in REVIEW_EMAIL_EVENT_TYPES:
                    if review_email_handler is None:
                        raise RuntimeError("review email handler is not configured")
                    email_payload = await review_email_handler.prepare_email(
                        session,
                        aggregate_id=event.aggregate_id,
                        payload=payload,
                    )
                elif event.event_type in LAUNCH_EMAIL_EVENT_TYPES:
                    if launch_email_handler is None:
                        raise RuntimeError("launch email handler is not configured")
                    email_payload = await launch_email_handler.prepare_email(
                        session,
                        aggregate_id=event.aggregate_id,
                        payload=payload,
                    )
                await sender.send(email_payload, message_id=f"launchpad-{event.id}")
                await repository.complete_email(
                    session,
                    event.id,
                    message_id=f"launchpad-{event.id}",
                    sent_at=current,
                )
            elif event.event_type in NOTIFICATION_EVENT_TYPES:
                if notification_handler is None:
                    raise RuntimeError("notification event handler is not configured")
                await notification_handler.publish_changed(
                    session,
                    aggregate_id=event.aggregate_id,
                    payload=payload,
                )
                await repository.complete_non_email(session, event.id, completed_at=current)
            elif event.event_type in LAUNCH_EVENT_TYPES:
                if launch_event_handler is None:
                    raise RuntimeError("launch event handler is not configured")
                await launch_event_handler.handle_launch_event(
                    session,
                    event_type=event.event_type,
                    aggregate_id=event.aggregate_id,
                    payload=payload,
                )
                await repository.complete_non_email(session, event.id, completed_at=current)
            elif event.event_type in VOTE_RANKING_EVENT_TYPES:
                if vote_ranking_handler is None:
                    raise RuntimeError("vote ranking handler is not configured")
                await vote_ranking_handler.handle_outbox_event(
                    session,
                    event_type=event.event_type,
                    aggregate_id=event.aggregate_id,
                    payload=payload,
                )
                await repository.complete_non_email(session, event.id, completed_at=current)
            else:
                if product_handler is None:
                    raise RuntimeError("product event handler is not configured")
                await product_handler.handle_outbox_event(
                    session,
                    event_type=event.event_type,
                    aggregate_id=event.aggregate_id,
                    payload=payload,
                )
                await repository.complete_non_email(session, event.id, completed_at=current)
            completed += 1
        except (PayloadDecodeError, PermanentEventError) as error:
            await repository.dead_letter(session, event.id)
            logger.error(
                "Outbox event is permanently invalid",
                extra={
                    "event_id": str(event.id),
                    "event_type": event.event_type,
                    "failure_class": type(error).__name__,
                },
            )
        except Exception as error:
            dead_lettered = await repository.retry(session, event.id, now=current)
            logger.log(
                logging.ERROR if dead_lettered else logging.WARNING,
                "Outbox event handler failed",
                extra={
                    "event_id": str(event.id),
                    "event_type": event.event_type,
                    "failure_class": type(error).__name__,
                    "dead_lettered": dead_lettered,
                },
            )
    return completed


def _is_expired_challenge(event: OutboxMessage, payload: dict[str, object], now: datetime) -> bool:
    if event.event_type not in {
        "auth.verification_requested.v1",
        "auth.password_reset_requested.v1",
    }:
        return False
    expires_at = payload.get("expires_at")
    if not isinstance(expires_at, str):
        return False
    try:
        expiry = datetime.fromisoformat(expires_at)
    except ValueError:
        return True
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return expiry <= now
