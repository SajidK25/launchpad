"""PostgreSQL integration coverage for private founder drafts."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.modules.auth.models import Account
from app.modules.auth.staff import AuthAccessService
from app.modules.products.models import Product, ProductSubmission
from app.modules.products.policies import (
    ProductConflictError,
    ProductForbiddenError,
    ProductInfrastructureError,
    ProductNotFoundError,
    ProductQuotaError,
)
from app.modules.products.schemas import ProductContentInput
from app.modules.products.service import ProductDraft, ProductService
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.models import OutboxMessage
from app.shared.events.outbox import OutboxEvent, OutboxRepository
from conftest import IntegrationSettings
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _account(account_id: UUID, *, verified: bool = False) -> Account:
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


def _product_service() -> ProductService:
    codec = EmailPayloadCodec({"product-test": b"p" * 32}, "product-test")
    return ProductService(
        member_access=AuthAccessService(),
        outbox_repository=OutboxRepository(),
        payload_codec=codec,
        clock=lambda: datetime(2026, 9, 29, tzinfo=UTC),
    )


class _FailAfterOutboxWrite:
    def __init__(self) -> None:
        self.product_ids: list[UUID] = []

    async def add(self, session: AsyncSession, event: OutboxEvent) -> UUID:
        await OutboxRepository().add(session, event)
        self.product_ids.append(event.aggregate_id)
        raise RuntimeError("simulated outbox failure")


async def _cleanup_products(
    sessions: async_sessionmaker[AsyncSession], *, product_ids: list[UUID], account_ids: list[UUID]
) -> None:
    async with sessions() as session, session.begin():
        if product_ids:
            await session.execute(
                delete(OutboxMessage).where(OutboxMessage.aggregate_id.in_(product_ids))
            )
            await session.execute(delete(Product).where(Product.id.in_(product_ids)))
        if account_ids:
            await session.execute(delete(Account).where(Account.id.in_(account_ids)))


def test_unverified_founder_can_create_and_only_owner_can_reopen_draft(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        product_id = uuid4()
        owner_id, other_id = uuid4(), uuid4()
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add_all([_account(owner_id), _account(other_id)])

            service = _product_service()
            async with sessions() as session, session.begin():
                created = await service.create_draft(session, actor_id=owner_id)
                product_id = created.id
                assert created.founder_id == owner_id
                assert created.status == "draft"
                assert created.version == 0

            async with sessions() as session:
                reopened = await service.get_draft(
                    session, actor_id=owner_id, product_id=product_id
                )
                assert reopened.id == product_id
                assert reopened.founder_id == owner_id
                assert reopened.content.name is None
                pending = await session.scalar(
                    select(func.count())
                    .select_from(ProductSubmission)
                    .where(ProductSubmission.product_id == product_id)
                )
                event_types = list(
                    await session.scalars(
                        select(OutboxMessage.event_type).where(
                            OutboxMessage.aggregate_id == product_id
                        )
                    )
                )
            assert pending == 0
            assert event_types == ["product.created.v1"]

            async with sessions() as session:
                try:
                    await service.get_draft(session, actor_id=other_id, product_id=product_id)
                except ProductNotFoundError:
                    pass
                else:
                    raise AssertionError("a different member loaded a private draft")
        finally:
            if "sessions" in locals():
                await _cleanup_products(
                    sessions, product_ids=[product_id], account_ids=[owner_id, other_id]
                )
            await database.close()

    asyncio.run(verify())


def test_stale_edit_cannot_replace_a_newer_saved_draft(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        founder_id, product_id = uuid4(), uuid4()
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add(_account(founder_id))
            service = _product_service()
            async with sessions() as session, session.begin():
                draft = await service.create_draft(session, actor_id=founder_id)
                product_id = draft.id
            async with sessions() as session, session.begin():
                saved = await service.save_draft(
                    session,
                    actor_id=founder_id,
                    product_id=product_id,
                    expected_version=0,
                    content=ProductContentInput(name="Newer saved name"),
                )
                assert saved.version == 1

            with pytest.raises(ProductConflictError):
                async with sessions() as session, session.begin():
                    await service.save_draft(
                        session,
                        actor_id=founder_id,
                        product_id=product_id,
                        expected_version=0,
                        content=ProductContentInput(name="Stale edit"),
                    )

            async with sessions() as session:
                latest = await service.get_draft(
                    session, actor_id=founder_id, product_id=product_id
                )
                events = list(
                    await session.scalars(
                        select(OutboxMessage.event_type)
                        .where(OutboxMessage.aggregate_id == product_id)
                        .order_by(OutboxMessage.available_at, OutboxMessage.id)
                    )
                )
            assert latest.content.name == "Newer saved name"
            assert latest.version == 1
            assert events.count("product.created.v1") == 1
            assert events.count("product.saved.v1") == 1
        finally:
            if "sessions" in locals():
                await _cleanup_products(
                    sessions, product_ids=[product_id], account_ids=[founder_id]
                )
            await database.close()

    asyncio.run(verify())


def test_suspension_blocks_draft_creation_and_editing(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        founder_id, product_id = uuid4(), uuid4()
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add(_account(founder_id))
            service = _product_service()
            async with sessions() as session, session.begin():
                draft = await service.create_draft(session, actor_id=founder_id)
                product_id = draft.id
            async with sessions() as session, session.begin():
                await session.execute(
                    update(Account)
                    .where(Account.id == founder_id)
                    .values(suspended_at=datetime.now(UTC))
                )

            with pytest.raises(ProductForbiddenError):
                async with sessions() as session, session.begin():
                    await service.create_draft(session, actor_id=founder_id)
            with pytest.raises(ProductForbiddenError):
                async with sessions() as session, session.begin():
                    await service.save_draft(
                        session,
                        actor_id=founder_id,
                        product_id=product_id,
                        expected_version=0,
                        content=ProductContentInput(name="Blocked edit"),
                    )

            async with sessions() as session:
                latest = await service.get_draft(
                    session, actor_id=founder_id, product_id=product_id
                )
                product_count = await session.scalar(
                    select(func.count())
                    .select_from(Product)
                    .where(Product.founder_id == founder_id)
                )
                event_count = await session.scalar(
                    select(func.count())
                    .select_from(OutboxMessage)
                    .where(OutboxMessage.aggregate_id == product_id)
                )
            assert latest.content.name is None
            assert latest.version == 0
            assert product_count == 1
            assert event_count == 1
        finally:
            if "sessions" in locals():
                await _cleanup_products(
                    sessions, product_ids=[product_id], account_ids=[founder_id]
                )
            await database.close()

    asyncio.run(verify())


def test_ten_draft_limit_holds_under_concurrent_creation(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        founder_id = uuid4()
        product_ids: list[UUID] = []
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add(_account(founder_id))
            service = _product_service()
            for _ in range(9):
                async with sessions() as session, session.begin():
                    draft = await service.create_draft(session, actor_id=founder_id)
                    product_ids.append(draft.id)

            barrier = asyncio.Barrier(2)

            async def create_racing_draft() -> ProductDraft:
                async with sessions() as session, session.begin():
                    await barrier.wait()
                    return await service.create_draft(session, actor_id=founder_id)

            outcomes = await asyncio.gather(
                create_racing_draft(), create_racing_draft(), return_exceptions=True
            )
            created = [outcome for outcome in outcomes if not isinstance(outcome, Exception)]
            rejected = [outcome for outcome in outcomes if isinstance(outcome, ProductQuotaError)]
            assert len(created) == 1
            assert len(rejected) == 1
            product_ids.append(created[0].id)

            async with sessions() as session:
                count = await session.scalar(
                    select(func.count())
                    .select_from(Product)
                    .where(Product.founder_id == founder_id, Product.status == "draft")
                )
            assert count == 10
        finally:
            if "sessions" in locals():
                await _cleanup_products(sessions, product_ids=product_ids, account_ids=[founder_id])
            await database.close()

    asyncio.run(verify())


def test_failed_outbox_write_rolls_back_draft_and_saved_content(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        founder_id = uuid4()
        product_ids: list[UUID] = []
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add(_account(founder_id))

            failing_outbox = _FailAfterOutboxWrite()
            broken_service = ProductService(
                member_access=AuthAccessService(),
                outbox_repository=failing_outbox,
                payload_codec=EmailPayloadCodec({"product-test": b"p" * 32}, "product-test"),
            )
            with pytest.raises(ProductInfrastructureError):
                async with sessions() as session, session.begin():
                    await broken_service.create_draft(session, actor_id=founder_id)
            assert len(failing_outbox.product_ids) == 1
            failed_create_id = failing_outbox.product_ids.pop()
            async with sessions() as session:
                failed_products = await session.scalar(
                    select(func.count()).select_from(Product).where(Product.id == failed_create_id)
                )
                failed_events = await session.scalar(
                    select(func.count())
                    .select_from(OutboxMessage)
                    .where(OutboxMessage.aggregate_id == failed_create_id)
                )
            assert failed_products == 0
            assert failed_events == 0

            service = _product_service()
            async with sessions() as session, session.begin():
                draft = await service.create_draft(session, actor_id=founder_id)
                product_ids.append(draft.id)
            with pytest.raises(ProductInfrastructureError):
                async with sessions() as session, session.begin():
                    await broken_service.save_draft(
                        session,
                        actor_id=founder_id,
                        product_id=product_ids[0],
                        expected_version=0,
                        content=ProductContentInput(name="Must roll back"),
                    )
            assert failing_outbox.product_ids == [product_ids[0]]
            async with sessions() as session:
                current = await service.get_draft(
                    session, actor_id=founder_id, product_id=product_ids[0]
                )
                event_count = await session.scalar(
                    select(func.count())
                    .select_from(OutboxMessage)
                    .where(OutboxMessage.aggregate_id == product_ids[0])
                )
            assert current.content.name is None
            assert current.version == 0
            assert event_count == 1
        finally:
            if "sessions" in locals():
                await _cleanup_products(
                    sessions,
                    product_ids=product_ids,
                    account_ids=[founder_id],
                )
            await database.close()

    asyncio.run(verify())
