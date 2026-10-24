"""PostgreSQL checks for product-owned launch lifecycle and public projection."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.auth.models import Account
from app.modules.auth.staff import AuthAccessService
from app.modules.products.models import Product
from app.modules.products.policies import ProductInfrastructureError
from app.modules.products.schemas import ProductLaunchEditInput
from app.modules.products.service import ProductService
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.models import OutboxMessage


def _service(now: datetime) -> ProductService:
    return ProductService(
        member_access=AuthAccessService(),
        payload_codec=EmailPayloadCodec({"launch-test": b"l" * 32}, "launch-test"),
        clock=lambda: now,
    )


class _FailingOutbox:
    async def add(self, _session: Any, _event: Any) -> UUID:
        raise RuntimeError("outbox insert failed")


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_schedule_publish_replay_failure_recovery_projection_and_limited_edits() -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 17, 22, tzinfo=UTC)
        founder_id, product_id, late_id, suspended_id = (uuid4() for _ in range(4))
        database = Database.connect(os.environ["DATABASE_URL"])
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                for account_id in (founder_id, product_id, late_id, suspended_id):
                    await session.execute(
                        insert(Account).values(
                            id=account_id,
                            email_display=f"{account_id}@example.test",
                            email_key=f"{account_id}@example.test",
                            password_hash="integration-only-placeholder",
                            verified_at=now,
                            role="member",
                            suspended_at=now if account_id == suspended_id else None,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                for item_id, owner_id, status in (
                    (product_id, founder_id, "approved"),
                    (late_id, founder_id, "scheduled"),
                    (suspended_id, suspended_id, "scheduled"),
                ):
                    await session.execute(
                        insert(Product).values(
                            id=item_id,
                            founder_id=owner_id,
                            status=status,
                            version=3,
                            name="Lifecycle product",
                            pitch="A concise pitch",
                            description="Original description",
                            website_url="https://example.test/original",
                            website_key="https://example.test/original",
                            created_at=now,
                            updated_at=now,
                        )
                    )

            service = _service(now)
            launch_at = datetime(2026, 10, 18, tzinfo=UTC)
            async with sessions() as session, session.begin():
                approved = await service.get_approved_product(
                    session, founder_id=founder_id, product_id=product_id, lock=True
                )
                assert approved is not None
                scheduled = await service.schedule_product(
                    session,
                    product=approved,
                    expected_version=3,
                    launch_date=launch_at.date(),
                    launch_at=launch_at,
                    now=now,
                )
                assert scheduled.status == "scheduled" and scheduled.version == 4
                assert await service.public_projection(session, product_id=product_id) is None
                with pytest.raises(ValueError):
                    await service.edit_launched_product(
                        session,
                        actor_id=founder_id,
                        product_id=product_id,
                        command=ProductLaunchEditInput(version=4, description="too early"),
                    )

            failing_service = ProductService(
                member_access=AuthAccessService(),
                outbox_repository=cast(Any, _FailingOutbox()),
                payload_codec=EmailPayloadCodec({"launch-test": b"l" * 32}, "launch-test"),
                clock=lambda: now,
            )
            with pytest.raises(ProductInfrastructureError):
                async with sessions() as session, session.begin():
                    await failing_service.publish_scheduled_product(
                        session, product_id=product_id, launch_at=launch_at, now=launch_at
                    )
            async with sessions() as session:
                still_scheduled = await session.scalar(
                    select(Product).where(Product.id == product_id)
                )
                assert still_scheduled is not None and still_scheduled.status == "scheduled"

            async with sessions() as session, session.begin():
                launched = await service.publish_scheduled_product(
                    session, product_id=product_id, launch_at=launch_at, now=launch_at
                )
                assert launched.status == "launched" and launched.version == 5
                assert launched.launched_at == launch_at
                launch_events = list(
                    (
                        await session.scalars(
                            select(OutboxMessage).where(
                                OutboxMessage.event_type == "product.launched.v1",
                                OutboxMessage.aggregate_id == product_id,
                            )
                        )
                    ).all()
                )
                assert len(launch_events) == 1
                payload = EmailPayloadCodec({"launch-test": b"l" * 32}, "launch-test").decode(
                    launch_events[0].key_id, launch_events[0].encrypted_payload or b""
                )
                assert payload == {
                    "product_id": str(product_id),
                    "owner_account_id": str(founder_id),
                    "launch_date": launch_at.date().isoformat(),
                }
            async with sessions() as session, session.begin():
                replay = await service.publish_scheduled_product(
                    session, product_id=product_id, launch_at=launch_at, now=launch_at
                )
                assert replay.status == "launched" and replay.version == 5
                replayed_event_count = await session.scalar(
                    select(func.count())
                    .select_from(OutboxMessage)
                    .where(
                        OutboxMessage.event_type == "product.launched.v1",
                        OutboxMessage.aggregate_id == product_id,
                    )
                )
                assert replayed_event_count == 1
                public = await service.public_projection(session, product_id=product_id)
                assert public is not None
                assert public.name == "Lifecycle product"
                assert not hasattr(public, "founder_id")
                edited = await service.edit_launched_product(
                    session,
                    actor_id=founder_id,
                    product_id=product_id,
                    command=ProductLaunchEditInput(
                        version=5,
                        description="Updated after launch",
                        website_url="https://example.test/updated",
                    ),
                )
                assert edited.version == 6
                with pytest.raises(ValueError):
                    ProductLaunchEditInput.model_validate({"version": 6, "name": "renamed"})

            late_launch_at = launch_at + timedelta(days=1)
            async with sessions() as session, session.begin():
                missed = await service.publish_scheduled_product(
                    session,
                    product_id=late_id,
                    launch_at=launch_at,
                    now=late_launch_at,
                )
                assert missed.status == "approved"
                assert missed.launch_failure_reason == "missed_day"
                blocked = await service.publish_scheduled_product(
                    session,
                    product_id=suspended_id,
                    launch_at=launch_at,
                    now=launch_at,
                )
                assert blocked.status == "approved"
                assert blocked.launch_failure_reason == "suspension_blocked"
                assert await service.public_projection(session, product_id=late_id) is None
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(
                    delete(Product).where(Product.id.in_([product_id, late_id, suspended_id]))
                )
                await connection.execute(
                    delete(Account).where(
                        Account.id.in_([founder_id, product_id, late_id, suspended_id])
                    )
                )
            await database.engine.dispose()

    asyncio.run(verify())
