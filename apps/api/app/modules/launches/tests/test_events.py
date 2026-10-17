"""PostgreSQL booking and timed outbox work share one transaction."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.auth.models import Account
from app.modules.auth.staff import AuthAccessService
from app.modules.launches.models import LaunchBooking
from app.modules.launches.service import LaunchBookingService
from app.modules.products.models import Product
from app.modules.products.service import ProductService
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.models import OutboxMessage
from app.shared.events.outbox import OutboxRepository


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_booking_and_replacement_create_distinct_due_work_in_one_transaction() -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 17, 22, tzinfo=UTC)
        founder_id, product_id = uuid4(), uuid4()
        database = Database.connect(os.environ["DATABASE_URL"])
        codec = EmailPayloadCodec({"launch-events-test": b"e" * 32}, "launch-events-test")
        booking_ids: list[object] = []
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                await session.execute(
                    insert(Account).values(
                        id=founder_id,
                        email_display=f"{founder_id}@example.test",
                        email_key=f"{founder_id}@example.test",
                        password_hash="integration-only-placeholder",
                        verified_at=now,
                        role="member",
                        suspended_at=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                await session.execute(
                    insert(Product).values(
                        id=product_id,
                        founder_id=founder_id,
                        status="approved",
                        version=4,
                        name="Timed launch",
                        pitch="Private before launch",
                        description="Description",
                        website_url="https://example.test/timed-launch",
                        website_key="https://example.test/timed-launch",
                        created_at=now,
                        updated_at=now,
                    )
                )
            access = AuthAccessService()
            outbox = OutboxRepository()
            products = ProductService(
                member_access=access,
                payload_codec=codec,
                outbox_repository=outbox,
                clock=lambda: now,
            )
            service = LaunchBookingService(
                member_access=access,
                product_access=products,
                outbox_repository=outbox,
                payload_codec=codec,
                clock=lambda: now,
            )
            async with sessions() as session, session.begin():
                first = await service.book(
                    session,
                    actor_id=founder_id,
                    product_id=product_id,
                    launch_date=date(2026, 10, 18),
                    expected_version=4,
                    idempotency_key="timed-first",
                )
                booking_ids.append(first.id)
                first_events = list(
                    (
                        await session.scalars(
                            select(OutboxMessage).where(OutboxMessage.aggregate_id == first.id)
                        )
                    ).all()
                )
                assert {event.event_type for event in first_events} == {
                    "launch.reminder_requested.v1",
                    "launch.publish_requested.v1",
                }
                assert {event.available_at for event in first_events} == {
                    now,
                    datetime(2026, 10, 18, tzinfo=UTC),
                }
                for event in first_events:
                    payload = codec.decode(event.key_id, event.encrypted_payload or b"")
                    assert payload == {
                        "launch_booking_id": str(first.id),
                        "product_id": str(product_id),
                    }

            async with sessions() as session, session.begin():
                replacement = await service.reschedule(
                    session,
                    actor_id=founder_id,
                    product_id=product_id,
                    launch_date=date(2026, 10, 19),
                    expected_version=5,
                    idempotency_key="timed-replacement",
                )
                booking_ids.append(replacement.id)
                second_events = list(
                    (
                        await session.scalars(
                            select(OutboxMessage).where(
                                OutboxMessage.aggregate_id == replacement.id
                            )
                        )
                    ).all()
                )
                assert {event.event_type for event in second_events} == {
                    "launch.reminder_requested.v1",
                    "launch.publish_requested.v1",
                }
                assert {event.available_at for event in second_events} == {
                    datetime(2026, 10, 18, tzinfo=UTC),
                    datetime(2026, 10, 19, tzinfo=UTC),
                }
                assert replacement.id != first.id
        finally:
            async with database.engine.begin() as connection:
                if booking_ids:
                    await connection.execute(
                        delete(OutboxMessage).where(OutboxMessage.aggregate_id.in_(booking_ids))
                    )
                    await connection.execute(
                        delete(LaunchBooking).where(LaunchBooking.id.in_(booking_ids))
                    )
                await connection.execute(delete(Product).where(Product.id == product_id))
                await connection.execute(delete(Account).where(Account.id == founder_id))
            await database.close()

    asyncio.run(verify())
