"""Dispatch contracts for review email and notification invalidation events."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.dispatcher import dispatch_due
from app.shared.events.outbox import OutboxRepository, PermanentEventError
from sqlalchemy.ext.asyncio import AsyncSession


class _Repository:
    def __init__(self, *events: SimpleNamespace) -> None:
        self.events = list(events)
        self.emails: list[UUID] = []
        self.completed: list[UUID] = []
        self.dead: list[UUID] = []
        self.retried: list[UUID] = []

    async def claim_due(
        self, _session: AsyncSession, *, now: datetime, limit: int
    ) -> list[SimpleNamespace]:
        del now, limit
        return self.events

    async def complete_email(
        self,
        _session: AsyncSession,
        event_id: UUID,
        *,
        message_id: str,
        sent_at: datetime,
    ) -> None:
        del message_id, sent_at
        self.emails.append(event_id)

    async def complete_non_email(
        self, _session: AsyncSession, event_id: UUID, *, completed_at: datetime
    ) -> None:
        del completed_at
        self.completed.append(event_id)

    async def dead_letter(
        self, _session: AsyncSession, event_id: UUID, *, clear_payload: bool = False
    ) -> None:
        del clear_payload
        self.dead.append(event_id)

    async def retry(self, _session: AsyncSession, event_id: UUID, *, now: datetime) -> bool:
        del now
        self.retried.append(event_id)
        return False


class _Sender:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[tuple[dict[str, object], str]] = []

    async def send(self, payload: dict[str, object], *, message_id: str) -> None:
        if self.fail:
            raise OSError("mail provider unavailable")
        self.sent.append((payload, message_id))


class _FailOnceSender:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.sent: list[tuple[dict[str, object], str]] = []

    async def send(self, payload: dict[str, object], *, message_id: str) -> None:
        self.calls.append(message_id)
        if len(self.calls) == 1:
            raise OSError("temporary provider outage")
        self.sent.append((payload, message_id))


class _ReviewEmail:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[UUID, dict[str, object]]] = []

    async def prepare_email(
        self,
        _session: AsyncSession,
        *,
        aggregate_id: UUID,
        payload: dict[str, object],
    ) -> dict[str, object]:
        if self.error is not None:
            raise self.error
        self.calls.append((aggregate_id, payload))
        return {
            "recipient": "founder@example.com",
            "subject": "Your product review is complete",
            "body": "Sign in to view your update.",
        }


class _NotificationHandler:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[UUID, dict[str, object]]] = []

    async def publish_changed(
        self,
        _session: AsyncSession,
        *,
        aggregate_id: UUID,
        payload: dict[str, object],
    ) -> None:
        if self.error is not None:
            raise self.error
        self.calls.append((aggregate_id, payload))


def _event(
    codec: EmailPayloadCodec, event_type: str, payload: Mapping[str, object]
) -> SimpleNamespace:
    key_id, ciphertext = codec.encode(payload)
    return SimpleNamespace(
        id=uuid4(),
        event_type=event_type,
        aggregate_id=uuid4(),
        key_id=key_id,
        encrypted_payload=ciphertext,
    )


def test_review_email_and_notification_events_use_typed_handlers() -> None:
    async def verify() -> None:
        codec = EmailPayloadCodec({"test": b"r" * 32}, "test")
        review_payload = {
            "recipient_account_id": str(uuid4()),
            "review_decision_id": str(uuid4()),
            "notification_id": str(uuid4()),
            "kind": "review_approved",
        }
        review = _event(codec, "review.outcome_email_requested.v1", review_payload)
        changed = _event(
            codec,
            "notification.changed.v1",
            {"recipient_account_id": str(uuid4()), "notification_id": str(uuid4())},
        )
        repository = _Repository(review, changed)
        sender = _Sender()
        email_handler = _ReviewEmail()
        notification_handler = _NotificationHandler()

        completed = await dispatch_due(
            cast(AsyncSession, object()),
            repository=cast(OutboxRepository, repository),
            codec=codec,
            sender=sender,
            review_email_handler=email_handler,
            notification_handler=notification_handler,
        )

        assert completed == 2
        assert email_handler.calls == [(review.aggregate_id, review_payload)]
        assert sender.sent[0][0]["recipient"] == "founder@example.com"
        assert sender.sent[0][1] == f"launchpad-{review.id}"
        assert notification_handler.calls[0][0] == changed.aggregate_id
        assert repository.emails == [review.id]
        assert repository.completed == [changed.id]

    asyncio.run(verify())


def test_review_email_and_live_failures_return_events_to_retry() -> None:
    async def verify() -> None:
        codec = EmailPayloadCodec({"test": b"r" * 32}, "test")
        review = _event(codec, "review.outcome_email_requested.v1", {"payload": "private"})
        changed = _event(codec, "notification.changed.v1", {"payload": "private"})
        repository = _Repository(review, changed)

        completed = await dispatch_due(
            cast(AsyncSession, object()),
            repository=cast(OutboxRepository, repository),
            codec=codec,
            sender=_Sender(fail=True),
            review_email_handler=_ReviewEmail(),
            notification_handler=_NotificationHandler(error=OSError("Redis unavailable")),
        )

        assert completed == 0
        assert repository.retried == [review.id, changed.id]
        assert repository.dead == []

    asyncio.run(verify())


def test_review_email_retry_reuses_stable_identity_and_completes_once() -> None:
    async def verify() -> None:
        codec = EmailPayloadCodec({"test": b"r" * 32}, "test")
        review = _event(
            codec,
            "review.outcome_email_requested.v1",
            {"recipient": "founder@example.com", "subject": "Review complete", "body": "Sign in"},
        )
        repository = _Repository(review)
        sender = _FailOnceSender()
        handler = _ReviewEmail()
        session = cast(AsyncSession, object())

        first_completed = await dispatch_due(
            session,
            repository=cast(OutboxRepository, repository),
            codec=codec,
            sender=sender,
            review_email_handler=handler,
        )
        second_completed = await dispatch_due(
            session,
            repository=cast(OutboxRepository, repository),
            codec=codec,
            sender=sender,
            review_email_handler=handler,
        )

        expected_message_id = f"launchpad-{review.id}"
        assert first_completed == 0
        assert second_completed == 1
        assert sender.calls == [expected_message_id, expected_message_id]
        assert len(sender.sent) == 1
        assert sender.sent[0][0]["recipient"] == "founder@example.com"
        assert sender.sent[0][1] == expected_message_id
        assert repository.retried == [review.id]
        assert repository.emails == [review.id]
        assert repository.dead == []

    asyncio.run(verify())


def test_duplicate_live_publish_is_safe_and_bad_review_payload_fails_closed() -> None:
    async def verify() -> None:
        codec = EmailPayloadCodec({"test": b"r" * 32}, "test")
        payload = {"recipient_account_id": str(uuid4()), "notification_id": str(uuid4())}
        first = _event(codec, "notification.changed.v1", payload)
        second = _event(codec, "notification.changed.v1", payload)
        malformed = _event(codec, "review.outcome_email_requested.v1", {"kind": "private"})
        repository = _Repository(first, second, malformed)
        notifications = _NotificationHandler()
        email_handler = _ReviewEmail(error=PermanentEventError("invalid review event"))
        sender = _Sender()

        completed = await dispatch_due(
            cast(AsyncSession, object()),
            repository=cast(OutboxRepository, repository),
            codec=codec,
            sender=sender,
            review_email_handler=email_handler,
            notification_handler=notifications,
        )

        assert completed == 2
        assert len(notifications.calls) == 2
        assert notifications.calls[0][1] == notifications.calls[1][1] == payload
        assert repository.completed == [first.id, second.id]
        assert repository.dead == [malformed.id]
        assert sender.sent == []

    asyncio.run(verify())
