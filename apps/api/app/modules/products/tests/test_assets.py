"""TDD coverage for bounded product asset contracts and lifecycle."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.models import Account
from app.modules.auth.staff import AuthAccessService
from app.modules.products.models import Product, ProductAsset
from app.modules.products.policies import (
    ProductConflictError,
    ProductForbiddenError,
    ProductNotFoundError,
)
from app.modules.products.repository import ProductRepository
from app.modules.products.schemas import ProductAssetIntentInput
from app.modules.products.service import ProductService
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.models import OutboxMessage
from app.shared.events.outbox import OutboxRepository
from app.shared.storage.objects import CleanPhoto, ObjectValidationError, StagingUpload


@pytest.mark.parametrize("size", [0, 5 * 1024 * 1024 + 1])
def test_asset_intent_rejects_out_of_bounds_sizes(size: int) -> None:
    with pytest.raises(ValidationError):
        ProductAssetIntentInput(kind="logo", content_type="image/png", size=size)


@pytest.mark.parametrize("content_type", ["image/svg+xml", "image/gif", "text/plain"])
def test_asset_intent_rejects_unsupported_image_types(content_type: str) -> None:
    with pytest.raises(ValidationError):
        ProductAssetIntentInput.model_validate(
            {"kind": "screenshot", "content_type": content_type, "size": 128}
        )


def test_asset_intent_accepts_supported_maximum_upload() -> None:
    value = ProductAssetIntentInput(
        kind="screenshot", content_type="image/webp", size=5 * 1024 * 1024
    )

    assert value.size == 5 * 1024 * 1024


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


class _Storage:
    def __init__(self) -> None:
        self.finalize_error: Exception | None = None
        self.uploads: list[tuple[UUID, UUID, UUID]] = []

    async def create_product_staging_upload(
        self,
        *,
        account_id: UUID,
        product_id: UUID,
        asset_id: UUID,
        content_type: str,
        size: int,
        expires_in: int = 300,
    ) -> StagingUpload:
        self.uploads.append((account_id, product_id, asset_id))
        key = f"product-staging/{account_id.hex}/{product_id.hex}/{asset_id.hex}"
        return StagingUpload(key, "http://minio/upload", {"key": key}, expires_in)

    async def finalize_product_staging(
        self,
        *,
        account_id: UUID,
        product_id: UUID,
        asset_id: UUID,
        declared_content_type: str | None = None,
    ) -> CleanPhoto:
        if self.finalize_error is not None:
            raise self.finalize_error
        key = f"product-clean/{account_id.hex}/{product_id.hex}/{asset_id.hex}"
        return CleanPhoto(key, "image/png", 80)


def _service(now: datetime) -> ProductService:
    return ProductService(
        member_access=AuthAccessService(),
        outbox_repository=OutboxRepository(),
        payload_codec=EmailPayloadCodec({"asset-test": b"a" * 32}, "asset-test"),
        clock=lambda: now,
    )


def test_asset_intents_are_owner_scoped_and_schedule_encrypted_cleanup() -> None:
    async def verify() -> None:
        database = Database.connect(os.environ["DATABASE_URL"])
        owner_id, other_id = uuid4(), uuid4()
        product_id: UUID | None = None
        now = datetime(2026, 9, 30, tzinfo=UTC)
        service = _service(now)
        storage = _Storage()
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add_all([_account(owner_id), _account(other_id)])
            async with sessions() as session, session.begin():
                product_id = (await service.create_draft(session, actor_id=owner_id)).id
            async with sessions() as session, session.begin():
                result = await service.create_asset_intent(
                    session,
                    actor_id=owner_id,
                    product_id=product_id,
                    intent=ProductAssetIntentInput(kind="logo", content_type="image/png", size=100),
                    storage=storage,
                )
            assert result.asset.state == "pending"
            assert not hasattr(result.asset, "staging_key")
            assert storage.uploads == [(owner_id, product_id, result.asset.id)]
            async with sessions() as session:
                cleanup = await session.scalar(
                    select(OutboxMessage).where(
                        OutboxMessage.aggregate_id == product_id,
                        OutboxMessage.event_type == "product.media_purge.v1",
                    )
                )
                assert cleanup is not None
                assert cleanup.available_at == datetime(2026, 10, 1, 0, 5, tzinfo=UTC)
                assert cleanup.encrypted_payload is not None
                assert b"product-staging" not in cleanup.encrypted_payload
            with pytest.raises(ProductNotFoundError):
                async with sessions() as session, session.begin():
                    await service.create_asset_intent(
                        session,
                        actor_id=other_id,
                        product_id=product_id,
                        intent=ProductAssetIntentInput(
                            kind="logo", content_type="image/png", size=100
                        ),
                        storage=storage,
                    )
            async with sessions() as session, session.begin():
                await session.execute(
                    update(Account).where(Account.id == owner_id).values(suspended_at=now)
                )
            with pytest.raises(ProductForbiddenError):
                async with sessions() as session, session.begin():
                    await service.create_asset_intent(
                        session,
                        actor_id=owner_id,
                        product_id=product_id,
                        intent=ProductAssetIntentInput(
                            kind="logo", content_type="image/png", size=100
                        ),
                        storage=storage,
                    )
        finally:
            if product_id is not None:
                async with async_sessionmaker(database.engine)() as session, session.begin():
                    await session.execute(
                        delete(OutboxMessage).where(OutboxMessage.aggregate_id == product_id)
                    )
                    await session.execute(delete(Product).where(Product.id == product_id))
                    await session.execute(
                        delete(Account).where(Account.id.in_([owner_id, other_id]))
                    )
            await database.close()

    asyncio.run(verify())


def test_only_clean_owned_assets_can_be_attached_and_promotion_has_durable_cleanup() -> None:
    async def verify() -> None:
        database = Database.connect(os.environ["DATABASE_URL"])
        owner_id, other_id = uuid4(), uuid4()
        product_ids: list[UUID] = []
        now = datetime(2026, 9, 30, tzinfo=UTC)
        service = _service(now)
        storage = _Storage()
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add_all([_account(owner_id), _account(other_id)])
            async with sessions() as session, session.begin():
                product_id = (await service.create_draft(session, actor_id=owner_id)).id
                other_product_id = (await service.create_draft(session, actor_id=other_id)).id
                product_ids.extend([product_id, other_product_id])
            async with sessions() as session, session.begin():
                logo = await service.create_asset_intent(
                    session,
                    actor_id=owner_id,
                    product_id=product_id,
                    intent=ProductAssetIntentInput(kind="logo", content_type="image/png", size=100),
                    storage=storage,
                )
                second_logo = await service.create_asset_intent(
                    session,
                    actor_id=owner_id,
                    product_id=product_id,
                    intent=ProductAssetIntentInput(kind="logo", content_type="image/png", size=100),
                    storage=storage,
                )
                screenshot = await service.create_asset_intent(
                    session,
                    actor_id=owner_id,
                    product_id=product_id,
                    intent=ProductAssetIntentInput(
                        kind="screenshot", content_type="image/png", size=100
                    ),
                    storage=storage,
                )
                foreign = await service.create_asset_intent(
                    session,
                    actor_id=other_id,
                    product_id=other_product_id,
                    intent=ProductAssetIntentInput(kind="logo", content_type="image/png", size=100),
                    storage=storage,
                )
                invalid = await service.create_asset_intent(
                    session,
                    actor_id=owner_id,
                    product_id=product_id,
                    intent=ProductAssetIntentInput(kind="logo", content_type="image/png", size=100),
                    storage=storage,
                )
            with pytest.raises(ProductConflictError):
                async with sessions() as session, session.begin():
                    await service.attach_assets(
                        session,
                        actor_id=owner_id,
                        product_id=product_id,
                        expected_version=0,
                        logo_asset_id=logo.asset.id,
                        screenshot_asset_ids=(second_logo.asset.id,),
                    )
            with pytest.raises(ProductConflictError):
                async with sessions() as session, session.begin():
                    await service.attach_assets(
                        session,
                        actor_id=owner_id,
                        product_id=product_id,
                        expected_version=0,
                        logo_asset_id=logo.asset.id,
                        screenshot_asset_ids=tuple(uuid4() for _ in range(11)),
                    )
            with pytest.raises(ProductNotFoundError):
                async with sessions() as session, session.begin():
                    await service.attach_assets(
                        session,
                        actor_id=owner_id,
                        product_id=product_id,
                        expected_version=0,
                        logo_asset_id=foreign.asset.id,
                        screenshot_asset_ids=(),
                    )
            with pytest.raises(ProductConflictError):
                async with sessions() as session, session.begin():
                    await service.attach_assets(
                        session,
                        actor_id=owner_id,
                        product_id=product_id,
                        expected_version=0,
                        logo_asset_id=logo.asset.id,
                        screenshot_asset_ids=(screenshot.asset.id,),
                    )
            storage.finalize_error = ObjectValidationError("invalid image bytes")
            async with sessions() as session, session.begin():
                failed_asset = await service.complete_asset(
                    session,
                    actor_id=owner_id,
                    product_id=product_id,
                    asset_id=invalid.asset.id,
                    storage=storage,
                )
                assert failed_asset.state == "failed"
            storage.finalize_error = None
            with pytest.raises(ProductConflictError):
                async with sessions() as session, session.begin():
                    await service.attach_assets(
                        session,
                        actor_id=owner_id,
                        product_id=product_id,
                        expected_version=0,
                        logo_asset_id=invalid.asset.id,
                        screenshot_asset_ids=(),
                    )
            async with sessions() as session, session.begin():
                completed_logo = await service.complete_asset(
                    session,
                    actor_id=owner_id,
                    product_id=product_id,
                    asset_id=logo.asset.id,
                    storage=storage,
                )
                completed_screenshot = await service.complete_asset(
                    session,
                    actor_id=owner_id,
                    product_id=product_id,
                    asset_id=screenshot.asset.id,
                    storage=storage,
                )
                assert completed_logo.state == completed_screenshot.state == "clean"
            async with sessions() as session, session.begin():
                saved = await service.attach_assets(
                    session,
                    actor_id=owner_id,
                    product_id=product_id,
                    expected_version=0,
                    logo_asset_id=logo.asset.id,
                    screenshot_asset_ids=(screenshot.asset.id,),
                )
                assert saved.version == 1
            async with sessions() as session:
                attached = list(
                    (
                        await session.scalars(
                            select(ProductAsset).where(
                                ProductAsset.product_id == product_id,
                                ProductAsset.attached_at.is_not(None),
                            )
                        )
                    ).all()
                )
                assert {(asset.kind, asset.position) for asset in attached} == {
                    ("logo", None),
                    ("screenshot", 1),
                }
            async with sessions() as session, session.begin():
                await service.complete_asset(
                    session,
                    actor_id=owner_id,
                    product_id=product_id,
                    asset_id=second_logo.asset.id,
                    storage=storage,
                )
            async with sessions() as session, session.begin():
                replaced = await service.attach_assets(
                    session,
                    actor_id=owner_id,
                    product_id=product_id,
                    expected_version=1,
                    logo_asset_id=second_logo.asset.id,
                    screenshot_asset_ids=(screenshot.asset.id,),
                )
                assert replaced.version == 2
            async with sessions() as session:
                old_logo = await session.get(ProductAsset, logo.asset.id)
                detached_cleanup = await session.scalar(
                    select(OutboxMessage).where(
                        OutboxMessage.aggregate_id == product_id,
                        OutboxMessage.event_type == "product.media_purge.v1",
                        OutboxMessage.available_at == datetime(2026, 10, 1, tzinfo=UTC),
                    )
                )
                assert old_logo is not None and old_logo.state == "detached"
                assert detached_cleanup is not None

            class FailingAssetRepository(ProductRepository):
                async def mark_asset_clean(
                    self, session: AsyncSession, **kwargs: Any
                ) -> ProductAsset:
                    raise RuntimeError("simulated database failure after storage promotion")

            failing_service = ProductService(
                member_access=AuthAccessService(),
                outbox_repository=OutboxRepository(),
                payload_codec=EmailPayloadCodec({"asset-test": b"a" * 32}, "asset-test"),
                repository=FailingAssetRepository(),
                clock=lambda: now,
            )
            async with sessions() as session, session.begin():
                orphan_candidate = await service.create_asset_intent(
                    session,
                    actor_id=owner_id,
                    product_id=product_id,
                    intent=ProductAssetIntentInput(
                        kind="screenshot", content_type="image/png", size=100
                    ),
                    storage=storage,
                )
            with pytest.raises(RuntimeError, match="simulated database failure"):
                async with sessions() as session, session.begin():
                    await failing_service.complete_asset(
                        session,
                        actor_id=owner_id,
                        product_id=product_id,
                        asset_id=orphan_candidate.asset.id,
                        storage=storage,
                    )
            async with sessions() as session:
                cleanup = await session.scalar(
                    select(OutboxMessage).where(
                        OutboxMessage.aggregate_id == product_id,
                        OutboxMessage.event_type == "product.media_purge.v1",
                    )
                )
                pending = await session.scalar(
                    select(ProductAsset).where(ProductAsset.id == orphan_candidate.asset.id)
                )
                assert cleanup is not None
                assert pending is not None and pending.state == "pending"
        finally:
            async with async_sessionmaker(database.engine)() as session, session.begin():
                await session.execute(
                    delete(OutboxMessage).where(OutboxMessage.aggregate_id.in_(product_ids))
                )
                await session.execute(delete(Product).where(Product.id.in_(product_ids)))
                await session.execute(delete(Account).where(Account.id.in_([owner_id, other_id])))
            await database.close()

    asyncio.run(verify())
