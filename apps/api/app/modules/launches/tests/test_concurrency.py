"""PostgreSQL serialization tests for the founder/day booking allocation."""

from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, insert, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from uuid6 import uuid7

from app.modules.auth.models import Account
from app.modules.auth.staff import AuthAccessService
from app.modules.launches.models import LaunchBooking
from app.modules.launches.repository import LaunchBookingRepository
from app.modules.launches.service import LaunchBookingService
from app.modules.products.models import Product
from app.shared.db.database import Database


class _ProductPort:
    """Small lifecycle adapter for exercising launch allocation with real rows."""

    async def get_approved_product(
        self,
        session: Any,
        *,
        founder_id: UUID,
        product_id: UUID,
        lock: bool = False,
    ) -> Product | None:
        product = await session.get(Product, product_id, with_for_update=lock)
        if product is None or product.founder_id != founder_id or product.status != "approved":
            return None
        return cast(Product, product)

    async def schedule_product(
        self,
        session: Any,
        *,
        product: Product,
        expected_version: int,
        launch_date: date,
        launch_at: datetime,
        now: datetime,
    ) -> Product:
        assert product.version == expected_version
        statement = (
            update(Product)
            .where(Product.id == product.id, Product.version == expected_version)
            .values(status="scheduled", version=Product.version + 1, updated_at=now)
            .returning(Product)
        )
        return cast(Product, (await session.scalars(statement)).one())


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_concurrent_founder_requests_cannot_take_the_last_daily_slot() -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 17, 12, tzinfo=UTC)
        launch_date = date(2026, 10, 20)
        founder_id, product_ids = uuid4(), [uuid4(), uuid4(), uuid4()]
        database = Database.connect(os.environ["DATABASE_URL"])
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
                        created_at=now,
                        updated_at=now,
                    )
                )
                for product_id in product_ids:
                    await session.execute(
                        insert(Product).values(
                            id=product_id,
                            founder_id=founder_id,
                            status="approved" if product_id != product_ids[0] else "scheduled",
                            version=1,
                            name="Concurrency product",
                            pitch="An approved product",
                            description="Private description",
                            website_url="https://example.test/product",
                            website_key="https://example.test/product",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                fingerprint = hashlib.sha256(b"existing-slot").hexdigest()
                await session.execute(
                    insert(LaunchBooking).values(
                        id=uuid7(),
                        product_id=product_ids[0],
                        founder_id=founder_id,
                        launch_date=launch_date,
                        launch_at=datetime.combine(launch_date, datetime.min.time(), tzinfo=UTC),
                        state="scheduled",
                        idempotency_key="existing-slot",
                        request_fingerprint=fingerprint,
                        created_at=now,
                        closed_at=None,
                    )
                )
            service = LaunchBookingService(
                member_access=AuthAccessService(),
                product_access=cast(Any, _ProductPort()),
                repository=LaunchBookingRepository(),
                clock=lambda: now,
            )

            async def attempt(product_id: UUID, key: str) -> bool:
                try:
                    async with sessions() as session, session.begin():
                        await service.book(
                            session,
                            actor_id=founder_id,
                            product_id=product_id,
                            launch_date=launch_date,
                            expected_version=1,
                            idempotency_key=key,
                        )
                    return True
                except ValueError:
                    return False

            outcomes = await asyncio.gather(
                attempt(product_ids[1], "race-left"), attempt(product_ids[2], "race-right")
            )
            assert sum(outcomes) == 1
            async with sessions() as session:
                total = await LaunchBookingRepository().count_active(
                    session, founder_id=founder_id, launch_date=launch_date
                )
            assert total == 2
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(
                    delete(LaunchBooking).where(LaunchBooking.founder_id == founder_id)
                )
                await connection.execute(delete(Product).where(Product.id.in_(product_ids)))
                await connection.execute(delete(Account).where(Account.id == founder_id))
            await database.engine.dispose()

    asyncio.run(verify())
