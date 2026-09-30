"""PostgreSQL coverage for irreversible private-draft deletion and media purge."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.modules.auth.models import Account
from app.modules.auth.staff import AuthAccessService
from app.modules.products.models import Product, ProductAsset, ProductSubmission
from app.modules.products.policies import (
    ProductConflictError,
    ProductForbiddenError,
    ProductInfrastructureError,
    ProductNotFoundError,
)
from app.modules.products.service import ProductService
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.dispatcher import dispatch_due
from app.shared.events.models import OutboxMessage
from app.shared.events.outbox import OutboxEvent, OutboxRepository
from app.shared.storage.objects import ObjectOperationError
from conftest import IntegrationSettings
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _account(account_id: UUID) -> Account:
    now = datetime.now(UTC)
    return Account(
        id=account_id,
        email_display=f"{account_id}@example.test",
        email_key=f"{account_id}@example.test",
        password_hash="integration-only-placeholder",
        verified_at=None,
        created_at=now,
        updated_at=now,
    )


class _PreflightStorage:
    async def get_product_private(
        self, *, account_id: UUID, product_id: UUID, object_key: str
    ) -> tuple[bytes, str | None]:
        raise AssertionError("non-owner deletion must not access storage")


class _UnavailableStorage:
    async def get_product_private(
        self, *, account_id: UUID, product_id: UUID, object_key: str
    ) -> tuple[bytes, str | None]:
        raise ObjectOperationError("storage unavailable")


class _AvailableStorage:
    async def get_product_private(
        self, *, account_id: UUID, product_id: UUID, object_key: str
    ) -> tuple[bytes, str | None]:
        del account_id, product_id, object_key
        from app.shared.storage.objects import ObjectNotFound

        raise ObjectNotFound("probe key is absent")

    async def delete_product_private(
        self, *, account_id: UUID, product_id: UUID, object_key: str
    ) -> None:
        del account_id, product_id, object_key


class _RetryingStorage(_AvailableStorage):
    def __init__(self) -> None:
        self.delete_calls = 0
        self.deleted: list[str] = []

    async def delete_product_private(
        self, *, account_id: UUID, product_id: UUID, object_key: str
    ) -> None:
        del account_id, product_id
        self.delete_calls += 1
        if self.delete_calls == 1:
            raise ObjectOperationError("transient purge failure")
        self.deleted.append(object_key)


class _NoopSender:
    async def send(self, payload: dict[str, object], *, message_id: str) -> None:
        del payload, message_id


class _FailAfterOutboxWrite:
    def __init__(self) -> None:
        self.repository = OutboxRepository()

    async def add(self, session: AsyncSession, event: OutboxEvent) -> UUID:
        event_id = await self.repository.add(session, event)
        raise RuntimeError(f"simulated failure after event {event_id}")


def test_delete_rejects_another_founder_without_touching_product(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        founder_id, other_id = uuid4(), uuid4()
        product_id: UUID | None = None
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add_all([_account(founder_id), _account(other_id)])
            service = ProductService(
                member_access=AuthAccessService(),
                payload_codec=EmailPayloadCodec({"deletion-test": b"d" * 32}, "deletion-test"),
                clock=lambda: datetime(2026, 9, 30, tzinfo=UTC),
            )
            async with sessions() as session, session.begin():
                product_id = (await service.create_draft(session, actor_id=founder_id)).id

            with pytest.raises(ProductNotFoundError):
                async with sessions() as session, session.begin():
                    await service.delete_draft(
                        session,
                        actor_id=other_id,
                        product_id=product_id,
                        expected_version=0,
                        storage=_PreflightStorage(),
                    )

            async with sessions() as session:
                draft = await service.get_draft(session, actor_id=founder_id, product_id=product_id)
                assert draft.status == "draft"
        finally:
            if "sessions" in locals():
                async with sessions() as session, session.begin():
                    if product_id is not None:
                        await session.execute(
                            delete(OutboxMessage).where(OutboxMessage.aggregate_id == product_id)
                        )
                        await session.execute(delete(Product).where(Product.id == product_id))
                    await session.execute(
                        delete(Account).where(Account.id.in_([founder_id, other_id]))
                    )
            await database.close()

    asyncio.run(verify())


def test_storage_preflight_failure_preserves_draft_and_outbox(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        founder_id, product_id = uuid4(), None
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add(_account(founder_id))
            service = ProductService(
                member_access=AuthAccessService(),
                payload_codec=EmailPayloadCodec({"deletion-test": b"d" * 32}, "deletion-test"),
                clock=lambda: datetime(2026, 9, 30, tzinfo=UTC),
            )
            async with sessions() as session, session.begin():
                product_id = (await service.create_draft(session, actor_id=founder_id)).id

            with pytest.raises(ProductInfrastructureError):
                async with sessions() as session, session.begin():
                    await service.delete_draft(
                        session,
                        actor_id=founder_id,
                        product_id=product_id,
                        expected_version=0,
                        storage=_UnavailableStorage(),
                    )

            async with sessions() as session:
                draft = await service.get_draft(session, actor_id=founder_id, product_id=product_id)
                events = list(
                    await session.scalars(
                        select(OutboxMessage.event_type).where(
                            OutboxMessage.aggregate_id == product_id
                        )
                    )
                )
            assert draft.version == 0
            assert events == ["product.created.v1"]
        finally:
            if "sessions" in locals():
                async with sessions() as session, session.begin():
                    if product_id is not None:
                        await session.execute(
                            delete(OutboxMessage).where(OutboxMessage.aggregate_id == product_id)
                        )
                        await session.execute(delete(Product).where(Product.id == product_id))
                    await session.execute(delete(Account).where(Account.id == founder_id))
            await database.close()

    asyncio.run(verify())


def test_delete_revokes_draft_and_schedules_delayed_asset_purge(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        founder_id, product_id, asset_id = uuid4(), None, uuid4()
        now = datetime(2026, 9, 30, tzinfo=UTC)
        expires_at = datetime(2026, 10, 1, tzinfo=UTC)
        codec = EmailPayloadCodec({"deletion-test": b"d" * 32}, "deletion-test")
        outbox = OutboxRepository()
        storage = _RetryingStorage()
        service = ProductService(
            member_access=AuthAccessService(),
            outbox_repository=outbox,
            payload_codec=codec,
            event_storage=storage,
            clock=lambda: now,
        )
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add(_account(founder_id))
            async with sessions() as session, session.begin():
                product_id = (await service.create_draft(session, actor_id=founder_id)).id
                session.add(
                    ProductAsset(
                        id=asset_id,
                        product_id=product_id,
                        kind="logo",
                        state="pending",
                        staging_key=(
                            f"product-staging/{founder_id.hex}/{product_id.hex}/{asset_id.hex}"
                        ),
                        clean_key=None,
                        media_type="image/png",
                        byte_count=100,
                        position=None,
                        expires_at=expires_at,
                        attached_at=None,
                    )
                )

            async with sessions() as session, session.begin():
                await service.delete_draft(
                    session,
                    actor_id=founder_id,
                    product_id=product_id,
                    expected_version=0,
                    storage=storage,
                )

            async with sessions() as session:
                assert await session.get(Product, product_id) is None
                assert await session.get(ProductAsset, asset_id) is None
                assert await service.repository.count_drafts(session, founder_id=founder_id) == 0
                with pytest.raises(ProductNotFoundError):
                    await service.get_draft(session, actor_id=founder_id, product_id=product_id)
                events = list(
                    await session.scalars(
                        select(OutboxMessage)
                        .where(OutboxMessage.aggregate_id == product_id)
                        .order_by(OutboxMessage.available_at, OutboxMessage.id)
                    )
                )
            assert [event.event_type for event in events] == [
                "product.created.v1",
                "product.deleted.v1",
                "product.media_purge.v1",
            ]
            purge = next(event for event in events if event.event_type == "product.media_purge.v1")
            assert purge.available_at == expires_at + service.ASSET_CLEANUP_GRACE
            payload = codec.decode(purge.key_id, purge.encrypted_payload)
            assert payload == {
                "account_id": str(founder_id),
                "asset_id": str(asset_id),
                "clean_key": f"product-clean/{founder_id.hex}/{product_id.hex}/{asset_id.hex}",
                "product_id": str(product_id),
                "staging_key": f"product-staging/{founder_id.hex}/{product_id.hex}/{asset_id.hex}",
            }

            async with sessions() as session, session.begin():
                await dispatch_due(
                    session,
                    repository=outbox,
                    codec=codec,
                    sender=_NoopSender(),
                    product_handler=service,
                    now=now,
                )
            assert storage.delete_calls == 0

            async with sessions() as session, session.begin():
                await dispatch_due(
                    session,
                    repository=outbox,
                    codec=codec,
                    sender=_NoopSender(),
                    product_handler=service,
                    now=purge.available_at,
                )
                retry_event = await session.get(OutboxMessage, purge.id)
                assert retry_event is not None
                assert retry_event.state == "pending"
                assert retry_event.attempts == 1
                assert await session.get(Product, product_id) is None

            async with sessions() as session, session.begin():
                await dispatch_due(
                    session,
                    repository=outbox,
                    codec=codec,
                    sender=_NoopSender(),
                    product_handler=service,
                    now=purge.available_at + timedelta(seconds=30),
                )
                completed = await session.get(OutboxMessage, purge.id)
                assert completed is not None
                assert completed.state == "completed"
                assert completed.encrypted_payload is None
                assert await session.get(Product, product_id) is None
            assert storage.deleted == [
                f"product-staging/{founder_id.hex}/{product_id.hex}/{asset_id.hex}",
                f"product-clean/{founder_id.hex}/{product_id.hex}/{asset_id.hex}",
            ]
        finally:
            if "sessions" in locals():
                async with sessions() as session, session.begin():
                    if product_id is not None:
                        await session.execute(
                            delete(OutboxMessage).where(OutboxMessage.aggregate_id == product_id)
                        )
                        await session.execute(delete(Product).where(Product.id == product_id))
                    await session.execute(delete(Account).where(Account.id == founder_id))
            await database.close()

    asyncio.run(verify())


def test_submitted_product_cannot_be_deleted_as_a_draft(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        founder_id, product_id, submission_id = uuid4(), None, uuid4()
        now = datetime(2026, 9, 30, tzinfo=UTC)
        service = ProductService(
            member_access=AuthAccessService(),
            payload_codec=EmailPayloadCodec({"deletion-test": b"d" * 32}, "deletion-test"),
            clock=lambda: now,
        )
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add(_account(founder_id))
            async with sessions() as session, session.begin():
                product_id = (await service.create_draft(session, actor_id=founder_id)).id
                await session.execute(
                    update(Product)
                    .where(Product.id == product_id)
                    .values(
                        status="submitted",
                        name="Submitted product",
                        pitch="A valid short pitch",
                        description="Complete product description",
                        website_url="https://example.test",
                        website_key="https://example.test",
                    )
                )
                await session.execute(
                    insert(ProductSubmission).values(
                        id=submission_id,
                        product_id=product_id,
                        state="pending",
                        submitted_at=now,
                        closed_at=None,
                        product_version=0,
                    )
                )

            with pytest.raises(ProductConflictError):
                async with sessions() as session, session.begin():
                    await service.delete_draft(
                        session,
                        actor_id=founder_id,
                        product_id=product_id,
                        expected_version=0,
                        storage=_AvailableStorage(),
                    )

            async with sessions() as session:
                assert await session.get(Product, product_id) is not None
                assert await session.get(ProductSubmission, submission_id) is not None
        finally:
            if "sessions" in locals():
                async with sessions() as session, session.begin():
                    await session.execute(
                        delete(OutboxMessage).where(OutboxMessage.aggregate_id == product_id)
                    )
                    await session.execute(delete(Product).where(Product.id == product_id))
                    await session.execute(delete(Account).where(Account.id == founder_id))
            await database.close()

    asyncio.run(verify())


def test_suspended_founder_cannot_delete_existing_draft(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        founder_id, product_id = uuid4(), None
        now = datetime(2026, 9, 30, tzinfo=UTC)
        service = ProductService(
            member_access=AuthAccessService(),
            payload_codec=EmailPayloadCodec({"deletion-test": b"d" * 32}, "deletion-test"),
            clock=lambda: now,
        )
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add(_account(founder_id))
            async with sessions() as session, session.begin():
                product_id = (await service.create_draft(session, actor_id=founder_id)).id
            async with sessions() as session, session.begin():
                await session.execute(
                    update(Account).where(Account.id == founder_id).values(suspended_at=now)
                )

            with pytest.raises(ProductForbiddenError):
                async with sessions() as session, session.begin():
                    await service.delete_draft(
                        session,
                        actor_id=founder_id,
                        product_id=product_id,
                        expected_version=0,
                        storage=_AvailableStorage(),
                    )

            async with sessions() as session:
                assert await session.get(Product, product_id) is not None
        finally:
            if "sessions" in locals():
                async with sessions() as session, session.begin():
                    if product_id is not None:
                        await session.execute(
                            delete(OutboxMessage).where(OutboxMessage.aggregate_id == product_id)
                        )
                        await session.execute(delete(Product).where(Product.id == product_id))
                    await session.execute(delete(Account).where(Account.id == founder_id))
            await database.close()

    asyncio.run(verify())


def test_outbox_failure_rolls_back_product_and_asset_deletion(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        founder_id, product_id, asset_id = uuid4(), None, uuid4()
        now = datetime(2026, 9, 30, tzinfo=UTC)
        codec = EmailPayloadCodec({"deletion-test": b"d" * 32}, "deletion-test")
        service = ProductService(
            member_access=AuthAccessService(), payload_codec=codec, clock=lambda: now
        )
        failing_service = ProductService(
            member_access=AuthAccessService(),
            outbox_repository=_FailAfterOutboxWrite(),
            payload_codec=codec,
            clock=lambda: now,
        )
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add(_account(founder_id))
            async with sessions() as session, session.begin():
                product_id = (await service.create_draft(session, actor_id=founder_id)).id
                session.add(
                    ProductAsset(
                        id=asset_id,
                        product_id=product_id,
                        kind="logo",
                        state="pending",
                        staging_key=(
                            f"product-staging/{founder_id.hex}/{product_id.hex}/{asset_id.hex}"
                        ),
                        clean_key=None,
                        media_type="image/png",
                        byte_count=100,
                        position=None,
                        expires_at=now + timedelta(minutes=5),
                        attached_at=None,
                    )
                )

            with pytest.raises(ProductInfrastructureError):
                async with sessions() as session, session.begin():
                    await failing_service.delete_draft(
                        session,
                        actor_id=founder_id,
                        product_id=product_id,
                        expected_version=0,
                        storage=_AvailableStorage(),
                    )

            async with sessions() as session:
                assert await session.get(Product, product_id) is not None
                assert await session.get(ProductAsset, asset_id) is not None
                event_types = list(
                    await session.scalars(
                        select(OutboxMessage.event_type).where(
                            OutboxMessage.aggregate_id == product_id
                        )
                    )
                )
            assert event_types == ["product.created.v1"]
        finally:
            if "sessions" in locals():
                async with sessions() as session, session.begin():
                    if product_id is not None:
                        await session.execute(
                            delete(OutboxMessage).where(OutboxMessage.aggregate_id == product_id)
                        )
                        await session.execute(delete(Product).where(Product.id == product_id))
                    await session.execute(delete(Account).where(Account.id == founder_id))
            await database.close()

    asyncio.run(verify())
