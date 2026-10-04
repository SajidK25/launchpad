"""Mounted notification HTTP, GraphQL, and account-scoped WebSocket behavior."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from app.modules.auth.models import Account, Session
from app.modules.auth.sessions import SessionService
from app.modules.notifications.live import notification_channel
from app.modules.notifications.models import Notification
from app.modules.notifications.routes import router as notifications_router
from app.modules.products.models import Product, ProductReviewDecision, ProductSubmission
from app.modules.users.routes import router as users_router
from app.shared.config.settings import load_settings
from app.shared.db.database import Database
from app.shared.events.models import OutboxMessage
from app.shared.security.passwords import hash_password
from app.shared.storage.objects import PrivateObjectStore
from conftest import IntegrationSettings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker


def test_mounted_notification_reads_survive_disconnect_and_live_hints_stay_account_scoped(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        route_database = Database.connect(integration_settings_fixture.database_url)
        sync_redis = Redis.from_url(integration_settings_fixture.redis_url)
        live_redis = AsyncRedis.from_url(integration_settings_fixture.redis_url)
        sessions = None
        now = datetime.now(UTC)
        staff_id, owner_id, other_id = (uuid4() for _ in range(3))
        product_ids = (uuid4(), uuid4())
        submission_ids = (uuid4(), uuid4())
        decision_ids = (uuid4(), uuid4())
        notification_ids = (uuid4(), uuid4())
        credentials = {}
        password = "Notification-test-password-1!"
        origin = "http://localhost:8080"
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                for account_id, role in (
                    (staff_id, "reviewer"),
                    (owner_id, "member"),
                    (other_id, "member"),
                ):
                    session.add(
                        Account(
                            id=account_id,
                            email_display=f"{account_id}@example.com",
                            email_key=f"{account_id}@example.com",
                            password_hash=hash_password(password),
                            verified_at=now,
                            role=role,
                            created_at=now,
                            updated_at=now,
                        )
                    )
            async with sessions() as session, session.begin():
                auth = SessionService()
                for account_id in (owner_id, other_id):
                    credentials[account_id] = await auth.sign_in(
                        session,
                        email=f"{account_id}@example.com",
                        password=password,
                    )
            async with sessions() as session, session.begin():
                for index, (product_id, submission_id, decision_id, notification_id) in enumerate(
                    zip(product_ids, submission_ids, decision_ids, notification_ids, strict=True)
                ):
                    founder_id = owner_id if index == 0 else other_id
                    await session.execute(
                        insert(Product).values(
                            id=product_id,
                            founder_id=founder_id,
                            status="approved",
                            version=1,
                            name=f"Private launch {index}",
                            pitch="A useful product",
                            description="Private approved content",
                            website_url=f"https://example.test/{product_id.hex}",
                            website_key=f"https://example.test/{product_id.hex}",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    await session.execute(
                        insert(ProductSubmission).values(
                            id=submission_id,
                            product_id=product_id,
                            state="approved",
                            submitted_at=now,
                            closed_at=now,
                            product_version=1,
                        )
                    )
                    await session.execute(
                        insert(ProductReviewDecision).values(
                            id=decision_id,
                            submission_id=submission_id,
                            actor_account_id=staff_id,
                            from_status="submitted",
                            outcome="approved",
                            reviewed_product_version=1,
                            feedback=None,
                            idempotency_key=f"notification-live-{decision_id}",
                            request_fingerprint="b" * 64,
                            created_at=now,
                        )
                    )
                    await session.execute(
                        insert(Notification).values(
                            id=notification_id,
                            recipient_account_id=founder_id,
                            review_decision_id=decision_id,
                            kind="review_approved",
                            created_at=now,
                            read_at=None,
                        )
                    )

            settings = load_settings().model_copy(
                update={
                    "products_enabled": False,
                    "review_writes_enabled": False,
                    "trusted_web_origins": (origin,),
                }
            )
            storage = PrivateObjectStore(
                endpoint_url=integration_settings_fixture.s3_endpoint_url,
                bucket_name="launchpad-private",
                access_key_id=integration_settings_fixture.s3_access_key_id,
                secret_access_key=integration_settings_fixture.s3_secret_access_key,
            )
            app = FastAPI()
            profile_routes, graphql_routes = users_router(
                settings=settings,
                database=route_database,
                redis=sync_redis,
                storage=storage,
            )
            app.include_router(profile_routes)
            app.include_router(graphql_routes, prefix="/api/v1")
            app.include_router(
                notifications_router(
                    settings=settings,
                    database=route_database,
                    redis=sync_redis,
                    live_redis=live_redis,
                )
            )

            owner = credentials[owner_id]
            other = credentials[other_id]
            owner_headers = {
                "Origin": origin,
                "X-CSRF-Token": owner.csrf_token,
                "Cookie": f"{settings.session_cookie_name}={owner.session_secret}",
            }
            other_headers = {
                "Origin": origin,
                "Cookie": f"{settings.session_cookie_name}={other.session_secret}",
            }
            with TestClient(app) as client:
                openapi = client.get("/openapi.json").json()
                assert "/api/v1/me/notifications/{notification_id}/read" in openapi["paths"]
                with client.websocket_connect(
                    "/api/v1/me/notifications/live", headers=owner_headers
                ) as owner_socket:
                    with client.websocket_connect(
                        "/api/v1/me/notifications/live", headers=other_headers
                    ):
                        published = sync_redis.publish(
                            notification_channel(owner_id), "do-not-forward-this-payload"
                        )
                        assert published == 1
                        assert owner_socket.receive_json() == {"type": "notifications_changed"}

                inbox_response = client.post(
                    "/api/v1/graphql",
                    json={
                        "query": "query { viewerNotificationInbox { unreadCount "
                        "items { id kind readAt } nextCursor } }"
                    },
                    cookies={settings.session_cookie_name: owner.session_secret},
                )
                assert inbox_response.status_code == 200
                inbox = inbox_response.json()["data"]["viewerNotificationInbox"]
                assert inbox["unreadCount"] == 1
                assert inbox["items"][0]["id"] == str(notification_ids[0])
                assert inbox["items"][0]["readAt"] is None

                marked = client.put(
                    f"/api/v1/me/notifications/{notification_ids[0]}/read",
                    headers=owner_headers,
                )
                repeated = client.put(
                    f"/api/v1/me/notifications/{notification_ids[0]}/read",
                    headers=owner_headers,
                )
                foreign = client.put(
                    f"/api/v1/me/notifications/{notification_ids[1]}/read",
                    headers=owner_headers,
                )
                assert marked.status_code == repeated.status_code == 200
                assert foreign.status_code == 404

                after_read = client.post(
                    "/api/v1/graphql",
                    json={
                        "query": "query { viewerNotificationInbox { unreadCount "
                        "items { id readAt } } }"
                    },
                    cookies={settings.session_cookie_name: owner.session_secret},
                )
                assert after_read.json()["data"]["viewerNotificationInbox"]["unreadCount"] == 0

            async with sessions() as session:
                persisted = await session.get(Notification, notification_ids[0])
                live_events = list(
                    await session.scalars(
                        select(OutboxMessage).where(
                            OutboxMessage.aggregate_id == notification_ids[0],
                            OutboxMessage.event_type == "notification.changed.v1",
                        )
                    )
                )
                assert persisted is not None and persisted.read_at is not None
                assert len(live_events) == 1
        finally:
            if sessions is not None:
                async with sessions() as session, session.begin():
                    await session.execute(
                        delete(Notification).where(Notification.id.in_(notification_ids))
                    )
                    await session.execute(
                        delete(OutboxMessage).where(
                            OutboxMessage.aggregate_id.in_(notification_ids)
                        )
                    )
                    await session.execute(
                        delete(ProductReviewDecision).where(
                            ProductReviewDecision.id.in_(decision_ids)
                        )
                    )
                    await session.execute(
                        delete(ProductSubmission).where(ProductSubmission.id.in_(submission_ids))
                    )
                    await session.execute(delete(Product).where(Product.id.in_(product_ids)))
                    await session.execute(
                        delete(Session).where(Session.account_id.in_((owner_id, other_id)))
                    )
                    await session.execute(
                        delete(Account).where(Account.id.in_((staff_id, owner_id, other_id)))
                    )
            await database.close()
            await route_database.close()
            await live_redis.aclose()
            sync_redis.close()

    asyncio.run(verify())
