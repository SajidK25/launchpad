"""TDD coverage for app-signed private product media access."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import cast
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Table, delete, insert, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.models import Account
from app.modules.auth.staff import AuthAccessService
from app.modules.products.models import Product, ProductAsset, ProductSubmission
from app.modules.products.policies import (
    ProductInfrastructureError,
    ProductNotFoundError,
    create_product_media_signature,
    verify_product_media_signature,
)
from app.modules.products.service import ProductService
from app.shared.db.database import Database
from app.shared.events.outbox import OutboxRepository
from app.shared.storage.objects import ObjectOperationError

ACCOUNT_TABLE = cast(Table, Account.__table__)
PRODUCT_TABLE = cast(Table, Product.__table__)
PRODUCT_ASSET_TABLE = cast(Table, ProductAsset.__table__)
PRODUCT_SUBMISSION_TABLE = cast(Table, ProductSubmission.__table__)


def test_media_signature_binds_session_path_and_expiry() -> None:
    path = f"/api/v1/products/{uuid4()}/assets/{uuid4()}"
    expires = int(datetime(2026, 9, 30, 12, tzinfo=UTC).timestamp())
    signature = create_product_media_signature("opaque-session-a", path, expires)

    now = datetime(2026, 9, 30, 11, 59, tzinfo=UTC)
    assert verify_product_media_signature("opaque-session-a", path, expires, signature, now=now)
    assert not verify_product_media_signature("opaque-session-b", path, expires, signature, now=now)
    assert not verify_product_media_signature(
        "opaque-session-a", f"{path}/changed", expires, signature, now=now
    )
    assert not verify_product_media_signature(
        "opaque-session-a", path, expires + 1, signature, now=now
    )
    assert not verify_product_media_signature("opaque-session-a", path, expires, "invalid", now=now)


def test_media_signature_rejects_expired_or_unbounded_expiry() -> None:
    path = f"/api/v1/products/{uuid4()}/assets/{uuid4()}"
    now = datetime(2026, 9, 30, 12, tzinfo=UTC)
    expires = int(now.timestamp())
    signature = create_product_media_signature("opaque-session", path, expires)

    assert not verify_product_media_signature("opaque-session", path, expires, signature, now=now)
    future = expires + 301
    future_signature = create_product_media_signature("opaque-session", path, future)
    assert not verify_product_media_signature(
        "opaque-session", path, future, future_signature, now=now
    )


class _Codec:
    def encode(self, payload: Mapping[str, object]) -> tuple[str, bytes]:
        del payload
        return "test", b"test"


class _Storage:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.reads: list[tuple[UUID, UUID, str]] = []

    async def get_product_private(
        self, *, account_id: UUID, product_id: UUID, object_key: str
    ) -> tuple[bytes, str | None]:
        self.reads.append((account_id, product_id, object_key))
        if self.error is not None:
            raise self.error
        return b"private-image", "image/png"


def _account(account_id: UUID, *, role: str = "member", verified: bool = True) -> Account:
    now = datetime.now(UTC)
    return Account(
        id=account_id,
        email_display=f"{account_id}@example.test",
        email_key=f"{account_id}@example.test",
        password_hash="test-placeholder",
        verified_at=now if verified else None,
        role=role,
        created_at=now,
        updated_at=now,
    )


def _service(now: datetime) -> ProductService:
    return ProductService(
        member_access=AuthAccessService(),
        outbox_repository=OutboxRepository(),
        payload_codec=_Codec(),
        clock=lambda: now,
    )


async def _seed_private_product(
    sessions: async_sessionmaker[AsyncSession],
    *,
    owner_id: UUID,
    product_id: UUID,
    asset_id: UUID,
    staff_id: UUID | None = None,
    other_id: UUID | None = None,
) -> None:
    now = datetime.now(UTC)
    async with sessions() as session, session.begin():
        accounts = [_account(owner_id)]
        if staff_id is not None:
            accounts.append(_account(staff_id, role="reviewer"))
        if other_id is not None:
            accounts.append(_account(other_id))
        for account in accounts:
            await session.execute(
                insert(ACCOUNT_TABLE).values(
                    id=account.id,
                    email_display=account.email_display,
                    email_key=account.email_key,
                    password_hash=account.password_hash,
                    verified_at=account.verified_at,
                    role=account.role,
                    suspended_at=account.suspended_at,
                    session_epoch=0,
                    created_at=account.created_at,
                    updated_at=account.updated_at,
                )
            )
        await session.execute(
            insert(PRODUCT_TABLE).values(
                id=product_id,
                founder_id=owner_id,
                status="submitted",
                version=1,
                name="Private launch",
                pitch="A private launch pitch",
                description="A complete but unpublished product description.",
                website_url="https://example.test",
                website_key="example.test",
                created_at=now,
                updated_at=now,
            )
        )
        await session.execute(
            insert(PRODUCT_ASSET_TABLE).values(
                id=asset_id,
                product_id=product_id,
                kind="logo",
                state="clean",
                staging_key=f"product-staging/{owner_id.hex}/{product_id.hex}/{asset_id.hex}",
                clean_key=f"product-clean/{owner_id.hex}/{product_id.hex}/{asset_id.hex}",
                media_type="image/png",
                byte_count=128,
                position=None,
                expires_at=now + timedelta(minutes=5),
                attached_at=now,
            )
        )
        await session.execute(
            insert(PRODUCT_SUBMISSION_TABLE).values(
                id=uuid4(),
                product_id=product_id,
                state="pending",
                submitted_at=now,
                closed_at=None,
                product_version=1,
            )
        )


async def _delete_seed(
    sessions: async_sessionmaker[AsyncSession], product_id: UUID, account_ids: set[UUID]
) -> None:
    async with sessions() as session, session.begin():
        await session.execute(
            delete(PRODUCT_ASSET_TABLE).where(ProductAsset.product_id == product_id)
        )
        await session.execute(
            delete(PRODUCT_SUBMISSION_TABLE).where(ProductSubmission.product_id == product_id)
        )
        await session.execute(delete(PRODUCT_TABLE).where(Product.id == product_id))
        await session.execute(delete(ACCOUNT_TABLE).where(Account.id.in_(account_ids)))


def test_owner_and_pending_staff_can_read_attached_clean_media() -> None:
    async def verify() -> None:
        database = Database.connect(os.environ["DATABASE_URL"])
        owner_id, staff_id = uuid4(), uuid4()
        product_id, asset_id = uuid4(), uuid4()
        now = datetime.now(UTC).replace(microsecond=0)
        storage = _Storage()
        sessions = async_sessionmaker(database.engine, expire_on_commit=False)
        try:
            await database.ensure_compatible()
            await _seed_private_product(
                sessions,
                owner_id=owner_id,
                staff_id=staff_id,
                product_id=product_id,
                asset_id=asset_id,
            )
            service = _service(now)
            path = f"/api/v1/products/{product_id}/assets/{asset_id}"
            async with sessions() as session, session.begin():
                media_url = await service.sign_private_asset_url(
                    session,
                    actor_id=owner_id,
                    session_secret="owner-session",
                    product_id=product_id,
                    asset_id=asset_id,
                )
            parsed_url = urlsplit(media_url)
            assert parsed_url.path == path
            assert set(parse_qs(parsed_url.query)) == {"expires", "signature"}
            expiry = int(now.timestamp()) + 300
            signature = create_product_media_signature("owner-session", path, expiry)
            async with sessions() as session, session.begin():
                media = await service.read_private_asset(
                    session,
                    actor_id=owner_id,
                    session_secret="owner-session",
                    product_id=product_id,
                    asset_id=asset_id,
                    expires_at=expiry,
                    signature=signature,
                    storage=storage,
                )
            assert (media.body, media.media_type) == (b"private-image", "image/png")
            assert storage.reads == [
                (
                    owner_id,
                    product_id,
                    f"product-clean/{owner_id.hex}/{product_id.hex}/{asset_id.hex}",
                )
            ]

            staff_signature = create_product_media_signature("staff-session", path, expiry)
            async with sessions() as session, session.begin():
                staff_media = await service.read_private_asset(
                    session,
                    actor_id=staff_id,
                    session_secret="staff-session",
                    product_id=product_id,
                    asset_id=asset_id,
                    expires_at=expiry,
                    signature=staff_signature,
                    storage=storage,
                )
            assert staff_media.body == b"private-image"

            for values in (
                {"suspended_at": now},
                {"suspended_at": None, "verified_at": None},
            ):
                async with sessions() as session, session.begin():
                    await session.execute(
                        update(ACCOUNT_TABLE).where(Account.id == staff_id).values(**values)
                    )
                with pytest.raises(ProductNotFoundError):
                    async with sessions() as session, session.begin():
                        await service.read_private_asset(
                            session,
                            actor_id=staff_id,
                            session_secret="staff-session",
                            product_id=product_id,
                            asset_id=asset_id,
                            expires_at=expiry,
                            signature=staff_signature,
                            storage=storage,
                        )
                assert len(storage.reads) == 2

        finally:
            await _delete_seed(sessions, product_id, {owner_id, staff_id})
            await database.close()

    asyncio.run(verify())


def test_staff_media_access_is_revoked_when_submission_is_withdrawn() -> None:
    async def verify() -> None:
        database = Database.connect(os.environ["DATABASE_URL"])
        owner_id, staff_id = uuid4(), uuid4()
        product_id, asset_id = uuid4(), uuid4()
        now = datetime.now(UTC).replace(microsecond=0)
        storage = _Storage()
        sessions = async_sessionmaker(database.engine, expire_on_commit=False)
        try:
            await database.ensure_compatible()
            await _seed_private_product(
                sessions,
                owner_id=owner_id,
                staff_id=staff_id,
                product_id=product_id,
                asset_id=asset_id,
            )
            service = _service(now)
            path = f"/api/v1/products/{product_id}/assets/{asset_id}"
            expiry = int(now.timestamp()) + 300
            signature = create_product_media_signature("staff-session", path, expiry)
            async with sessions() as session, session.begin():
                await session.execute(
                    update(PRODUCT_SUBMISSION_TABLE)
                    .where(ProductSubmission.product_id == product_id)
                    .values(state="withdrawn", closed_at=now)
                )
                await session.execute(
                    update(Product).where(Product.id == product_id).values(status="draft")
                )
            with pytest.raises(ProductNotFoundError):
                async with sessions() as session, session.begin():
                    await service.read_private_asset(
                        session,
                        actor_id=staff_id,
                        session_secret="staff-session",
                        product_id=product_id,
                        asset_id=asset_id,
                        expires_at=expiry,
                        signature=signature,
                        storage=storage,
                    )
            assert storage.reads == []
        finally:
            await _delete_seed(sessions, product_id, {owner_id, staff_id})
            await database.close()

    asyncio.run(verify())


def test_other_members_detached_assets_and_storage_failures_are_safe() -> None:
    async def verify() -> None:
        database = Database.connect(os.environ["DATABASE_URL"])
        owner_id, other_id = uuid4(), uuid4()
        product_id, asset_id = uuid4(), uuid4()
        now = datetime.now(UTC).replace(microsecond=0)
        sessions = async_sessionmaker(database.engine, expire_on_commit=False)
        try:
            await database.ensure_compatible()
            await _seed_private_product(
                sessions,
                owner_id=owner_id,
                other_id=other_id,
                product_id=product_id,
                asset_id=asset_id,
            )
            service = _service(now)
            storage = _Storage()
            path = f"/api/v1/products/{product_id}/assets/{asset_id}"
            expiry = int(now.timestamp()) + 300
            signature = create_product_media_signature("other-session", path, expiry)
            with pytest.raises(ProductNotFoundError):
                async with sessions() as session, session.begin():
                    await service.read_private_asset(
                        session,
                        actor_id=other_id,
                        session_secret="other-session",
                        product_id=product_id,
                        asset_id=asset_id,
                        expires_at=expiry,
                        signature=signature,
                        storage=storage,
                    )
            assert storage.reads == []

            async with sessions() as session, session.begin():
                await session.execute(
                    update(PRODUCT_ASSET_TABLE)
                    .where(ProductAsset.id == asset_id)
                    .values(state="detached", attached_at=None)
                )
            with pytest.raises(ProductNotFoundError):
                async with sessions() as session, session.begin():
                    await service.read_private_asset(
                        session,
                        actor_id=owner_id,
                        session_secret="owner-session",
                        product_id=product_id,
                        asset_id=asset_id,
                        expires_at=expiry,
                        signature=create_product_media_signature("owner-session", path, expiry),
                        storage=storage,
                    )
            assert storage.reads == []

            async with sessions() as session, session.begin():
                await session.execute(
                    update(PRODUCT_ASSET_TABLE)
                    .where(ProductAsset.id == asset_id)
                    .values(state="clean", attached_at=now)
                )
            failing_storage = _Storage(ObjectOperationError("storage outage"))
            with pytest.raises(ProductInfrastructureError):
                async with sessions() as session, session.begin():
                    await service.read_private_asset(
                        session,
                        actor_id=owner_id,
                        session_secret="owner-session",
                        product_id=product_id,
                        asset_id=asset_id,
                        expires_at=expiry,
                        signature=create_product_media_signature("owner-session", path, expiry),
                        storage=failing_storage,
                    )
            async with sessions() as session, session.begin():
                await session.execute(delete(PRODUCT_TABLE).where(Product.id == product_id))
            with pytest.raises(ProductNotFoundError):
                async with sessions() as session, session.begin():
                    await service.read_private_asset(
                        session,
                        actor_id=owner_id,
                        session_secret="owner-session",
                        product_id=product_id,
                        asset_id=asset_id,
                        expires_at=expiry,
                        signature=create_product_media_signature("owner-session", path, expiry),
                        storage=storage,
                    )
        finally:
            await _delete_seed(sessions, product_id, {owner_id, other_id})
            await database.close()

    asyncio.run(verify())
