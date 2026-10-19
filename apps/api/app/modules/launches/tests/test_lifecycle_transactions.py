"""Database-backed regression coverage for booking cutoffs and atomic reschedules."""

from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from uuid6 import uuid7

from app.modules.auth.models import Account
from app.modules.auth.staff import AuthAccessService
from app.modules.launches.models import LaunchBooking
from app.modules.launches.policies import LaunchConflictError
from app.modules.launches.service import LaunchBookingService
from app.modules.products.models import Product
from app.modules.products.service import ProductService
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.outbox import OutboxRepository


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_cancel_cutoff_and_failed_reschedule_preserve_booking_state() -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 17, 12, tzinfo=UTC)
        founder_id = uuid4()
        product_ids = [uuid4() for _ in range(5)]
        booking_ids: list[UUID] = []
        database = Database.connect(os.environ["DATABASE_URL"])
        codec = EmailPayloadCodec({"launch-lifecycle-test": b"l" * 32}, "launch-lifecycle-test")
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
                for product_id in product_ids:
                    await session.execute(
                        insert(Product).values(
                            id=product_id,
                            founder_id=founder_id,
                            status="scheduled",
                            version=5,
                            name="Launch lifecycle test",
                            pitch="Private until launch",
                            description="Description",
                            website_url="https://example.test/product",
                            website_key="https://example.test/product",
                            created_at=now,
                            updated_at=now,
                        )
                    )

                # Product 0 is cancelled just before cutoff; product 1 tests
                # the exact cutoff. Product 2 targets a date held by products 3
                # and 4, so a failed replacement must retain its old booking.
                launch_dates = [date(2026, 10, 18), date(2026, 10, 19), date(2026, 10, 20)]
                for index, product_id in enumerate(product_ids):
                    launch_date = launch_dates[index] if index < 3 else date(2026, 10, 21)
                    booking_id = uuid7()
                    booking_ids.append(booking_id)
                    key = f"lifecycle-{index}"
                    await session.execute(
                        insert(LaunchBooking).values(
                            id=booking_id,
                            product_id=product_id,
                            founder_id=founder_id,
                            launch_date=launch_date,
                            launch_at=datetime.combine(
                                launch_date, datetime.min.time(), tzinfo=UTC
                            ),
                            state="scheduled",
                            idempotency_key=key,
                            request_fingerprint=hashlib.sha256(key.encode()).hexdigest(),
                            created_at=now,
                            closed_at=None,
                        )
                    )

            access = AuthAccessService()
            outbox = OutboxRepository()
            products = ProductService(
                member_access=access,
                payload_codec=codec,
                outbox_repository=outbox,
            )
            service = LaunchBookingService(
                member_access=access,
                product_access=products,
                outbox_repository=outbox,
                payload_codec=codec,
                clock=lambda: now,
            )
            before_cutoff = datetime(2026, 10, 17, 23, 59, 59, 999999, tzinfo=UTC)
            cancellation_service = LaunchBookingService(
                member_access=access,
                product_access=products,
                outbox_repository=outbox,
                payload_codec=codec,
                clock=lambda: before_cutoff,
            )

            async with sessions() as session, session.begin():
                cancelled = await cancellation_service.cancel(
                    session,
                    actor_id=founder_id,
                    product_id=product_ids[0],
                    expected_version=5,
                    idempotency_key="cancel-before-cutoff",
                )
                assert cancelled.state == "cancelled"
                saved_product = await session.get(Product, product_ids[0])
                assert saved_product is not None
                assert saved_product.status == "approved"
                assert saved_product.version == 6
                released_count = await session.scalar(
                    select(func.count())
                    .select_from(LaunchBooking)
                    .where(
                        LaunchBooking.founder_id == founder_id,
                        LaunchBooking.launch_date == date(2026, 10, 18),
                        LaunchBooking.state == "scheduled",
                    )
                )
                assert released_count == 0

            for label, cutoff_time in (
                ("at", datetime(2026, 10, 19, tzinfo=UTC)),
                ("after", datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC)),
            ):
                cutoff_service = LaunchBookingService(
                    member_access=access,
                    product_access=products,
                    outbox_repository=outbox,
                    payload_codec=codec,
                    clock=lambda cutoff_time=cutoff_time: cutoff_time,
                )
                async with sessions() as session, session.begin():
                    with pytest.raises(LaunchConflictError):
                        await cutoff_service.cancel(
                            session,
                            actor_id=founder_id,
                            product_id=product_ids[1],
                            expected_version=5,
                            idempotency_key=f"cancel-{label}-cutoff",
                        )
                    saved_booking = await session.scalar(
                        select(LaunchBooking).where(LaunchBooking.id == booking_ids[1])
                    )
                    saved_product = await session.get(Product, product_ids[1])
                    assert saved_booking is not None and saved_booking.state == "scheduled"
                    assert saved_product is not None and saved_product.status == "scheduled"
                    assert saved_product.version == 5

            async with sessions() as session, session.begin():
                with pytest.raises(LaunchConflictError):
                    await service.reschedule(
                        session,
                        actor_id=founder_id,
                        product_id=product_ids[2],
                        launch_date=date(2026, 10, 21),
                        expected_version=5,
                        idempotency_key="reschedule-to-full-day",
                    )
                old_booking = await session.scalar(
                    select(LaunchBooking).where(LaunchBooking.id == booking_ids[2])
                )
                product = await session.get(Product, product_ids[2])
                assert old_booking is not None
                assert old_booking.state == "scheduled"
                assert old_booking.launch_date == date(2026, 10, 20)
                assert product is not None and product.status == "scheduled"
                assert product.version == 5
                target_count = await session.scalar(
                    select(func.count())
                    .select_from(LaunchBooking)
                    .where(
                        LaunchBooking.founder_id == founder_id,
                        LaunchBooking.launch_date == date(2026, 10, 21),
                        LaunchBooking.state == "scheduled",
                    )
                )
                assert target_count == 2
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(
                    delete(LaunchBooking).where(LaunchBooking.founder_id == founder_id)
                )
                await connection.execute(delete(Product).where(Product.id.in_(product_ids)))
                await connection.execute(delete(Account).where(Account.id == founder_id))
            await database.close()

    asyncio.run(verify())
