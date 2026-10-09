"""HTTP checks for owner-only product commands and versioned topic saves."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.modules.auth.models import Account, Session
from app.modules.auth.sessions import SessionService, SignInResult
from app.modules.products.models import (
    Product,
    ProductAsset,
    ProductSubmission,
    ProductTopic,
    Topic,
)
from app.modules.products.routes import router
from app.shared.config.settings import load_settings
from app.shared.db.database import Database
from app.shared.events.models import OutboxMessage
from app.shared.security.passwords import hash_password
from app.shared.storage.objects import PrivateObjectStore
from conftest import IntegrationSettings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker


def test_product_http_commands_preserve_private_versions_topics_and_queue(
    integration_settings_fixture: IntegrationSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_settings()
    redis = Redis.from_url(integration_settings_fixture.redis_url)
    account_id, other_id = uuid4(), uuid4()
    password = "a secure product password!"
    names = [f"First {uuid4().hex[:8]}", f"Second {uuid4().hex[:8]}"]
    product_id: UUID | None = None

    async def prepare() -> tuple[SignInResult, SignInResult]:
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            now = datetime.now(UTC)
            async with sessions() as session, session.begin():
                for member_id in (account_id, other_id):
                    session.add(
                        Account(
                            id=member_id,
                            email_display=f"{member_id}@example.com",
                            email_key=f"{member_id}@example.com",
                            password_hash=hash_password(password),
                            verified_at=now,
                            created_at=now,
                            updated_at=now,
                        )
                    )
            async with sessions() as session, session.begin():
                owner = await SessionService().sign_in(
                    session, email=f"{account_id}@example.com", password=password
                )
                other = await SessionService().sign_in(
                    session, email=f"{other_id}@example.com", password=password
                )
            return owner, other
        finally:
            await database.close()

    async def attach_valid_media(target_id: UUID) -> tuple[UUID, UUID]:
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            asset_ids = (uuid4(), uuid4())
            async with sessions() as session, session.begin():
                for asset_id, kind in zip(asset_ids, ("logo", "screenshot"), strict=True):
                    session.add(
                        ProductAsset(
                            id=asset_id,
                            product_id=target_id,
                            kind=kind,
                            state="clean",
                            staging_key=f"products/{account_id}/{target_id}/{asset_id}-stage",
                            clean_key=f"products/{account_id}/{target_id}/{asset_id}-clean",
                            media_type="image/png",
                            byte_count=100,
                            position=None,
                            expires_at=None,
                            attached_at=None,
                        )
                    )
            return asset_ids
        finally:
            await database.close()

    async def inspect(target_id: UUID) -> tuple[list[str], int, int, datetime]:
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session:
                selected = list(
                    await session.scalars(
                        select(Topic.name_key)
                        .join(ProductTopic, ProductTopic.topic_id == Topic.id)
                        .where(ProductTopic.product_id == target_id)
                        .order_by(ProductTopic.position)
                    )
                )
                product = await session.get(Product, target_id)
                period = await session.scalar(
                    select(ProductSubmission).where(
                        ProductSubmission.product_id == target_id,
                        ProductSubmission.state == "pending",
                    )
                )
                assert product is not None and period is not None
                event_count = await session.scalar(
                    select(func.count())
                    .select_from(OutboxMessage)
                    .where(
                        OutboxMessage.aggregate_id == target_id,
                        OutboxMessage.event_type == "product.saved.v1",
                    )
                )
                return selected, product.version, int(event_count or 0), period.submitted_at
        finally:
            await database.close()

    async def cleanup() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                if product_id is not None:
                    await session.execute(
                        delete(OutboxMessage).where(OutboxMessage.aggregate_id == product_id)
                    )
                    await session.execute(delete(Product).where(Product.id == product_id))
                await session.execute(
                    delete(Session).where(Session.account_id.in_((account_id, other_id)))
                )
                await session.execute(delete(Account).where(Account.id.in_((account_id, other_id))))
                await session.execute(
                    delete(Topic).where(Topic.name_key.in_([name.casefold() for name in names]))
                )
        finally:
            await database.close()
            redis.close()

    try:
        owner, other = asyncio.run(prepare())
        storage = PrivateObjectStore(
            endpoint_url=integration_settings_fixture.s3_endpoint_url,
            bucket_name="launchpad-private",
            access_key_id=integration_settings_fixture.s3_access_key_id,
            secret_access_key=integration_settings_fixture.s3_secret_access_key,
        )
        app = FastAPI()
        route_database = Database.connect(integration_settings_fixture.database_url)
        app.include_router(
            router(settings=settings, database=route_database, redis=redis, storage=storage)
        )
        with TestClient(app) as client:
            origin = {"Origin": "http://localhost:8080", "X-CSRF-Token": owner.csrf_token}
            cookies = {settings.session_cookie_name: owner.session_secret}
            transfer_without_origin = client.put(
                "/api/v1/me/products/00000000-0000-0000-0000-000000000001/"
                "assets/00000000-0000-0000-0000-000000000002/content",
                content=b"must not be accepted",
            )
            assert transfer_without_origin.status_code == 403
            missing_csrf = client.post(
                "/api/v1/me/products", headers={"Origin": origin["Origin"]}, cookies=cookies
            )
            assert missing_csrf.status_code == 403
            assert missing_csrf.json() == {"detail": "request rejected"}
            created = client.post("/api/v1/me/products", headers=origin, cookies=cookies)
            assert created.status_code == 201
            product_id = UUID(created.json()["id"])
            assert created.json() == {"id": str(product_id), "status": "draft", "version": 0}

            asset_path = f"/api/v1/me/products/{product_id}/assets"
            minio_intent = client.post(
                asset_path,
                json={"kind": "logo", "content_type": "image/png", "size": 128},
                headers=origin,
                cookies=cookies,
            )
            assert minio_intent.status_code == 201
            assert minio_intent.json()["upload_method"] == "POST"
            assert minio_intent.json()["upload_transport"] == "storage_form"
            assert minio_intent.json()["fields"]

            r2_app = FastAPI()
            r2_database = Database.connect(integration_settings_fixture.database_url)
            r2_settings = settings.model_copy(update={"storage_provider": "r2"})
            r2_app.include_router(
                router(settings=r2_settings, database=r2_database, redis=redis, storage=storage)
            )
            with TestClient(r2_app) as r2_client:
                r2_intent = r2_client.post(
                    asset_path,
                    json={"kind": "screenshot", "content_type": "image/webp", "size": 256},
                    headers=origin,
                    cookies=cookies,
                )
            assert r2_intent.status_code == 201
            assert r2_intent.json()["upload_method"] == "PUT"
            assert r2_intent.json()["upload_transport"] == "authenticated_api"
            assert r2_intent.json()["upload_url"].endswith("/content")
            assert r2_intent.json()["fields"] == {}
            assert r2_intent.json()["upload_headers"] == {"Content-Type": "image/webp"}

            other_response = client.patch(
                f"/api/v1/me/products/{product_id}",
                json={"version": 0, "name": "Not yours"},
                headers={"Origin": origin["Origin"], "X-CSRF-Token": other.csrf_token},
                cookies={settings.session_cookie_name: other.session_secret},
            )
            assert other_response.status_code == 404

            saved = client.patch(
                f"/api/v1/me/products/{product_id}",
                json={
                    "version": 0,
                    "name": "Example product",
                    "pitch": "One-line pitch",
                    "description": "Useful description",
                    "website_url": "https://example.test/product",
                    "topic_names": names,
                },
                headers=origin,
                cookies=cookies,
            )
            assert saved.status_code == 200
            assert saved.json() == {"id": str(product_id), "status": "draft", "version": 1}
            stale = client.patch(
                f"/api/v1/me/products/{product_id}",
                json={"version": 0, "topic_names": ["Stale"]},
                headers=origin,
                cookies=cookies,
            )
            assert stale.status_code == 409
            save_bucket = f"launchpad:limit:address:product:save:account:{account_id.hex}"
            redis.set(save_bucket, 60, ex=60)
            throttled = client.patch(
                f"/api/v1/me/products/{product_id}",
                json={"version": 1, "name": "Throttled edit"},
                headers=origin,
                cookies=cookies,
            )
            assert throttled.status_code == 429
            redis.delete(save_bucket)
            logo_asset_id, screenshot_asset_id = asyncio.run(attach_valid_media(product_id))
            asset_path = f"/api/v1/me/products/{product_id}/assets"
            attachment_payload = {
                "version": 1,
                "logo_asset_id": str(logo_asset_id),
                "screenshot_asset_ids": [str(screenshot_asset_id)],
            }
            missing_csrf = client.put(
                asset_path,
                json=attachment_payload,
                headers={"Origin": origin["Origin"]},
                cookies=cookies,
            )
            assert missing_csrf.status_code == 403
            malformed_attachment = client.put(
                asset_path,
                json={"version": 1, "logo_asset_id": str(logo_asset_id)},
                headers=origin,
                cookies=cookies,
            )
            assert malformed_attachment.status_code == 422
            other_attachment = client.put(
                asset_path,
                json=attachment_payload,
                headers={"Origin": origin["Origin"], "X-CSRF-Token": other.csrf_token},
                cookies={settings.session_cookie_name: other.session_secret},
            )
            assert other_attachment.status_code == 404
            attached = client.put(
                asset_path, json=attachment_payload, headers=origin, cookies=cookies
            )
            assert attached.status_code == 200
            assert attached.json() == {"id": str(product_id), "status": "draft", "version": 2}
            stale_attachment = client.put(
                asset_path, json=attachment_payload, headers=origin, cookies=cookies
            )
            assert stale_attachment.status_code == 409

            submitted = client.post(
                f"/api/v1/me/products/{product_id}/submit",
                json={"version": 2},
                headers=origin,
                cookies=cookies,
            )
            assert submitted.status_code == 200
            submission_id = submitted.json()["submission_id"]
            repeated = client.post(
                f"/api/v1/me/products/{product_id}/submit",
                json={"version": 2},
                headers=origin,
                cookies=cookies,
            )
            assert repeated.status_code == 200
            assert repeated.json()["submission_id"] == submission_id

            before = asyncio.run(inspect(product_id))
            rejected = client.patch(
                f"/api/v1/me/products/{product_id}",
                json={"version": 3, "topic_names": []},
                headers=origin,
                cookies=cookies,
            )
            assert rejected.status_code == 422
            assert asyncio.run(inspect(product_id)) == before
            duplicate = client.patch(
                f"/api/v1/me/products/{product_id}",
                json={"version": 3, "topic_names": [names[0], names[0].upper()]},
                headers=origin,
                cookies=cookies,
            )
            assert duplicate.status_code == 422
            assert asyncio.run(inspect(product_id)) == before

            edited = client.patch(
                f"/api/v1/me/products/{product_id}",
                json={"version": 3, "topic_names": [names[1].upper(), names[0].upper()]},
                headers=origin,
                cookies=cookies,
            )
            assert edited.status_code == 200
            assert edited.json()["version"] == 4
            after = asyncio.run(inspect(product_id))
            assert after[0] == [names[1].casefold(), names[0].casefold()]
            assert after[1] == 4
            assert after[2] == before[2] + 1
            assert after[3] == before[3]

            def unavailable(_key: str) -> int:
                raise RedisError("simulated unavailable limiter")

            monkeypatch.setattr(redis, "incr", unavailable)
            unavailable_save = client.patch(
                f"/api/v1/me/products/{product_id}",
                json={"version": 4, "name": "Cannot save during outage"},
                headers=origin,
                cookies=cookies,
            )
            assert unavailable_save.status_code == 503

            withdrawn = client.post(
                f"/api/v1/me/products/{product_id}/withdraw",
                json={"version": 4, "submission_id": submission_id},
                headers=origin,
                cookies=cookies,
            )
            assert withdrawn.status_code == 200
            assert withdrawn.json()["status"] == "draft"
    finally:
        asyncio.run(cleanup())
