"""Product-owned handlers for typed outbox work and private media purges."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from app.modules.auth.staff import AuthAccessService
from app.modules.products.repository import ProductRepository
from app.modules.products.service import ProductService
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.outbox import OutboxRepository, PermanentEventError
from app.shared.storage.objects import ObjectOperationError
from sqlalchemy.ext.asyncio import AsyncSession


class _Repository:
    def __init__(self, *, owner_id: UUID, asset: SimpleNamespace | None) -> None:
        self.product: SimpleNamespace | None = SimpleNamespace(founder_id=owner_id)
        self.asset = asset

    async def get_owned_product(
        self,
        _session: AsyncSession,
        *,
        product_id: UUID,
        founder_id: UUID,
        lock: bool,
    ) -> SimpleNamespace | None:
        del product_id, lock
        if self.product is not None and self.product.founder_id != founder_id:
            return None
        return self.product

    async def get_asset(
        self,
        _session: AsyncSession,
        *,
        product_id: UUID,
        asset_id: UUID,
        lock: bool,
    ) -> SimpleNamespace | None:
        del product_id, asset_id, lock
        return self.asset

    async def mark_asset_failed(
        self, _session: AsyncSession, *, asset: SimpleNamespace
    ) -> SimpleNamespace:
        asset.state = "failed"
        return asset


class _Storage:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.deleted: list[str] = []

    async def delete_product_private(
        self, *, account_id: UUID, product_id: UUID, object_key: str
    ) -> None:
        del account_id, product_id
        if self.fail:
            raise ObjectOperationError("storage unavailable")
        self.deleted.append(object_key)


def _service(repository: _Repository) -> ProductService:
    return ProductService(
        member_access=AuthAccessService(),
        outbox_repository=OutboxRepository(),
        payload_codec=EmailPayloadCodec({"event-test": b"e" * 32}, "event-test"),
        repository=cast(ProductRepository, repository),
    )


def _purge_event(*, account_id: UUID, product_id: UUID, asset_id: UUID) -> dict[str, object]:
    suffix = f"{account_id.hex}/{product_id.hex}/{asset_id.hex}"
    return {
        "account_id": str(account_id),
        "product_id": str(product_id),
        "asset_id": str(asset_id),
        "staging_key": f"product-staging/{suffix}",
        "clean_key": f"product-clean/{suffix}",
    }


def test_media_purge_keeps_attached_clean_object_and_removes_staging() -> None:
    async def verify() -> None:
        account_id, product_id, asset_id = uuid4(), uuid4(), uuid4()
        payload = _purge_event(account_id=account_id, product_id=product_id, asset_id=asset_id)
        clean_key = str(payload["clean_key"])
        asset = SimpleNamespace(
            state="clean",
            attached_at=datetime.now(UTC),
            clean_key=clean_key,
        )
        service = _service(_Repository(owner_id=account_id, asset=asset))
        storage = _Storage()

        await service.handle_outbox_event(
            cast(AsyncSession, object()),
            event_type="product.media_purge.v1",
            aggregate_id=product_id,
            payload=payload,
            storage=storage,
        )

        assert storage.deleted == [str(payload["staging_key"])]
        assert asset.state == "clean"

    asyncio.run(verify())


def test_media_purge_invalidates_unattached_asset_and_deletes_both_keys() -> None:
    async def verify() -> None:
        account_id, product_id, asset_id = uuid4(), uuid4(), uuid4()
        payload = _purge_event(account_id=account_id, product_id=product_id, asset_id=asset_id)
        asset = SimpleNamespace(state="clean", attached_at=None, clean_key=payload["clean_key"])
        service = _service(_Repository(owner_id=account_id, asset=asset))
        storage = _Storage()

        await service.handle_outbox_event(
            cast(AsyncSession, object()),
            event_type="product.media_purge.v1",
            aggregate_id=product_id,
            payload=payload,
            storage=storage,
        )

        assert asset.state == "failed"
        assert storage.deleted == [str(payload["staging_key"]), str(payload["clean_key"])]

    asyncio.run(verify())


def test_media_purge_after_product_deletion_is_idempotently_scoped() -> None:
    async def verify() -> None:
        account_id, product_id, asset_id = uuid4(), uuid4(), uuid4()
        payload = _purge_event(account_id=account_id, product_id=product_id, asset_id=asset_id)
        repository = _Repository(owner_id=account_id, asset=None)
        repository.product = None
        service = _service(repository)
        storage = _Storage()

        await service.handle_outbox_event(
            cast(AsyncSession, object()),
            event_type="product.media_purge.v1",
            aggregate_id=product_id,
            payload=payload,
            storage=storage,
        )

        assert storage.deleted == [str(payload["staging_key"]), str(payload["clean_key"])]

    asyncio.run(verify())


def test_product_state_event_is_acknowledged_without_storage_mutation() -> None:
    async def verify() -> None:
        service = _service(_Repository(owner_id=uuid4(), asset=None))
        storage = _Storage()

        await service.handle_outbox_event(
            cast(AsyncSession, object()),
            event_type="product.saved.v1",
            aggregate_id=uuid4(),
            payload={"product_id": str(uuid4())},
            storage=storage,
        )

        assert storage.deleted == []

    asyncio.run(verify())


def test_malformed_media_purge_is_permanent_and_never_deletes() -> None:
    async def verify() -> None:
        account_id, product_id, asset_id = uuid4(), uuid4(), uuid4()
        payload = _purge_event(account_id=account_id, product_id=product_id, asset_id=asset_id)
        payload["clean_key"] = "product-clean/someone-elses-object"
        service = _service(_Repository(owner_id=account_id, asset=None))
        storage = _Storage()

        with pytest.raises(PermanentEventError):
            await service.handle_outbox_event(
                cast(AsyncSession, object()),
                event_type="product.media_purge.v1",
                aggregate_id=product_id,
                payload=payload,
                storage=storage,
            )
        assert storage.deleted == []

    asyncio.run(verify())


def test_storage_failure_propagates_for_durable_retry() -> None:
    async def verify() -> None:
        account_id, product_id, asset_id = uuid4(), uuid4(), uuid4()
        payload = _purge_event(account_id=account_id, product_id=product_id, asset_id=asset_id)
        service = _service(_Repository(owner_id=account_id, asset=None))
        storage = _Storage(fail=True)

        with pytest.raises(ObjectOperationError):
            await service.handle_outbox_event(
                cast(AsyncSession, object()),
                event_type="product.media_purge.v1",
                aggregate_id=product_id,
                payload=payload,
                storage=storage,
            )

    asyncio.run(verify())
