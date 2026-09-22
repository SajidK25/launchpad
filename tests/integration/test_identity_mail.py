"""Real PostgreSQL checks for transactional encrypted mail events."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.models import EmailDelivery, OutboxMessage
from app.shared.events.outbox import OutboxEvent, OutboxRepository
from conftest import IntegrationSettings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker


def _event(
    codec: EmailPayloadCodec, *, event_type: str = "auth.verification_requested.v1"
) -> OutboxEvent:
    key_id, ciphertext = codec.encode(
        {"recipient": "member@example.com", "link": "https://example.test/verify?token=raw"}
    )
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
