"""Transactional review notification behavior."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.service import NotificationService
from app.shared.email.codec import EmailPayloadCodec


class _NotificationRepository:
    def __init__(self) -> None:
        self.rows: dict[Any, Any] = {}
        self.sessions: list[Any] = []

    async def find_review_notification(self, session: Any, decision_id: Any) -> Any:
        self.sessions.append(session)
        return self.rows.get(decision_id)

    async def add(self, session: Any, notification: Any) -> None:
        self.sessions.append(session)
        self.rows[notification.review_decision_id] = notification


class _OutboxRepository:
    def __init__(self, *, fail_on: int | None = None) -> None:
        self.events: list[Any] = []
        self.fail_on = fail_on
        self.sessions: list[Any] = []

    async def add(self, session: Any, event: Any) -> Any:
        self.sessions.append(session)
        if self.fail_on == len(self.events) + 1:
            raise RuntimeError("outbox unavailable")
        self.events.append(event)
        return event.id


def _service(repository: Any, outbox: Any) -> tuple[NotificationService, EmailPayloadCodec]:
    codec = EmailPayloadCodec({"test": b"n" * 32}, "test")
    return (
        NotificationService(
            repository=repository,
            outbox_repository=outbox,
            payload_codec=codec,
            clock=lambda: datetime(2026, 1, 2, tzinfo=UTC),
        ),
        codec,
    )


@asynccontextmanager
async def _caller_transaction(repository: Any, outbox: Any) -> AsyncIterator[None]:
    """Model caller-owned rollback of rows staged by the service."""

    try:
        yield
    except BaseException:
        repository.rows.clear()
        outbox.events.clear()
        raise


def test_review_outcome_records_notice_and_encrypted_channel_events_in_caller_session() -> None:
    async def verify() -> None:
        decision_id, founder_id = uuid4(), uuid4()
        decision = SimpleNamespace(id=decision_id, outcome="changes_requested")
        session = cast(AsyncSession, object())
        repository, outbox = _NotificationRepository(), _OutboxRepository()
        service, codec = _service(repository, outbox)

        notice = await service.record_review_outcome(
            session, decision=decision, founder_id=founder_id
        )

        assert notice is repository.rows[decision_id]
        assert notice.recipient_account_id == founder_id
        assert notice.review_decision_id == decision_id
        assert notice.kind == "review_changes_requested"
        assert len(outbox.events) == 2
        assert {event.event_type for event in outbox.events} == {
            "review.outcome_email_requested.v1",
            "notification.changed.v1",
        }
        assert all(event.aggregate_id == decision_id for event in outbox.events)
        assert repository.sessions == [session, session]
        assert outbox.sessions == [session, session]
        email_payload = codec.decode(
            outbox.events[0].key_id, outbox.events[0].encrypted_payload
        )
        live_payload = codec.decode(outbox.events[1].key_id, outbox.events[1].encrypted_payload)
        assert email_payload == {
            "recipient_account_id": str(founder_id),
            "review_decision_id": str(decision_id),
            "notification_id": str(notice.id),
            "kind": "review_changes_requested",
        }
        assert live_payload == {
            "recipient_account_id": str(founder_id),
            "notification_id": str(notice.id),
            "kind": "review_changes_requested",
        }
        assert "feedback" not in email_payload
        assert "feedback" not in live_payload

    asyncio.run(verify())


def test_replaying_review_outcome_does_not_add_another_notice_or_events() -> None:
    async def verify() -> None:
        decision_id, founder_id = uuid4(), uuid4()
        session = cast(AsyncSession, object())
        repository, outbox = _NotificationRepository(), _OutboxRepository()
        service, _ = _service(repository, outbox)
        decision = SimpleNamespace(id=decision_id, outcome="approved")

        first = await service.record_review_outcome(
            session, decision=decision, founder_id=founder_id
        )
        second = await service.record_review_outcome(
            session, decision=decision, founder_id=founder_id
        )

        assert second is first
        assert len(repository.rows) == 1
        assert len(outbox.events) == 2

    asyncio.run(verify())


def test_outbox_failure_leaves_rollback_to_callers_transaction() -> None:
    async def verify() -> None:
        decision_id, founder_id = uuid4(), uuid4()
        repository, outbox = _NotificationRepository(), _OutboxRepository(fail_on=2)
        service, _ = _service(repository, outbox)
        decision = SimpleNamespace(id=decision_id, outcome="rejected")
        session: Any = SimpleNamespace(begin=AsyncMock())
        typed_session = cast(AsyncSession, session)

        with pytest.raises(RuntimeError, match="outbox unavailable"):
            async with _caller_transaction(repository, outbox):
                await service.record_review_outcome(
                    typed_session, decision=decision, founder_id=founder_id
                )

        # The caller owns commit/rollback. A rolled-back caller transaction drops the first
        # notification and outbox insert together; the service never opens its own transaction.
        assert not session.begin.await_count
        assert repository.rows == {}
        assert outbox.events == []

    asyncio.run(verify())


def test_notification_service_never_calls_a_delivery_provider() -> None:
    async def verify() -> None:
        repository, outbox = _NotificationRepository(), _OutboxRepository()
        service, _ = _service(repository, outbox)
        await service.record_review_outcome(
            cast(AsyncSession, object()),
            decision=SimpleNamespace(id=uuid4(), outcome="approved"),
            founder_id=uuid4(),
        )

        assert not hasattr(service, "email_sender")
        assert not hasattr(service, "redis_publisher")
        assert len(outbox.events) == 2

    asyncio.run(verify())
