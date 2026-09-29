"""PostgreSQL coverage for transactional product submission periods."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.modules.auth.models import Account
from app.modules.auth.staff import AuthAccessService
from app.modules.products.models import (
    Product,
    ProductAsset,
    ProductSubmission,
    ProductTopic,
    Topic,
)
from app.modules.products.policies import (
    ProductConflictError,
    ProductForbiddenError,
    ProductInfrastructureError,
)
from app.modules.products.schemas import ProductContentInput
from app.modules.products.service import ProductService, ProductValidationError
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.models import OutboxMessage
from app.shared.events.outbox import OutboxEvent, OutboxRepository
from conftest import IntegrationSettings
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _account(account_id: UUID, *, verified: bool = True) -> Account:
    now = datetime.now(UTC)
    return Account(
        id=account_id,
        email_display=f"{account_id}@example.test",
        email_key=f"{account_id}@example.test",
        password_hash="integration-only-placeholder",
        verified_at=now if verified else None,
        created_at=now,
        updated_at=now,
    )


def _service(now: datetime) -> ProductService:
    return ProductService(
        member_access=AuthAccessService(),
        outbox_repository=OutboxRepository(),
        payload_codec=EmailPayloadCodec({"product-test": b"p" * 32}, "product-test"),
        clock=lambda: now,
    )


class _FailAfterOutboxWrite:
    async def add(self, session: AsyncSession, event: OutboxEvent) -> UUID:
        await OutboxRepository().add(session, event)
        raise RuntimeError("simulated event failure")


async def _clean(
    sessions: async_sessionmaker,
    *,
    product_ids: list[UUID],
    account_ids: list[UUID],
    topic_ids: list[UUID],
) -> None:
    async with sessions() as session, session.begin():
        if product_ids:
            await session.execute(
                delete(OutboxMessage).where(OutboxMessage.aggregate_id.in_(product_ids))
            )
            await session.execute(delete(Product).where(Product.id.in_(product_ids)))
        if topic_ids:
            await session.execute(delete(Topic).where(Topic.id.in_(topic_ids)))
        if account_ids:
            await session.execute(delete(Account).where(Account.id.in_(account_ids)))


async def _make_complete(
    sessions: async_sessionmaker,
    *,
    service: ProductService,
    founder_id: UUID,
    product_id: UUID,
    topic_id: UUID,
    clock: datetime,
) -> None:
    async with sessions() as session, session.begin():
        await service.save_draft(
            session,
            actor_id=founder_id,
            product_id=product_id,
            expected_version=0,
            content=ProductContentInput(
                name="Product",
                pitch="A useful product",
                description="A detailed description.",
                website_url="https://example.test/product",
            ),
        )
        session.add(
            ProductAsset(
                id=uuid4(),
                product_id=product_id,
                kind="logo",
                state="clean",
                staging_key=f"products/{founder_id}/{product_id}/logo-stage",
                clean_key=f"products/{founder_id}/{product_id}/logo-clean",
                media_type="image/png",
                byte_count=100,
                position=None,
                expires_at=None,
                attached_at=clock,
            )
        )
        session.add(
            ProductAsset(
                id=uuid4(),
                product_id=product_id,
                kind="screenshot",
                state="clean",
                staging_key=f"products/{founder_id}/{product_id}/shot-stage",
                clean_key=f"products/{founder_id}/{product_id}/shot-clean",
                media_type="image/png",
                byte_count=100,
                position=1,
                expires_at=None,
                attached_at=clock,
            )
        )
        session.add(ProductTopic(product_id=product_id, topic_id=topic_id, position=1))


def test_submission_requires_complete_verified_draft_and_is_idempotent(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        now = datetime(2026, 9, 29, tzinfo=UTC)
        database = Database.connect(integration_settings_fixture.database_url)
        founder_id, unverified_id, topic_id = uuid4(), uuid4(), uuid4()
        product_ids: list[UUID] = []
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add_all([_account(founder_id), _account(unverified_id, verified=False)])
                session.add(Topic(id=topic_id, display_name="Tools", name_key=f"t{topic_id.hex}"))
            service = _service(now)
            async with sessions() as session, session.begin():
                incomplete = await service.create_draft(session, actor_id=founder_id)
                product_ids.append(incomplete.id)
            with pytest.raises(ProductValidationError):
                async with sessions() as session, session.begin():
                    await service.submit_draft(
                        session,
                        actor_id=founder_id,
                        product_id=incomplete.id,
                        expected_version=0,
                    )

            async with sessions() as session, session.begin():
                unverified = await service.create_draft(session, actor_id=unverified_id)
                product_ids.append(unverified.id)
                await service.save_draft(
                    session,
                    actor_id=unverified_id,
                    product_id=unverified.id,
                    expected_version=0,
                    content=ProductContentInput(
                        name="Product",
                        pitch="A useful product",
                        description="A detailed description.",
                        website_url="https://example.test/unverified",
                    ),
                )
                session.add_all(
                    [
                        ProductAsset(
                            id=uuid4(),
                            product_id=unverified.id,
                            kind="logo",
                            state="clean",
                            staging_key=f"products/{unverified_id}/{unverified.id}/logo-stage",
                            clean_key=f"products/{unverified_id}/{unverified.id}/logo-clean",
                            media_type="image/png",
                            byte_count=100,
                            position=None,
                            expires_at=None,
                            attached_at=now,
                        ),
                        ProductAsset(
                            id=uuid4(),
                            product_id=unverified.id,
                            kind="screenshot",
                            state="clean",
                            staging_key=f"products/{unverified_id}/{unverified.id}/shot-stage",
                            clean_key=f"products/{unverified_id}/{unverified.id}/shot-clean",
                            media_type="image/png",
                            byte_count=100,
                            position=1,
                            expires_at=None,
                            attached_at=now,
                        ),
                        ProductTopic(product_id=unverified.id, topic_id=topic_id, position=1),
                    ]
                )
            with pytest.raises(ProductForbiddenError):
                async with sessions() as session, session.begin():
                    await service.submit_draft(
                        session,
                        actor_id=unverified_id,
                        product_id=unverified.id,
                        expected_version=1,
                    )

            await _make_complete(
                sessions,
                service=service,
                founder_id=founder_id,
                product_id=incomplete.id,
                topic_id=topic_id,
                clock=now,
            )
            with pytest.raises(ProductConflictError):
                async with sessions() as session, session.begin():
                    await service.submit_draft(
                        session,
                        actor_id=founder_id,
                        product_id=incomplete.id,
                        expected_version=0,
                    )
            async with sessions() as session, session.begin():
                first = await service.submit_draft(
                    session,
                    actor_id=founder_id,
                    product_id=incomplete.id,
                    expected_version=1,
                )
            async with sessions() as session, session.begin():
                retry = await service.submit_draft(
                    session,
                    actor_id=founder_id,
                    product_id=incomplete.id,
                    expected_version=1,
                )
            assert first.id == retry.id
            assert first.submitted_at == retry.submitted_at == now
            assert first.product_version == retry.product_version == 2
            async with sessions() as session:
                period_count = await session.scalar(
                    select(func.count())
                    .select_from(ProductSubmission)
                    .where(ProductSubmission.product_id == incomplete.id)
                )
                submitted = await session.scalar(select(Product).where(Product.id == incomplete.id))
            assert period_count == 1
            assert submitted.status == "submitted"
            assert submitted.version == 2
        finally:
            if "sessions" in locals():
                await _clean(
                    sessions,
                    product_ids=product_ids,
                    account_ids=[founder_id, unverified_id],
                    topic_ids=[topic_id],
                )
            await database.close()

    asyncio.run(verify())


def test_failed_submission_outbox_write_rolls_back_product_and_period(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        now = datetime(2026, 9, 29, tzinfo=UTC)
        database = Database.connect(integration_settings_fixture.database_url)
        founder_id, topic_id = uuid4(), uuid4()
        product_ids: list[UUID] = []
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add(_account(founder_id))
                session.add(Topic(id=topic_id, display_name="Tools", name_key=f"t{topic_id.hex}"))
            service = _service(now)
            async with sessions() as session, session.begin():
                draft = await service.create_draft(session, actor_id=founder_id)
                product_ids.append(draft.id)
            await _make_complete(
                sessions,
                service=service,
                founder_id=founder_id,
                product_id=draft.id,
                topic_id=topic_id,
                clock=now,
            )
            broken_service = ProductService(
                member_access=AuthAccessService(),
                outbox_repository=_FailAfterOutboxWrite(),
                payload_codec=EmailPayloadCodec({"product-test": b"p" * 32}, "product-test"),
                clock=lambda: now,
            )
            with pytest.raises(ProductInfrastructureError):
                async with sessions() as session, session.begin():
                    await broken_service.submit_draft(
                        session,
                        actor_id=founder_id,
                        product_id=draft.id,
                        expected_version=1,
                    )
            async with sessions() as session:
                current = await session.scalar(select(Product).where(Product.id == draft.id))
                period_count = await session.scalar(
                    select(func.count())
                    .select_from(ProductSubmission)
                    .where(ProductSubmission.product_id == draft.id)
                )
                event_count = await session.scalar(
                    select(func.count())
                    .select_from(OutboxMessage)
                    .where(
                        OutboxMessage.aggregate_id == draft.id,
                        OutboxMessage.event_type == "product.submitted.v1",
                    )
                )
            assert current.status == "draft"
            assert current.version == 1
            assert period_count == 0
            assert event_count == 0
        finally:
            if "sessions" in locals():
                await _clean(
                    sessions,
                    product_ids=product_ids,
                    account_ids=[founder_id],
                    topic_ids=[topic_id],
                )
            await database.close()

    asyncio.run(verify())


def test_pending_edit_preserves_queue_time_and_withdrawal_invalidates_period(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        first_time = datetime(2026, 9, 29, tzinfo=UTC)
        second_time = datetime(2026, 9, 30, tzinfo=UTC)
        database = Database.connect(integration_settings_fixture.database_url)
        founder_id, topic_id = uuid4(), uuid4()
        product_ids: list[UUID] = []
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add(_account(founder_id))
                session.add(Topic(id=topic_id, display_name="Tools", name_key=f"t{topic_id.hex}"))
            service = _service(first_time)
            async with sessions() as session, session.begin():
                draft = await service.create_draft(session, actor_id=founder_id)
                product_ids.append(draft.id)
            await _make_complete(
                sessions,
                service=service,
                founder_id=founder_id,
                product_id=draft.id,
                topic_id=topic_id,
                clock=first_time,
            )
            async with sessions() as session, session.begin():
                period = await service.submit_draft(
                    session,
                    actor_id=founder_id,
                    product_id=draft.id,
                    expected_version=1,
                )
            service = _service(second_time)
            async with sessions() as session, session.begin():
                edited = await service.save_pending(
                    session,
                    actor_id=founder_id,
                    product_id=draft.id,
                    expected_version=2,
                    content=ProductContentInput(pitch="An improved pitch"),
                )
            assert edited.version == 3
            with pytest.raises(ProductValidationError):
                async with sessions() as session, session.begin():
                    await service.save_pending(
                        session,
                        actor_id=founder_id,
                        product_id=draft.id,
                        expected_version=3,
                        content=ProductContentInput(name=None),
                    )
            async with sessions() as session:
                period_after_edit = await session.get(ProductSubmission, period.id)
                current = await session.scalar(select(Product).where(Product.id == draft.id))
            assert period_after_edit.submitted_at == first_time
            assert period_after_edit.product_version == 3
            assert current.name == "Product"

            async with sessions() as session, session.begin():
                await session.execute(
                    update(Account).where(Account.id == founder_id).values(suspended_at=second_time)
                )
            async with sessions() as session, session.begin():
                withdrawn = await service.withdraw_submission(
                    session,
                    actor_id=founder_id,
                    product_id=draft.id,
                    submission_id=period.id,
                    expected_version=3,
                )
            assert withdrawn.status == "draft"
            assert withdrawn.version == 4
            async with sessions() as session:
                closed = await session.get(ProductSubmission, period.id)
                current = await session.scalar(select(Product).where(Product.id == draft.id))
            assert closed.state == "withdrawn"
            assert closed.closed_at == second_time
            assert current.status == "draft"
            assert current.version == 4
        finally:
            if "sessions" in locals():
                await _clean(
                    sessions,
                    product_ids=product_ids,
                    account_ids=[founder_id],
                    topic_ids=[topic_id],
                )
            await database.close()

    asyncio.run(verify())


def test_pending_limit_serializes_submitters_and_resubmit_gets_new_queue_period(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        first_time = datetime(2026, 9, 29, tzinfo=UTC)
        next_time = datetime(2026, 9, 30, tzinfo=UTC)
        database = Database.connect(integration_settings_fixture.database_url)
        founder_id, topic_id = uuid4(), uuid4()
        product_ids: list[UUID] = []
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add(_account(founder_id))
                session.add(Topic(id=topic_id, display_name="Tools", name_key=f"t{topic_id.hex}"))
            service = _service(first_time)
            for _ in range(4):
                async with sessions() as session, session.begin():
                    draft = await service.create_draft(session, actor_id=founder_id)
                    product_ids.append(draft.id)
                await _make_complete(
                    sessions,
                    service=service,
                    founder_id=founder_id,
                    product_id=draft.id,
                    topic_id=topic_id,
                    clock=first_time,
                )
            initial_periods = []
            for product_id in product_ids[:2]:
                async with sessions() as session, session.begin():
                    initial_periods.append(
                        await service.submit_draft(
                            session,
                            actor_id=founder_id,
                            product_id=product_id,
                            expected_version=1,
                        )
                    )

            barrier = asyncio.Barrier(2)

            async def submit(product_id: UUID) -> object:
                async with sessions() as session, session.begin():
                    await barrier.wait()
                    return await service.submit_draft(
                        session,
                        actor_id=founder_id,
                        product_id=product_id,
                        expected_version=1,
                    )

            outcomes = await asyncio.gather(
                submit(product_ids[2]), submit(product_ids[3]), return_exceptions=True
            )
            accepted = [item for item in outcomes if not isinstance(item, Exception)]
            rejected = [item for item in outcomes if isinstance(item, Exception)]
            assert len(accepted) == 1
            assert len(rejected) == 1
            assert isinstance(rejected[0], Exception)
            assert rejected[0].__class__.__name__ == "ProductQuotaError"

            old_period = initial_periods[0]
            async with sessions() as session, session.begin():
                withdrawn = await service.withdraw_submission(
                    session,
                    actor_id=founder_id,
                    product_id=old_period.product_id,
                    submission_id=old_period.id,
                    expected_version=2,
                )
            assert withdrawn.version == 3
            service = _service(next_time)
            async with sessions() as session, session.begin():
                replacement = await service.submit_draft(
                    session,
                    actor_id=founder_id,
                    product_id=old_period.product_id,
                    expected_version=3,
                )
            assert replacement.id != old_period.id
            assert replacement.submitted_at == next_time
            assert (old_period.id, old_period.product_version) != (
                replacement.id,
                replacement.product_version,
            )
            async with sessions() as session:
                periods = list(
                    await session.scalars(
                        select(ProductSubmission)
                        .where(ProductSubmission.product_id == old_period.product_id)
                        .order_by(ProductSubmission.submitted_at, ProductSubmission.id)
                    )
                )
                pending_count = await session.scalar(
                    select(func.count())
                    .select_from(ProductSubmission)
                    .join(Product, Product.id == ProductSubmission.product_id)
                    .where(
                        Product.founder_id == founder_id,
                        ProductSubmission.state == "pending",
                    )
                )
            assert len(periods) == 2
            assert periods[0].state == "withdrawn"
            assert periods[1].state == "pending"
            assert pending_count == 3
        finally:
            if "sessions" in locals():
                await _clean(
                    sessions,
                    product_ids=product_ids,
                    account_ids=[founder_id],
                    topic_ids=[topic_id],
                )
            await database.close()

    asyncio.run(verify())
