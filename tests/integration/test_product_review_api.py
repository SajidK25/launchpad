"""HTTP integration coverage for gated staff review commands."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from app.modules.auth.models import Account, Session
from app.modules.auth.sessions import SessionService
from app.modules.notifications.models import Notification
from app.modules.products.models import Product, ProductReviewDecision, ProductSubmission
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
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker


def test_staff_review_http_command_enforces_authorization_and_request_protection(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        route_database = Database.connect(integration_settings_fixture.database_url)
        redis = Redis.from_url(integration_settings_fixture.redis_url)
        now = datetime.now(UTC)
        reviewer_id, member_id, unverified_id, suspended_id, founder_id = (
            uuid4() for _ in range(5)
        )
        account_ids = [reviewer_id, member_id, unverified_id, suspended_id, founder_id]
        product_ids = [uuid4() for _ in range(3)]
        submission_ids = [uuid4() for _ in product_ids]
        sessions = None
        rate_key = f"launchpad:limit:address:product:review:account:{reviewer_id.hex}"
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                for account_id, role, verified, suspended_at in (
                    (reviewer_id, "reviewer", True, None),
                    (member_id, "member", True, None),
                    (unverified_id, "reviewer", False, None),
                    (suspended_id, "admin", True, now),
                    (founder_id, "member", True, None),
                ):
                    session.add(
                        Account(
                            id=account_id,
                            email_display=f"{account_id}@example.com",
                            email_key=f"{account_id}@example.com",
                            password_hash=hash_password("Review-test-password-1!"),
                            verified_at=now if verified else None,
                            role=role,
                            suspended_at=suspended_at,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                for product_id, submission_id in zip(product_ids, submission_ids, strict=True):
                    await session.execute(
                        insert(Product).values(
                            id=product_id,
                            founder_id=founder_id,
                            status="submitted",
                            version=1,
                            name="Review API product",
                            pitch="A useful tool",
                            description="Private review fixture.",
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
                            state="pending",
                            submitted_at=now,
                            product_version=1,
                        )
                    )
            async with sessions() as session, session.begin():
                auth = SessionService()
                credentials = {
                    account_id: await auth.sign_in(
                        session,
                        email=f"{account_id}@example.com",
                        password="Review-test-password-1!",
                    )
                    for account_id in (reviewer_id, member_id, unverified_id, suspended_id)
                }

            settings = load_settings()
            storage = PrivateObjectStore(
                endpoint_url=integration_settings_fixture.s3_endpoint_url,
                bucket_name="launchpad-private",
                access_key_id=integration_settings_fixture.s3_access_key_id,
                secret_access_key=integration_settings_fixture.s3_secret_access_key,
            )
            app = FastAPI()
            app.include_router(
                router(settings=settings, database=route_database, redis=redis, storage=storage)
            )
            disabled_app = FastAPI()
            disabled_settings = settings.model_copy(update={"review_writes_enabled": False})
            disabled_app.include_router(
                router(
                    settings=disabled_settings,
                    database=route_database,
                    redis=redis,
                    storage=storage,
                )
            )
            origin = "http://localhost:8080"
            reviewer = credentials[reviewer_id]
            reviewer_headers = {
                "Origin": origin,
                "X-CSRF-Token": reviewer.csrf_token,
                "Idempotency-Key": "review-http-approve-1",
            }
            reviewer_cookies = {settings.session_cookie_name: reviewer.session_secret}

            def post_review(
                client: TestClient,
                index: int,
                outcome: str = "approved",
                feedback: str | None = None,
                expected_version: int = 1,
                key: str = "review-http-approve-1",
                *,
                headers: dict[str, str] | None = None,
                cookies: dict[str, str] | None = None,
            ):
                body = {
                    "submission_id": str(submission_ids[index]),
                    "expected_version": expected_version,
                    "outcome": outcome,
                }
                if feedback is not None:
                    body["feedback"] = feedback
                selected_headers = {
                    **reviewer_headers,
                    "Idempotency-Key": key,
                    **(headers or {}),
                }
                return client.post(
                    f"/api/v1/staff/products/{product_ids[index]}/review-decisions",
                    json=body,
                    headers=selected_headers,
                    cookies=reviewer_cookies if cookies is None else cookies,
                )

            with TestClient(app) as client:
                missing_csrf = post_review(
                    client,
                    0,
                    headers={"X-CSRF-Token": ""},
                )
                assert missing_csrf.status_code == 403

                untrusted = post_review(client, 0, headers={"Origin": "http://attacker.example"})
                assert untrusted.status_code == 403

                visitor = post_review(client, 0, headers={"Origin": origin}, cookies={})
                assert visitor.status_code == 401

                for account_id in (member_id, unverified_id, suspended_id):
                    identity = credentials[account_id]
                    denied = post_review(
                        client,
                        0,
                        key=f"review-denied-{account_id.hex}",
                        headers={"X-CSRF-Token": identity.csrf_token},
                        cookies={settings.session_cookie_name: identity.session_secret},
                    )
                    assert denied.status_code == 403

                redis.set(rate_key, 60, ex=60)
                throttled = post_review(client, 0)
                assert throttled.status_code == 429
                redis.delete(rate_key)

                accepted = post_review(client, 0)
                assert accepted.status_code == 201
                assert accepted.json()["status"] == "approved"
                assert accepted.json()["version"] == 2
                replay = post_review(client, 0)
                assert replay.status_code == 201
                assert replay.json()["decision_id"] == accepted.json()["decision_id"]

                changed_payload = post_review(
                    client,
                    0,
                    outcome="rejected",
                    feedback="Please revise.",
                )
                assert changed_payload.status_code == 409
                stale = post_review(client, 0, expected_version=1, key="review-stale-version")
                assert stale.status_code == 409

                invalid_feedback = post_review(
                    client, 1, outcome="changes_requested", feedback="   "
                )
                assert invalid_feedback.status_code == 422

                rejected = post_review(
                    client,
                    1,
                    outcome="rejected",
                    feedback="Does not meet the launch policy.",
                    key="review-http-rejected-1",
                )
                returned = post_review(
                    client,
                    2,
                    outcome="changes_requested",
                    feedback="Add onboarding details.",
                    key="review-http-return-1",
                )
                assert rejected.status_code == returned.status_code == 201
                assert rejected.json()["status"] == "rejected"
                assert returned.json()["status"] == "changes_requested"

            with TestClient(disabled_app) as client:
                disabled = post_review(client, 0, expected_version=2)
                assert disabled.status_code == 503

            async with sessions() as session:
                decisions = list(
                    await session.scalars(
                        select(ProductReviewDecision).where(
                            ProductReviewDecision.submission_id.in_(submission_ids)
                        )
                    )
                )
                notifications = list(
                    await session.scalars(
                        select(Notification).where(
                            Notification.review_decision_id.in_(
                                [decision.id for decision in decisions]
                            )
                        )
                    )
                )
                products = list(
                    await session.scalars(select(Product).where(Product.id.in_(product_ids)))
                )
                assert len(decisions) == len(notifications) == 3
                assert {product.status for product in products} == {
                    "approved",
                    "rejected",
                    "changes_requested",
                }
        finally:
            if sessions is not None:
                async with sessions() as session, session.begin():
                    decision_ids = list(
                        await session.scalars(
                            select(ProductReviewDecision.id).where(
                                ProductReviewDecision.submission_id.in_(submission_ids)
                            )
                        )
                    )
                    await session.execute(
                        delete(Notification).where(
                            Notification.review_decision_id.in_(decision_ids)
                        )
                    )
                    await session.execute(
                        delete(ProductReviewDecision).where(
                            ProductReviewDecision.id.in_(decision_ids)
                        )
                    )
                    await session.execute(
                        delete(OutboxMessage).where(
                            OutboxMessage.aggregate_id.in_([*product_ids, *decision_ids])
                        )
                    )
                    await session.execute(delete(Product).where(Product.id.in_(product_ids)))
                    await session.execute(
                        delete(Session).where(Session.account_id.in_(account_ids))
                    )
                    await session.execute(delete(Account).where(Account.id.in_(account_ids)))
            redis.delete(rate_key)
            redis.close()
            await route_database.close()
            await database.close()

    asyncio.run(verify())
