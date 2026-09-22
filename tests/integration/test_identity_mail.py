"""Real PostgreSQL checks for transactional encrypted mail events."""

from __future__ import annotations

import asyncio
import json
import urllib.request
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.email.transport import EmailTransport
from app.shared.events.dispatcher import dispatch_due
from app.shared.events.models import EmailDelivery, OutboxMessage
from app.shared.events.outbox import OutboxEvent, OutboxRepository
from conftest import IntegrationSettings, MailSettings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker


def _event(
    codec: EmailPayloadCodec,
    *,
    event_type: str = "auth.verification_requested.v1",
    payload: dict[str, object] | None = None,
) -> OutboxEvent:
    message = payload or {
        "recipient": "member@example.com",
        "subject": "Verify your Launchpad account",
        "body": "Use the verification link.",
    }
    key_id, ciphertext = codec.encode(message)
    return OutboxEvent(
        event_type=event_type,
        aggregate_id=uuid4(),
        key_id=key_id,
        encrypted_payload=ciphertext,
        available_at=datetime.now(UTC),
    )


def test_outbox_insert_is_atomic_with_the_calling_transaction(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        codec = EmailPayloadCodec({"v1": b"a" * 32}, "v1")
        repository = OutboxRepository()
        try:
            await database.prepare()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions.begin() as session:
                await repository.add(session, _event(codec))
            try:
                async with sessions.begin() as session:
                    await repository.add(session, _event(codec))
                    raise RuntimeError("rollback")
            except RuntimeError:
                pass
            async with sessions() as session:
                rows = list((await session.scalars(select(OutboxMessage))).all())
                assert len(rows) == 1
        finally:
            await database.close()

    asyncio.run(verify())


def test_due_event_is_sent_and_recorded_with_stable_message_id(
    integration_settings_fixture: IntegrationSettings,
    mail_settings: MailSettings,
    reset_database: None,
) -> None:
    async def verify() -> None:
        from app.shared.events.dispatcher import dispatch_due

        database = Database.connect(integration_settings_fixture.database_url)
        codec = EmailPayloadCodec({"v1": b"c" * 32}, "v1")
        repository = OutboxRepository()
        try:
            await database.prepare()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions.begin() as session:
                event_id = await repository.add(
                    session,
                    _event(
                        codec,
                        payload={
                            "recipient": "member@example.com",
                            "subject": "T5 delivery sentinel",
                            "body": "A durable message.",
                        },
                    ),
                )
            sender = EmailTransport(
                hostname=mail_settings.smtp_host,
                port=mail_settings.smtp_port,
                sender="noreply@example.com",
                use_tls=False,
            )
            async with sessions.begin() as session:
                assert (
                    await dispatch_due(
                        session,
                        repository=repository,
                        codec=codec,
                        sender=sender,
                    )
                    == 1
                )
            async with sessions() as session:
                delivery = await session.get(EmailDelivery, event_id)
                assert delivery is not None
                assert delivery.message_id == f"launchpad-{event_id}"
        finally:
            await database.close()

    asyncio.run(verify())
    with urllib.request.urlopen(f"{mail_settings.api_url}/api/v1/messages", timeout=2) as response:
        messages = json.load(response)["messages"]
    assert any(message["Subject"] == "T5 delivery sentinel" for message in messages)


def test_concurrent_claim_and_retry_completion_are_durable(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        codec = EmailPayloadCodec({"v1": b"b" * 32}, "v1")
        repository = OutboxRepository()
        try:
            await database.prepare()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions.begin() as session:
                event_id = await repository.add(session, _event(codec))

            async def claim_once() -> int:
                async with sessions.begin() as session:
                    claimed = await repository.claim_due(session, limit=1)
                    return len(claimed)

            claimed_counts = await asyncio.gather(claim_once(), claim_once())
            assert sorted(claimed_counts) == [0, 1]

            future = datetime.now(UTC) + timedelta(seconds=301)
            async with sessions.begin() as session:
                assert await repository.release_expired_claims(session, now=future) == 1
            retry_time = future + timedelta(seconds=31)
            async with sessions.begin() as session:
                claimed = await repository.claim_due(session, now=retry_time, limit=1)
                assert len(claimed) == 1
                await repository.complete(
                    session, event_id, message_id="message-1", sent_at=retry_time
                )
            async with sessions() as session:
                row = await session.get(OutboxMessage, event_id)
                delivery = await session.get(EmailDelivery, event_id)
                assert row is not None and row.state == "completed"
                assert row.encrypted_payload is None
                assert delivery is not None and delivery.message_id == "message-1"
        finally:
            await database.close()

    asyncio.run(verify())


def test_expired_challenge_is_dropped_while_privacy_notice_delivers(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    class RecordingSender:
        def __init__(self) -> None:
            self.subjects: list[str] = []

        async def send(self, payload: dict[str, object], *, message_id: str) -> None:
            self.subjects.append(str(payload["subject"]))

    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        codec = EmailPayloadCodec({"v1": b"d" * 32}, "v1")
        repository = OutboxRepository()
        now = datetime.now(UTC)
        sender = RecordingSender()
        try:
            await database.prepare()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions.begin() as session:
                await repository.add(
                    session,
                    _event(
                        codec,
                        payload={
                            "recipient": "member@example.com",
                            "subject": "Expired verification",
                            "body": "stale",
                            "expires_at": (now - timedelta(minutes=1)).isoformat(),
                        },
                    ),
                )
                await repository.add(
                    session,
                    _event(
                        codec,
                        event_type="users.profile_became_private.v1",
                        payload={
                            "recipient": "member@example.com",
                            "subject": "Your profile is private",
                            "body": "notice",
                        },
                    ),
                )
            async with sessions.begin() as session:
                assert (
                    await dispatch_due(
                        session,
                        repository=repository,
                        codec=codec,
                        sender=sender,
                        now=now + timedelta(seconds=1),
                    )
                    == 1
                )
            assert sender.subjects == ["Your profile is private"]
        finally:
            await database.close()

    asyncio.run(verify())


def test_smtp_failure_keeps_event_retryable_until_recovery(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    class FlakySender:
        def __init__(self) -> None:
            self.calls = 0

        async def send(self, payload: dict[str, object], *, message_id: str) -> None:
            self.calls += 1
            if self.calls == 1:
                raise OSError("smtp unavailable")

    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        codec = EmailPayloadCodec({"v1": b"e" * 32}, "v1")
        repository = OutboxRepository()
        sender = FlakySender()
        try:
            await database.prepare()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions.begin() as session:
                event_id = await repository.add(session, _event(codec))
            async with sessions.begin() as session:
                assert (
                    await dispatch_due(
                        session,
                        repository=repository,
                        codec=codec,
                        sender=sender,
                    )
                    == 0
                )
            async with sessions() as session:
                pending = await session.get(OutboxMessage, event_id)
                assert pending is not None and pending.state == "pending"
                retry_time = pending.available_at + timedelta(seconds=1)
            async with sessions.begin() as session:
                assert (
                    await dispatch_due(
                        session,
                        repository=repository,
                        codec=codec,
                        sender=sender,
                        now=retry_time,
                    )
                    == 1
                )
            assert sender.calls == 2
        finally:
            await database.close()

    asyncio.run(verify())
