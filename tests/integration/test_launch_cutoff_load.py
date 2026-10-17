"""PostgreSQL cutoff throughput regression for the one-minute launch target."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, date, datetime, timedelta
from time import monotonic
from uuid import uuid4

import pytest
from app.modules.auth.models import Account
from app.modules.auth.staff import AuthAccessService
from app.modules.launches.models import LaunchBooking
from app.modules.launches.repository import LaunchBookingRepository
from app.modules.launches.service import LaunchBookingService
from app.modules.notifications.models import LaunchNotificationPreference
from app.modules.notifications.service import NotificationService
from app.modules.products.models import Product
from app.modules.products.service import ProductService
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.models import OutboxMessage
from app.shared.events.outbox import OutboxRepository
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

sys.path.insert(0, "apps/worker")

from worker import LaunchEventWorker, process_claimed_events

LOAD_COUNT = 1_000


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_one_thousand_due_launches_publish_within_sixty_seconds() -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 18, tzinfo=UTC)
        product_ids = [uuid4() for _ in range(LOAD_COUNT)]
        founder_ids = [uuid4() for _ in range(LOAD_COUNT)]
        booking_ids = [uuid4() for _ in range(LOAD_COUNT)]
        event_ids = [uuid4() for _ in range(LOAD_COUNT)]
        database = Database.connect(os.environ["DATABASE_URL"])
        outbox = OutboxRepository()
        codec = EmailPayloadCodec({"cutoff-load": b"l" * 32}, "cutoff-load")
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                await session.execute(
                    insert(Account.__table__),
                    [
                        {
                            "id": founder_id,
                            "email_display": f"{founder_id}@load.test",
                            "email_key": f"{founder_id}@load.test",
                            "password_hash": "integration-only-placeholder",
                            "verified_at": now,
                            "role": "member",
                            "created_at": now,
                            "updated_at": now,
                        }
                        for founder_id in founder_ids
                    ],
                )
                await session.execute(
                    insert(Product.__table__),
                    [
                        {
                            "id": product_id,
                            "founder_id": founder_id,
                            "status": "scheduled",
                            "version": 1,
                            "name": f"Cutoff product {index}",
                            "pitch": "Launching at the UTC cutoff",
                            "description": "A cutoff throughput integration fixture.",
                            "website_url": f"https://load-{index}.example.test",
                            "website_key": f"https://load-{index}.example.test",
                            "created_at": now - timedelta(days=1),
                            "updated_at": now - timedelta(days=1),
                        }
                        for index, (product_id, founder_id) in enumerate(
                            zip(product_ids, founder_ids, strict=True)
                        )
                    ],
                )
                await session.execute(
                    insert(LaunchBooking.__table__),
                    [
                        {
                            "id": booking_id,
                            "product_id": product_id,
                            "founder_id": founder_id,
                            "launch_date": date(2026, 10, 18),
                            "launch_at": now,
                            "state": "scheduled",
                            "idempotency_key": f"load-book-{booking_id}",
                            "request_fingerprint": "b" * 64,
                            "created_at": now - timedelta(days=1),
                            "closed_at": None,
                        }
                        for booking_id, product_id, founder_id in zip(
                            booking_ids, product_ids, founder_ids, strict=True
                        )
                    ],
                )
                await session.execute(
                    insert(LaunchNotificationPreference.__table__),
                    [
                        {
                            "account_id": founder_id,
                            "reminder_email": False,
                            "reminder_in_site": False,
                            "live_email": False,
                            "live_in_site": False,
                            "failure_email": False,
                            "failure_in_site": False,
                            "updated_at": now,
                        }
                        for founder_id in founder_ids
                    ],
                )
                await session.execute(
                    insert(OutboxMessage.__table__),
                    [
                        {
                            "id": event_id,
                            "event_type": "launch.publish_requested.v1",
                            "aggregate_id": booking_id,
                            "encrypted_payload": codec.encode(
                                {
                                    "launch_booking_id": str(booking_id),
                                    "product_id": str(product_id),
                                }
                            )[1],
                            "key_id": "cutoff-load",
                            "available_at": now,
                            "attempts": 0,
                            "claimed_at": None,
                            "completed_at": None,
                            "state": "pending",
                        }
                        for event_id, booking_id, product_id in zip(
                            event_ids, booking_ids, product_ids, strict=True
                        )
                    ],
                )

            async with sessions.begin() as session:
                before_cutoff = await outbox.claim_due(
                    session, now=now - timedelta(microseconds=1), limit=LOAD_COUNT
                )
            assert before_cutoff == []

            member_access = AuthAccessService()
            products = ProductService(
                member_access=member_access,
                outbox_repository=outbox,
                payload_codec=codec,
                clock=lambda: now,
            )
            bookings = LaunchBookingService(
                member_access=member_access,
                product_access=products,
                repository=LaunchBookingRepository(),
                outbox_repository=outbox,
                payload_codec=codec,
                clock=lambda: now,
            )
            notifications = NotificationService(
                outbox_repository=outbox,
                payload_codec=codec,
                member_access=member_access,
                clock=lambda: now,
            )
            handler = LaunchEventWorker(
                bookings=bookings,
                products=products,
                notifications=notifications,
                member_access=member_access,
                clock=lambda: now,
            )
            async with sessions.begin() as session:
                claimed = await outbox.claim_due(session, now=now, limit=LOAD_COUNT)
            assert len(claimed) == LOAD_COUNT

            async def dispatch(session: AsyncSession, event: OutboxMessage) -> None:
                from app.shared.events.dispatcher import dispatch_claimed

                await dispatch_claimed(
                    session,
                    events=[event],
                    repository=outbox,
                    codec=codec,
                    sender=_NoopEmailSender(),
                    launch_event_handler=handler,
                )

            started = monotonic()
            await process_claimed_events(
                claimed,
                sessions=sessions,
                dispatch=dispatch,
                concurrency=16,
                email_concurrency=4,
            )
            elapsed = monotonic() - started
            async with sessions() as session:
                launched_ids = set(
                    (
                        await session.scalars(
                            select(Product.__table__.c.id).where(
                                Product.__table__.c.id.in_(product_ids),
                                Product.__table__.c.status == "launched",
                            )
                        )
                    ).all()
                )
            assert launched_ids == set(product_ids)
            assert elapsed < 60, f"1,000 launches took {elapsed:.1f}s"
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(
                    delete(OutboxMessage.__table__).where(
                        OutboxMessage.__table__.c.id.in_(event_ids)
                    )
                )
                await connection.execute(
                    delete(LaunchBooking.__table__).where(
                        LaunchBooking.__table__.c.id.in_(booking_ids)
                    )
                )
                await connection.execute(
                    delete(LaunchNotificationPreference.__table__).where(
                        LaunchNotificationPreference.__table__.c.account_id.in_(founder_ids)
                    )
                )
                await connection.execute(
                    delete(Product.__table__).where(Product.__table__.c.id.in_(product_ids))
                )
                await connection.execute(
                    delete(Account.__table__).where(Account.__table__.c.id.in_(founder_ids))
                )
            await database.close()

    asyncio.run(verify())


class _NoopEmailSender:
    async def send(self, _payload: dict[str, object], *, message_id: str) -> None:
        raise AssertionError(f"load fixture must not send email: {message_id}")
