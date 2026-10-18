"""Anonymous media reads must recheck launched status and attachment on each request."""

from __future__ import annotations

import asyncio
import base64
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.modules.auth.models import Account
from app.modules.products.models import Product, ProductAsset
from app.modules.products.routes import router
from app.shared.config.settings import Settings
from app.shared.db.database import Database
from app.shared.storage.objects import PrivateObjectStore


class _PublicStorage(PrivateObjectStore):
    def __init__(self) -> None:
        super().__init__(
            endpoint_url="https://objects.example.test",
            bucket_name="private",
            access_key_id="test",
            secret_access_key="test",
            client_factory=lambda: SimpleNamespace(),
        )
        self.reads: list[tuple[str, str, str]] = []

    async def get_product_private(
        self, *, account_id: object, product_id: object, object_key: str
    ) -> tuple[bytes, str | None]:
        self.reads.append((str(account_id), str(product_id), object_key))
        return b"published-image-bytes", "image/png"


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_public_media_requires_launched_product_and_attached_clean_asset() -> None:
    async def verify() -> None:
        database = Database.connect(os.environ["DATABASE_URL"])
        database.engine = create_async_engine(
            database.engine.url, poolclass=NullPool, pool_pre_ping=True
        )
        owner_id = uuid4()
        launched_id, approved_id, scheduled_id = uuid4(), uuid4(), uuid4()
        launched_asset_id, unattached_asset_id = uuid4(), uuid4()
        other_asset_id = uuid4()
        now = datetime.now(UTC).replace(microsecond=0)
        storage = _PublicStorage()
        settings = Settings(
            trusted_web_origins=("https://launchpad.example.test",),
            outbox_key_id="media-test",
            outbox_key=SecretStr(base64.b64encode(b"m" * 32).decode("ascii")),
        )
        app = FastAPI()
        app.include_router(
            router(
                settings=settings,
                database=database,
                redis=SimpleNamespace(),  # type: ignore[arg-type]
                storage=storage,
            )
        )
        sessions = async_sessionmaker(database.engine, expire_on_commit=False)
        try:
            await database.ensure_compatible()
            async with sessions() as session, session.begin():
                await session.execute(
                    insert(Account).values(
                        id=owner_id,
                        email_display=f"{owner_id}@example.test",
                        email_key=f"{owner_id}@example.test",
                        password_hash="integration-only-placeholder",
                        verified_at=now,
                        role="member",
                        suspended_at=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                for product_id, status in (
                    (launched_id, "launched"),
                    (approved_id, "approved"),
                    (scheduled_id, "scheduled"),
                ):
                    await session.execute(
                        insert(Product).values(
                            id=product_id,
                            founder_id=owner_id,
                            status=status,
                            version=1,
                            name="Private launch details",
                            pitch="Private pitch",
                            description="Private product description",
                            website_url="https://example.test",
                            website_key="example.test",
                            launched_at=now if status == "launched" else None,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                for asset_id, product_id, state, attached_at in (
                    (launched_asset_id, launched_id, "clean", now),
                    (unattached_asset_id, launched_id, "clean", None),
                    (other_asset_id, approved_id, "clean", now),
                ):
                    await session.execute(
                        insert(ProductAsset).values(
                            id=asset_id,
                            product_id=product_id,
                            kind="logo",
                            state=state,
                            staging_key=(
                                f"product-staging/{owner_id.hex}/{product_id.hex}/{asset_id.hex}"
                            ),
                            clean_key=(
                                f"product-clean/{owner_id.hex}/{product_id.hex}/{asset_id.hex}"
                            ),
                            media_type="image/png",
                            byte_count=128,
                            position=None,
                            expires_at=now,
                            attached_at=attached_at,
                        )
                    )

            with TestClient(app) as client:
                public_path = f"/api/v1/products/{launched_id}/assets/{launched_asset_id}/public"
                response = client.get(public_path)
                assert response.status_code == 200
                assert response.content == b"published-image-bytes"
                assert response.headers["content-type"] == "image/png"
                assert response.headers["cache-control"] == "no-store"
                assert response.headers["x-content-type-options"] == "nosniff"
                assert storage.reads == [
                    (
                        str(owner_id),
                        str(launched_id),
                        f"product-clean/{owner_id.hex}/{launched_id.hex}/{launched_asset_id.hex}",
                    )
                ]

                hidden_paths = (
                    f"/api/v1/products/{approved_id}/assets/{other_asset_id}/public",
                    f"/api/v1/products/{scheduled_id}/assets/{launched_asset_id}/public",
                    f"/api/v1/products/{launched_id}/assets/{unattached_asset_id}/public",
                    f"/api/v1/products/{launched_id}/assets/{uuid4()}/public",
                    f"/api/v1/products/{uuid4()}/assets/{launched_asset_id}/public",
                )
                for path in hidden_paths:
                    hidden = client.get(path)
                    assert hidden.status_code == 404
                    assert hidden.json() == {"detail": "product media unavailable"}
                assert len(storage.reads) == 1
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(
                    delete(ProductAsset).where(
                        ProductAsset.product_id.in_([launched_id, approved_id, scheduled_id])
                    )
                )
                await connection.execute(
                    delete(Product).where(Product.id.in_([launched_id, approved_id, scheduled_id]))
                )
                await connection.execute(delete(Account).where(Account.id == owner_id))
            await database.engine.dispose()

    asyncio.run(verify())
