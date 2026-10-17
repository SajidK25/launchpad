"""Typed launch event categories retain outbox retry and idempotency behavior."""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.dispatcher import dispatch_due
from app.shared.events.outbox import OutboxRepository
from sqlalchemy.ext.asyncio import AsyncSession


class _Repository:
    def __init__(self, *events: SimpleNamespace) -> None:
        self.events = list(events)
        self.completed: list[UUID] = []
        self.emails: list[UUID] = []
        self.dead: list[UUID] = []
        self.retried: list[UUID] = []

    async def claim_due(
        self, _session: AsyncSession, *, now: datetime, limit: int
    ) -> list[SimpleNamespace]:
        del now, limit
        return self.events

    async def complete_non_email(
        self, _session: AsyncSession, event_id: UUID, *, completed_at: datetime
    ) -> None:
        del completed_at
        self.completed.append(event_id)

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
    def __init__(self) -> None:
        self.sent: list[tuple[dict[str, object], str]] = []

    async def send(self, payload: dict[str, object], *, message_id: str) -> None:
        self.sent.append((payload, message_id))


class _LaunchEvents:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, UUID, dict[str, object]]] = []

    async def handle_launch_event(
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


class _LaunchEmail:
    async def prepare_email(
        self,
        _session: AsyncSession,
        *,
        aggregate_id: UUID,
        payload: dict[str, object],
    ) -> dict[str, object]:
        return {
            "recipient": "founder@example.test",
            "subject": str(payload["kind"]),
            "body": str(aggregate_id),
        }


def _event(
    codec: EmailPayloadCodec,
    event_type: str,
    *,
    payload: dict[str, object],
    aggregate_id: UUID | None = None,
) -> SimpleNamespace:
    key_id, ciphertext = codec.encode(payload)
    return SimpleNamespace(
        id=uuid4(),
        event_type=event_type,
        aggregate_id=aggregate_id or uuid4(),
        key_id=key_id,
        encrypted_payload=ciphertext,
    )


def test_typed_launch_events_dispatch_and_unknown_events_dead_letter() -> None:
    async def verify() -> None:
        codec = EmailPayloadCodec({"launch-dispatch": b"d" * 32}, "launch-dispatch")
        booking_id, product_id = uuid4(), uuid4()
        reminder = _event(
            codec,
            "launch.reminder_requested.v1",
            payload={"launch_booking_id": str(booking_id), "product_id": str(product_id)},
            aggregate_id=booking_id,
        )
        publication = _event(
            codec,
            "launch.publish_requested.v1",
            payload={"launch_booking_id": str(booking_id), "product_id": str(product_id)},
            aggregate_id=booking_id,
        )
        email = _event(
            codec,
            "launch.notice_email_requested.v1",
            payload={
                "recipient_account_id": str(uuid4()),
                "launch_booking_id": str(booking_id),
                "notification_id": str(uuid4()),
                "kind": "launch_live",
            },
            aggregate_id=booking_id,
        )
        unknown = _event(codec, "unexpected.launch.v1", payload={"secret": "hidden"})
        repository = _Repository(reminder, publication, email, unknown)
        events = _LaunchEvents()
        sender = _Sender()

        completed = await dispatch_due(
            cast(AsyncSession, object()),
            repository=cast(OutboxRepository, repository),
            codec=codec,
            sender=sender,
            launch_event_handler=events,
            launch_email_handler=_LaunchEmail(),
        )

        assert completed == 3
        assert [call[0] for call in events.calls] == [
            "launch.reminder_requested.v1",
            "launch.publish_requested.v1",
        ]
        assert repository.completed == [reminder.id, publication.id]
        assert repository.emails == [email.id]
        assert sender.sent[0][1] == f"launchpad-{email.id}"
        assert repository.dead == [unknown.id]

    asyncio.run(verify())


def test_launch_handler_transient_failure_is_retried_without_marking_complete() -> None:
    async def verify() -> None:
        codec = EmailPayloadCodec({"launch-dispatch": b"d" * 32}, "launch-dispatch")
        event = _event(
            codec,
            "launch.publish_requested.v1",
            payload={"launch_booking_id": str(uuid4()), "product_id": str(uuid4())},
        )
        repository = _Repository(event)

        completed = await dispatch_due(
            cast(AsyncSession, object()),
            repository=cast(OutboxRepository, repository),
            codec=codec,
            sender=_Sender(),
            launch_event_handler=_LaunchEvents(error=OSError("database unavailable")),
        )

        assert completed == 0
        assert repository.retried == [event.id]
        assert repository.completed == []
        assert repository.dead == []

    asyncio.run(verify())
