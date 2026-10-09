"""TDD coverage for bounded product asset contracts and lifecycle."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.models import Account
from app.modules.auth.staff import AccountState, AuthAccessService
from app.modules.products.models import Product, ProductAsset
from app.modules.products.policies import (
    ProductConflictError,
    ProductForbiddenError,
    ProductInfrastructureError,
    ProductNotFoundError,
    ProductQuotaError,
)
from app.modules.products.repository import ProductRepository
from app.modules.products.schemas import ProductAssetIntentInput
from app.modules.products.service import ProductService, ProductValidationError
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.models import OutboxMessage
from app.shared.events.outbox import OutboxRepository
from app.shared.storage.objects import (
    CleanPhoto,
    ObjectOperationError,
    ObjectValidationError,
    StagingUpload,
)


@pytest.mark.anyio
@pytest.mark.parametrize("storage_failure", [False, True])
async def test_product_transfer_locks_and_preserves_pending_asset_on_storage_failure(
    storage_failure: bool,
) -> None:
    owner_id, product_id, asset_id = uuid4(), uuid4(), uuid4()
    now = datetime(2026, 10, 1, tzinfo=UTC)
    product = SimpleNamespace(id=product_id, founder_id=owner_id, status="draft")
    asset = SimpleNamespace(
        id=asset_id,
        product_id=product_id,
        state="pending",
        staging_key=f"product-staging/{owner_id.hex}/{product_id.hex}/{asset_id.hex}",
        media_type="image/png",
        byte_count=64,
        expires_at=now.replace(minute=5),
    )

    class Access:
        async def current_account(self, session: Any, account_id: UUID, *, lock: bool = False):
            assert lock is True
            return AccountState(account_id, True, "member", None)

    class Session:
        def begin_nested(self) -> Session:
            return self

        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *args: object) -> None:
            return None

    class Repository:
        lock_order: list[str]

        def __init__(self) -> None:
            self.lock_order = []

        async def get_owned_product(self, session: Any, **values: object):
            self.lock_order.append("product")
            assert values["lock"] is True
            return product

        async def get_asset(self, session: Any, **values: object):
            self.lock_order.append("asset")
            assert values["lock"] is True
            return asset

    class Storage:
        writes: list[dict[str, object]]

        def __init__(self) -> None:
            self.writes = []

        async def put_staging(self, **values: object) -> None:
            self.writes.append(values)
            if storage_failure:
                raise ObjectOperationError("storage unavailable")

    repository = Repository()
    storage = Storage()
    service = ProductService(
        member_access=Access(),
        repository=repository,
        payload_codec=EmailPayloadCodec({"asset-test": b"a" * 32}, "asset-test"),
        clock=lambda: now,
    )

    if storage_failure:
        with pytest.raises(ProductInfrastructureError):
            await service.transfer_asset(
                Session(),
                actor_id=owner_id,
                product_id=product_id,
                asset_id=asset_id,
                body=b"bounded image bytes",
                content_type="image/png",
                storage=storage,
            )
    else:
        await service.transfer_asset(
            Session(),
            actor_id=owner_id,
            product_id=product_id,
            asset_id=asset_id,
            body=b"bounded image bytes",
            content_type="image/png",
            storage=storage,
        )

    assert repository.lock_order == ["product", "asset"]
    assert asset.state == "pending"
    assert storage.writes == [
        {
            "object_key": asset.staging_key,
            "body": b"bounded image bytes",
            "content_type": "image/png",
        }
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "invalid_state",
    ["foreign_owner", "submitted", "absent_asset", "expired", "clean", "wrong_type", "oversized"],
)
async def test_product_transfer_refuses_ineligible_or_mismatched_intents(
    invalid_state: str,
) -> None:
    owner_id, product_id, asset_id = uuid4(), uuid4(), uuid4()
    now = datetime(2026, 10, 1, tzinfo=UTC)
    product = SimpleNamespace(
        id=product_id,
        founder_id=uuid4() if invalid_state == "foreign_owner" else owner_id,
        status="submitted" if invalid_state == "submitted" else "draft",
    )
    asset = SimpleNamespace(
        id=asset_id,
        product_id=product_id,
        state="clean" if invalid_state == "clean" else "pending",
        staging_key=f"product-staging/{owner_id.hex}/{product_id.hex}/{asset_id.hex}",
        media_type="image/png",
        byte_count=8 if invalid_state == "oversized" else 64,
        expires_at=now.replace(minute=0) if invalid_state == "expired" else now.replace(minute=5),
    )

    class Access:
        async def current_account(self, session: Any, account_id: UUID, *, lock: bool = False):
            return AccountState(account_id, True, "member", None)

    class Session:
        def begin_nested(self) -> Session:
            return self

        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *args: object) -> None:
            return None

    class Repository:
        async def get_owned_product(self, session: Any, **values: object):
            return product

        async def get_asset(self, session: Any, **values: object):
            return None if invalid_state == "absent_asset" else asset

    class Storage:
        writes = 0

        async def put_staging(self, **values: object) -> None:
            self.writes += 1

    storage = Storage()
    service = ProductService(
        member_access=Access(),
        repository=Repository(),
        payload_codec=EmailPayloadCodec({"asset-test": b"a" * 32}, "asset-test"),
        clock=lambda: now,
    )
    body = b"123456789" if invalid_state == "oversized" else b"bounded image bytes"
    content_type = "image/jpeg" if invalid_state == "wrong_type" else "image/png"

    with pytest.raises((ProductConflictError, ProductNotFoundError, ProductValidationError)):
        await service.transfer_asset(
            Session(),
            actor_id=owner_id,
            product_id=product_id,
            asset_id=asset_id,
            body=body,
            content_type=content_type,
            storage=storage,
        )
    assert storage.writes == 0


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
            for _ in range(service.PENDING_ASSET_LIMIT - 1):
                async with sessions() as session, session.begin():
                    await service.create_asset_intent(
                        session,
                        actor_id=owner_id,
                        product_id=product_id,
                        intent=ProductAssetIntentInput(
                            kind="screenshot", content_type="image/png", size=100
                        ),
                        storage=storage,
                    )
            with pytest.raises(ProductQuotaError):
                async with sessions() as session, session.begin():
                    await service.create_asset_intent(
                        session,
                        actor_id=owner_id,
                        product_id=product_id,
                        intent=ProductAssetIntentInput(
                            kind="screenshot", content_type="image/png", size=100
                        ),
                        storage=storage,
                    )
            assert len(storage.uploads) == service.PENDING_ASSET_LIMIT
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
