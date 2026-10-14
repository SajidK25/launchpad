"""Focused outbox dispatch contracts that do not require external services."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.dispatcher import dispatch_due
from app.shared.events.outbox import MAX_ATTEMPTS, OutboxRepository
from sqlalchemy.ext.asyncio import AsyncSession


class _Session:
    def __init__(self, event: SimpleNamespace) -> None:
        self.event = event
        self.flushes = 0

    async def get(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
        return self.event

    async def flush(self) -> None:
        self.flushes += 1

    async def execute(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("non-email completion must not create an EmailDelivery row")


def test_non_email_completion_clears_payload_without_email_delivery() -> None:
    async def verify() -> None:
        now = datetime(2026, 9, 30, tzinfo=UTC)
        event = SimpleNamespace(
            id=uuid4(),
            state="claimed",
            completed_at=None,
            claimed_at=now,
            encrypted_payload=b"encrypted product event",
        )
        session = _Session(event)

        await OutboxRepository().complete_non_email(
            cast(AsyncSession, session), event.id, completed_at=now
        )

        assert event.state == "completed"
        assert event.completed_at == now
        assert event.claimed_at is None
        assert event.encrypted_payload is None
        assert session.flushes == 1

    asyncio.run(verify())


def test_outbox_retry_dead_letters_exhausted_work_and_retains_replay_payload() -> None:
    async def verify() -> None:
        now = datetime(2026, 9, 30, tzinfo=UTC)
        event = SimpleNamespace(
            id=uuid4(),
            state="claimed",
            attempts=MAX_ATTEMPTS,
            claimed_at=now,
            available_at=now,
            encrypted_payload=b"encrypted replay payload",
        )
        session = _Session(event)

        dead_lettered = await OutboxRepository().retry(
            cast(AsyncSession, session), event.id, now=now
        )

        assert dead_lettered is True
        assert event.state == "dead"
        assert event.claimed_at is None
        assert event.encrypted_payload == b"encrypted replay payload"

    asyncio.run(verify())


class _DispatcherRepository:
    def __init__(self, *events: SimpleNamespace, exhaust: bool = False) -> None:
        self.events = list(events)
        self.exhaust = exhaust
        self.email_completions: list[UUID] = []
        self.non_email_completions: list[UUID] = []
        self.dead_letters: list[tuple[UUID, bool]] = []
        self.retries: list[UUID] = []

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
        self.email_completions.append(event_id)

    async def complete_non_email(
        self, _session: AsyncSession, event_id: UUID, *, completed_at: datetime
    ) -> None:
        del completed_at
        self.non_email_completions.append(event_id)

    async def dead_letter(
        self, _session: AsyncSession, event_id: UUID, *, clear_payload: bool = False
    ) -> None:
        self.dead_letters.append((event_id, clear_payload))

    async def retry(self, _session: AsyncSession, event_id: UUID, *, now: datetime) -> bool:
        del now
        self.retries.append(event_id)
        return self.exhaust


class _Sender:
    def __init__(self) -> None:
        self.sent: list[tuple[dict[str, object], str]] = []

    async def send(self, payload: dict[str, object], *, message_id: str) -> None:
        self.sent.append((payload, message_id))


class _ProductHandler:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, UUID, dict[str, object]]] = []
        self.error = error

    async def handle_outbox_event(
        self,
        _session: AsyncSession,
        *,
        event_type: str,
        aggregate_id: UUID,
        payload: dict[str, object],
    ) -> None:
        if self.error is not None:
            raise self.error
        self.calls.append((event_type, aggregate_id, payload))


def _outbox_event(
    codec: EmailPayloadCodec, event_type: str, payload: dict[str, object]
) -> SimpleNamespace:
    key_id, ciphertext = codec.encode(payload)
    return SimpleNamespace(
        id=uuid4(),
        event_type=event_type,
        aggregate_id=uuid4(),
        key_id=key_id,
        encrypted_payload=ciphertext,
        state="claimed",
    )


def test_product_events_never_reach_email_sender_or_email_delivery() -> None:
    async def verify() -> None:
        codec = EmailPayloadCodec({"test": b"x" * 32}, "test")
        product = _outbox_event(codec, "product.saved.v1", {"product_id": str(uuid4())})
        purge = _outbox_event(
            codec,
            "product.media_purge.v1",
            {"product_id": str(uuid4()), "clean_key": "encrypted-in-payload"},
        )
        repository = _DispatcherRepository(product, purge)
        sender = _Sender()
        handler = _ProductHandler()

        completed = await dispatch_due(
            cast(AsyncSession, object()),
            repository=cast(OutboxRepository, repository),
            codec=codec,
            sender=sender,
            product_handler=handler,
        )

        assert completed == 2
        assert sender.sent == []
        assert [call[0] for call in handler.calls] == [
            "product.saved.v1",
            "product.media_purge.v1",
        ]
        assert repository.non_email_completions == [product.id, purge.id]
        assert repository.email_completions == []

    asyncio.run(verify())


def test_allowlisted_email_events_keep_stable_delivery_behavior() -> None:
    async def verify() -> None:
        codec = EmailPayloadCodec({"test": b"x" * 32}, "test")
        verification = _outbox_event(
            codec,
            "auth.verification_requested.v1",
            {"recipient": "member@example.test", "subject": "Verify", "body": "Link"},
        )
        privacy_notice = _outbox_event(
            codec,
            "users.profile_became_private.v1",
            {"recipient": "member@example.test", "subject": "Private", "body": "Notice"},
        )
        repository = _DispatcherRepository(verification, privacy_notice)
        sender = _Sender()

        completed = await dispatch_due(
            cast(AsyncSession, object()),
            repository=cast(OutboxRepository, repository),
            codec=codec,
            sender=sender,
        )

        assert completed == 2
        assert [delivery[1] for delivery in sender.sent] == [
            f"launchpad-{verification.id}",
            f"launchpad-{privacy_notice.id}",
        ]
        assert repository.email_completions == [verification.id, privacy_notice.id]
        assert repository.non_email_completions == []

    asyncio.run(verify())


def test_unknown_events_fail_closed_and_are_dead_lettered(caplog: Any) -> None:
    async def verify() -> None:
        codec = EmailPayloadCodec({"test": b"x" * 32}, "test")
        unknown = _outbox_event(
            codec,
            "unexpected.event.v1",
            {"recipient": "attacker@example.test", "body": "must not send"},
        )
        repository = _DispatcherRepository(unknown)
        sender = _Sender()

        completed = await dispatch_due(
            cast(AsyncSession, object()),
            repository=cast(OutboxRepository, repository),
            codec=codec,
            sender=sender,
        )

        assert completed == 0
        assert sender.sent == []
        assert repository.dead_letters == [(unknown.id, False)]

    asyncio.run(verify())
    assert "must not send" not in caplog.text
    assert any(
        getattr(record, "event_type", None) == "unexpected.event.v1" for record in caplog.records
    )


def test_exhausted_handler_failure_is_logged_without_sensitive_payload(caplog: Any) -> None:
    async def verify() -> None:
        secret_value = "product-clean/private-object-key"
        codec = EmailPayloadCodec({"test": b"x" * 32}, "test")
        product_event = _outbox_event(codec, "product.media_purge.v1", {"clean_key": secret_value})
        repository = _DispatcherRepository(product_event, exhaust=True)
        handler = _ProductHandler(error=OSError(secret_value))

        completed = await dispatch_due(
            cast(AsyncSession, object()),
            repository=cast(OutboxRepository, repository),
            codec=codec,
            sender=_Sender(),
            product_handler=handler,
        )

        assert completed == 0
        assert repository.retries == [product_event.id]

    asyncio.run(verify())
    assert any(
        getattr(record, "event_type", None) == "product.media_purge.v1"
        and getattr(record, "failure_class", None) == "OSError"
        and getattr(record, "dead_lettered", None) is True
        for record in caplog.records
    )
    assert "product-clean/private-object-key" not in caplog.text
