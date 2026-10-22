"""HTTP coverage for the one private product and profile GraphQL endpoint."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.modules.auth.models import Account, Session
from app.modules.auth.sessions import SessionService, SignInResult
from app.modules.products.models import (
    Product,
    ProductAsset,
    ProductSubmission,
    ProductTopic,
    Topic,
)
from app.modules.users.models import Profile, ProfileLink
from app.modules.users.routes import router as users_router
from app.shared.config.settings import load_settings
from app.shared.db.database import Database
from app.shared.security.passwords import hash_password
from app.shared.storage.objects import PrivateObjectStore
from conftest import IntegrationSettings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import delete, insert, update
from sqlalchemy.ext.asyncio import async_sessionmaker


def test_composed_graphql_keeps_private_products_topics_and_media_scoped(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    settings = load_settings().model_copy(update={"launches_enabled": True})
    account_ids = (uuid4(), uuid4(), uuid4(), uuid4())
    owner_id, other_id, staff_id, unverified_id = account_ids
    product_ids = (uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4())
    (
        owner_draft_id,
        owner_pending_id,
        other_pending_id,
        unverified_draft_id,
        public_launched_id,
        private_approved_id,
    ) = product_ids
    submission_ids = (uuid4(), uuid4())
    topic_id = uuid4()
    asset_id = uuid4()
    public_asset_id = uuid4()
    topic_name = f"Secret Launch {topic_id.hex[:8]}"
    now = datetime.now(UTC)
    password = "a secure GraphQL test password!"
    password_hash = hash_password(password)

    async def seed() -> dict[UUID, SignInResult]:
        database = Database.connect(integration_settings_fixture.database_url)
        await database.ensure_compatible()
        sessions = async_sessionmaker(database.engine, expire_on_commit=False)
        async with sessions() as session, session.begin():
            for account_id, role, verified, suspended in (
                (owner_id, "member", True, False),
                (other_id, "member", True, True),
                (staff_id, "reviewer", True, False),
                (unverified_id, "member", False, False),
            ):
                session.add(
                    Account(
                        id=account_id,
                        email_display=f"{account_id}@example.com",
                        email_key=f"{account_id}@example.com",
                        password_hash=password_hash,
                        verified_at=now if verified else None,
                        role=role,
                        suspended_at=now if suspended else None,
                        created_at=now,
                        updated_at=now,
                    )
                )
        async with sessions() as session, session.begin():
            await session.execute(
                insert(Profile).values(
                    account_id=staff_id,
                    display_name="Reviewer",
                    bio="Reviews new launches",
                    photo_key=f"profile-clean/{staff_id}/photo",
                    visibility="public",
                    published_at=now,
                    version=2,
                )
            )
            session.add(
                ProfileLink(id=uuid4(), account_id=staff_id, url="https://example.test", position=0)
            )
        async with sessions() as session, session.begin():
            await session.execute(
                insert(Product).values(
                    [
                        {
                            "id": product_id,
                            "founder_id": founder_id,
                            "status": status,
                            "version": version,
                            "name": name,
                            "pitch": "A useful launch" if status == "submitted" else None,
                            "description": "Reviewable details" if status == "submitted" else None,
                            "website_url": website,
                            "website_key": website,
                            "created_at": now,
                            "updated_at": now,
                        }
                        for product_id, founder_id, status, version, name, website in (
                            (owner_draft_id, owner_id, "draft", 1, "Private owner draft", None),
                            (
                                owner_pending_id,
                                owner_id,
                                "submitted",
                                2,
                                "Owner pending",
                                "https://example.test/shared",
                            ),
                            (
                                other_pending_id,
                                other_id,
                                "submitted",
                                3,
                                "Other pending",
                                "https://example.test/shared",
                            ),
                            (
                                unverified_draft_id,
                                unverified_id,
                                "draft",
                                0,
                                "Unverified private draft",
                                None,
                            ),
                        )
                    ]
                )
            )
            await session.execute(
                insert(Product).values(
                    [
                        {
                            "id": public_launched_id,
                            "founder_id": other_id,
                            "status": "launched",
                            "version": 4,
                            "name": "Public Launch",
                            "pitch": "A published card",
                            "description": "Do not expose this description in discovery",
                            "website_url": "https://example.test/public",
                            "website_key": "https://example.test/public",
                            "launched_at": now - timedelta(minutes=1),
                            "created_at": now,
                            "updated_at": now,
                        },
                        {
                            "id": private_approved_id,
                            "founder_id": other_id,
                            "status": "approved",
                            "version": 2,
                            "name": "Private Approved Product",
                            "pitch": "Not public until launched",
                            "description": "Private approved description",
                            "website_url": "https://example.test/private-approved",
                            "website_key": "https://example.test/private-approved",
                            "launched_at": None,
                            "created_at": now,
                            "updated_at": now,
                        },
                    ]
                )
            )
            session.add_all(
                [
                    ProductSubmission(
                        id=submission_ids[0],
                        product_id=owner_pending_id,
                        state="pending",
                        submitted_at=now,
                        product_version=2,
                    ),
                    ProductSubmission(
                        id=submission_ids[1],
                        product_id=other_pending_id,
                        state="pending",
                        submitted_at=now + timedelta(minutes=1),
                        product_version=3,
                    ),
                ]
            )
            session.add(Topic(id=topic_id, display_name=topic_name, name_key=topic_name.casefold()))
            await session.flush()
            session.add_all(
                [
                    ProductTopic(
                        product_id=owner_pending_id,
                        topic_id=topic_id,
                        position=1,
                        selected_label=topic_name.upper(),
                    ),
                    ProductTopic(
                        product_id=other_pending_id,
                        topic_id=topic_id,
                        position=1,
                        selected_label=topic_name.lower(),
                    ),
                    ProductTopic(
                        product_id=public_launched_id,
                        topic_id=topic_id,
                        position=1,
                        selected_label="Public topic",
                    ),
                    ProductAsset(
                        id=asset_id,
                        product_id=other_pending_id,
                        kind="logo",
                        state="clean",
                        staging_key=f"products/{other_id}/{other_pending_id}/{asset_id}-stage",
                        clean_key=f"products/{other_id}/{other_pending_id}/{asset_id}-clean",
                        media_type="image/png",
                        byte_count=100,
                        position=None,
                        expires_at=None,
                        attached_at=now,
                    ),
                    ProductAsset(
                        id=public_asset_id,
                        product_id=public_launched_id,
                        kind="logo",
                        state="clean",
                        staging_key=f"products/{other_id}/{public_launched_id}/{public_asset_id}-stage",
                        clean_key=f"products/{other_id}/{public_launched_id}/{public_asset_id}-clean",
                        media_type="image/png",
                        byte_count=100,
                        position=None,
                        expires_at=None,
                        attached_at=now,
                    ),
                ]
            )
        results: dict[UUID, SignInResult] = {}
        async with sessions() as session, session.begin():
            for account_id in account_ids:
                results[account_id] = await SessionService().sign_in(
                    session, email=f"{account_id}@example.com", password=password
                )
        await database.close()
        return results

    async def cleanup() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        sessions = async_sessionmaker(database.engine, expire_on_commit=False)
        async with sessions() as session, session.begin():
            await session.execute(delete(Product).where(Product.id.in_(product_ids)))
            await session.execute(delete(Topic).where(Topic.id == topic_id))
            await session.execute(delete(ProfileLink).where(ProfileLink.account_id == staff_id))
            await session.execute(delete(Profile).where(Profile.account_id == staff_id))
            await session.execute(delete(Session).where(Session.account_id.in_(account_ids)))
            await session.execute(delete(Account).where(Account.id.in_(account_ids)))
        await database.close()

    async def withdraw_other() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        async with database.engine.begin() as connection:
            await connection.execute(
                update(ProductSubmission)
                .where(ProductSubmission.id == submission_ids[1])
                .values(state="withdrawn", closed_at=now + timedelta(minutes=2))
            )
            await connection.execute(
                update(Product).where(Product.id == other_pending_id).values(status="draft")
            )
        await database.close()

    try:
        sessions = asyncio.run(seed())
    except Exception:
        asyncio.run(cleanup())
        raise
    redis = Redis.from_url(integration_settings_fixture.redis_url)
    storage = PrivateObjectStore(
        endpoint_url=integration_settings_fixture.s3_endpoint_url,
        bucket_name="launchpad-private",
        access_key_id=integration_settings_fixture.s3_access_key_id,
        secret_access_key=integration_settings_fixture.s3_secret_access_key,
    )
    app = FastAPI()
    route_database = Database.connect(integration_settings_fixture.database_url)
    _, graphql = users_router(
        settings=settings, database=route_database, redis=redis, storage=storage
    )
    app.include_router(graphql, prefix="/api/v1")

    def query(client: TestClient, text: str, actor_id: UUID | None = None) -> dict[str, object]:
        cookies = (
            {settings.session_cookie_name: sessions[actor_id].session_secret}
            if actor_id is not None
            else None
        )
        response = client.post("/api/v1/graphql", json={"query": text}, cookies=cookies)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        return response.json()

    try:
        with TestClient(app) as client:
            public_page = query(
                client,
                "query { publicLaunches(first: 10) { todayDate selectedDate items "
                "{ id name pitch logoUrl topics } nextCursor } }",
            )
            page = public_page["data"]["publicLaunches"]
            assert page["todayDate"] == now.date().isoformat()
            assert page["selectedDate"] == now.date().isoformat()
            assert page["items"] == [
                {
                    "id": str(public_launched_id),
                    "name": "Public Launch",
                    "pitch": "A published card",
                    "logoUrl": (
                        f"/api/v1/products/{public_launched_id}/assets/{public_asset_id}/public"
                    ),
                    "topics": ["Public topic"],
                }
            ]
            public_product = query(
                client,
                f'query {{ publicProduct(id: "{public_launched_id}") '
                "{ id name description logo { id url } } }",
            )
            assert public_product["data"]["publicProduct"]["description"] == (
                "Do not expose this description in discovery"
            )
            assert public_product["data"]["publicProduct"]["logo"] == {
                "id": str(public_asset_id),
                "url": f"/api/v1/products/{public_launched_id}/assets/{public_asset_id}/public",
            }
            archive_page = query(
                client,
                f'query {{ publicLaunches(date: "{now.date().isoformat()}") '
                "{ todayDate selectedDate items { id } } }",
            )
            assert archive_page["data"]["publicLaunches"]["selectedDate"] == now.date().isoformat()
            assert archive_page["data"]["publicLaunches"]["items"] == [
                {"id": str(public_launched_id)}
            ]
            future_date = (now.date() + timedelta(days=1)).isoformat()
            for invalid_public_read in (
                "query { publicLaunches(first: 51) { items { id } } }",
                'query { publicLaunches(after: "malformed") { items { id } } }',
                f'query {{ publicLaunches(date: "{future_date}") {{ items {{ id }} }} }}',
            ):
                invalid = query(client, invalid_public_read)
                assert invalid["data"] is None
                assert invalid["errors"][0]["message"] == "invalid product query"

            owner_list = query(
                client,
                "query { viewerProducts { items { id status version name } nextCursor } }",
                owner_id,
            )
            assert {item["id"] for item in owner_list["data"]["viewerProducts"]["items"]} == {
                str(owner_draft_id),
                str(owner_pending_id),
            }
            unverified = query(
                client,
                "query { viewerProducts { items { id name } } }",
                unverified_id,
            )
            assert [item["id"] for item in unverified["data"]["viewerProducts"]["items"]] == [
                str(unverified_draft_id)
            ]
            foreign = query(
                client,
                f'query {{ viewerProduct(id: "{other_pending_id}") {{ summary {{ id }} }} }}',
                owner_id,
            )
            assert foreign["data"]["viewerProduct"] is None
            own_detail = query(
                client,
                f'query {{ viewerProduct(id: "{owner_pending_id}") '
                "{ summary { id version } topics { displayName position } "
                "submission { id productVersion } } }",
                owner_id,
            )
            assert own_detail["data"]["viewerProduct"]["topics"] == [
                {"displayName": topic_name.upper(), "position": 1}
            ]
            assert own_detail["data"]["viewerProduct"]["submission"] == {
                "id": str(submission_ids[0]),
                "productVersion": 2,
            }
            visitor = query(client, "query { viewerProducts { items { id } } }")
            assert visitor["data"] is None
            assert visitor["errors"]
            owner_topic = query(
                client,
                "query { topicChoices { id displayName } }",
                owner_id,
            )
            assert owner_topic["data"]["topicChoices"] == [
                {"id": str(topic_id), "displayName": topic_name.upper()}
            ]
            assert (
                query(client, "query { topicChoices { id displayName } }")["data"]["topicChoices"]
                == []
            )
            assert (
                query(client, "query { topicChoices { id displayName } }", staff_id)["data"][
                    "topicChoices"
                ]
                == []
            )
            staff_queue = query(
                client,
                "query { reviewQueue(first: 50) { items { product { id version } "
                "submission { id productVersion } possibleDuplicate founderSuspended } } }",
                staff_id,
            )
            entries = [
                entry
                for entry in staff_queue["data"]["reviewQueue"]["items"]
                if entry["product"]["id"] in {str(owner_pending_id), str(other_pending_id)}
            ]
            assert [item["product"]["id"] for item in entries] == [
                str(owner_pending_id),
                str(other_pending_id),
            ]
            assert entries[1]["submission"] == {"id": str(submission_ids[1]), "productVersion": 3}
            assert entries[1]["possibleDuplicate"] is True
            assert entries[1]["founderSuspended"] is True
            staff_detail = query(
                client,
                f'query {{ reviewProduct(id: "{other_pending_id}") '
                "{ submission { id productVersion } product { summary { id } "
                "topics { displayName } assets { id url } } possibleDuplicate founderSuspended } }",
                staff_id,
            )
            review = staff_detail["data"]["reviewProduct"]
            assert review["product"]["topics"] == [{"displayName": topic_name.lower()}]
            assert review["product"]["assets"][0]["url"].startswith(
                f"/api/v1/products/{other_pending_id}/assets/{asset_id}?expires="
            )
            assert review["submission"]["productVersion"] == 3
            staff_draft = query(
                client,
                f'query {{ reviewProduct(id: "{owner_draft_id}") {{ submission {{ id }} }} }}',
                staff_id,
            )
            assert staff_draft["data"]["reviewProduct"] is None
            denied = query(client, "query { reviewQueue { items { product { id } } } }", owner_id)
            assert denied["data"] is None
            assert denied["errors"]
            profile = query(
                client,
                f'query {{ publicProfile(accountId: "{staff_id}") '
                "{ accountId displayName bio links photoUrl } }",
            )
            assert profile["data"]["publicProfile"] == {
                "accountId": str(staff_id),
                "displayName": "Reviewer",
                "bio": "Reviews new launches",
                "links": ["https://example.test"],
                "photoUrl": f"/api/v1/profiles/{staff_id}/photo",
            }
            viewer_profile = query(
                client,
                "query { viewerProfile { accountId displayName bio links photoUrl "
                "visibility version } }",
                staff_id,
            )
            assert viewer_profile["data"]["viewerProfile"] == {
                **profile["data"]["publicProfile"],
                "visibility": "public",
                "version": 2,
            }
            for unsafe in (
                "mutation { viewerProducts { nextCursor } }",
                "query { __schema { queryType { name } } }",
                "query { renamed: viewerProducts { nextCursor } }",
                "query { viewerProducts { items { ...Fields } } } "
                "fragment Fields on ProductSummary { id }",
                "query { hiddenProduct { id } }",
                "query { viewerProducts { items { nested { nested { nested { "
                "nested { id } } } } } } }",
                "query { viewerProducts { items { id } } } " + " " * 8192,
            ):
                rejected = client.post("/api/v1/graphql", json={"query": unsafe})
                assert rejected.status_code == 400
                assert rejected.json() == {"detail": "query is not allowed"}
            oversized_body = client.post(
                "/api/v1/graphql",
                json={
                    "query": "query { topicChoices { id } }",
                    "variables": {"padding": "x" * 17000},
                },
            )
            assert oversized_body.status_code == 400
            oversized_page = query(
                client,
                "query { viewerProducts(first: 51) { nextCursor } }",
                owner_id,
            )
            assert oversized_page["data"] is None
            assert oversized_page["errors"][0]["message"] == "invalid product query"
            assert client.get("/api/v1/graphql").status_code == 405
            asyncio.run(withdraw_other())
            withdrawn = query(
                client,
                f'query {{ reviewProduct(id: "{other_pending_id}") {{ submission {{ id }} }} }}',
                staff_id,
            )
            assert withdrawn["data"]["reviewProduct"] is None
            owner_after_withdrawal = query(
                client,
                f'query {{ viewerProduct(id: "{other_pending_id}") '
                "{ summary { status } submission { id } } }",
                other_id,
            )
            assert owner_after_withdrawal["data"]["viewerProduct"] == {
                "summary": {"status": "draft"},
                "submission": None,
            }
    finally:
        asyncio.run(cleanup())
        asyncio.run(route_database.close())
        redis.close()
