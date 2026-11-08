"""PostgreSQL-backed public discussion GraphQL reads."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import strawberry
from alembic import command
from app.modules.auth.staff import AuthAccessService
from app.modules.comments.graphql import CommentQuery
from app.modules.comments.models import Comment
from app.modules.comments.repository import CommentRepository
from app.modules.comments.service import CommentService
from app.modules.products.models import Product
from app.modules.products.service import ProductService
from app.modules.users.comment_attribution import CommentAttributionService
from app.modules.users.models import PhotoUpload, Profile
from app.shared.db.database import Database, _alembic_config
from conftest import IntegrationSettings
from sqlalchemy import Connection, insert, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7


class _Codec:
    def encode(self, _payload: object) -> tuple[str, bytes]:
        return "unused", b"unused"


class _Storage:
    async def get_private(self, *, object_key: str) -> tuple[bytes, str | None]:
        raise AssertionError(f"read projection must not fetch image bytes: {object_key}")


def _upgrade(sync_connection: Connection) -> None:
    config = _alembic_config()
    config.attributes["connection"] = sync_connection
    command.upgrade(config, "head")


def _comment(
    *,
    product_id: UUID,
    author_id: UUID,
    body: str,
    created_at: datetime,
    parent_id: UUID | None = None,
) -> Comment:
    return Comment(
        id=uuid7(),
        product_id=product_id,
        author_account_id=author_id,
        depth=1 if parent_id is not None else 0,
        parent_id=parent_id,
        parent_depth=0 if parent_id is not None else None,
        body=body,
        body_fingerprint=hashlib.sha256(body.encode()).hexdigest(),
        moderation_status="visible",
        created_at=created_at,
    )


async def _insert_comments(session: AsyncSession, comments: list[Comment]) -> None:
    await session.execute(
        text(
            "INSERT INTO comments "
            "(id,product_id,author_account_id,depth,parent_id,parent_depth,body,"
            "body_fingerprint,moderation_status,created_at) VALUES "
            "(:id,:product_id,:author_account_id,:depth,:parent_id,:parent_depth,:body,"
            ":body_fingerprint,:moderation_status,:created_at)"
        ),
        [
            {
                "id": comment.id,
                "product_id": comment.product_id,
                "author_account_id": comment.author_account_id,
                "depth": comment.depth,
                "parent_id": comment.parent_id,
                "parent_depth": comment.parent_depth,
                "body": comment.body,
                "body_fingerprint": comment.body_fingerprint,
                "moderation_status": comment.moderation_status,
                "created_at": comment.created_at,
            }
            for comment in comments
        ],
    )


def test_public_discussion_pages_are_bounded_stable_and_hide_private_context(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        now = datetime(2026, 10, 25, 12, tzinfo=UTC)
        author_ids = (uuid4(), uuid4())
        owner_id = uuid4()
        public_product_id, private_product_id, other_product_id = uuid4(), uuid4(), uuid4()
        try:
            async with database.engine.begin() as connection:
                await connection.run_sync(_upgrade)
                for account_id in (*author_ids, owner_id):
                    await connection.execute(
                        text(
                            "INSERT INTO accounts "
                            "(id,email_display,email_key,password_hash,verified_at,role,"
                            "created_at,updated_at) VALUES "
                            "(:id,:email,:email,'hash',:now,'member',:now,:now)"
                        ),
                        {
                            "id": account_id,
                            "email": f"{account_id}@comments.test",
                            "now": now,
                        },
                    )
                for product_id, status, launched_at in (
                    (public_product_id, "launched", now),
                    (private_product_id, "approved", None),
                    (other_product_id, "launched", now),
                ):
                    await connection.execute(
                        insert(Product).values(
                            id=product_id,
                            founder_id=owner_id,
                            status=status,
                            version=1,
                            name=f"Product {product_id}",
                            pitch="Pitch",
                            description="Description",
                            website_url=f"https://{product_id}.comments.test",
                            website_key=f"{product_id}.comments.test",
                            launched_at=launched_at,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                for index, author_id in enumerate(author_ids):
                    photo_key = f"profile-clean/{author_id}/photo"
                    await connection.execute(
                        insert(Profile).values(
                            account_id=author_id,
                            display_name=f"Current Author {index}",
                            bio="Builder",
                            photo_key=photo_key,
                            visibility="public" if index == 0 else "private",
                            published_at=now if index == 0 else None,
                            version=1,
                        )
                    )
                    await connection.execute(
                        insert(PhotoUpload).values(
                            id=uuid4(),
                            account_id=author_id,
                            staging_key=f"profile-staging/{author_id}/photo",
                            clean_key=photo_key,
                            expires_at=now + timedelta(days=1),
                            state="cleaned",
                            byte_count=128,
                            media_type="image/png",
                        )
                    )

            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            roots = [
                _comment(
                    product_id=public_product_id,
                    author_id=author_ids[index % 2],
                    body=f"Root {index}",
                    created_at=now + timedelta(minutes=index),
                )
                for index in range(22)
            ]
            replies = [
                _comment(
                    product_id=public_product_id,
                    author_id=author_ids[index % 2],
                    body=f"Reply {index}",
                    created_at=now + timedelta(hours=1, minutes=index),
                    parent_id=roots[-1].id,
                )
                for index in range(5)
            ]
            wrong_product_root = _comment(
                product_id=other_product_id,
                author_id=author_ids[0],
                body="Other product root",
                created_at=now,
            )
            async with sessions() as session, session.begin():
                await _insert_comments(session, [*roots, wrong_product_root])
                await _insert_comments(session, replies)

            product_service = ProductService(
                member_access=AuthAccessService(), payload_codec=cast(Any, _Codec())
            )
            attribution = CommentAttributionService(storage=cast(Any, _Storage()))
            comments = CommentService(
                account_access=cast(Any, AuthAccessService()),
                attribution_access=attribution,
                product_access=product_service,
                repository=CommentRepository(),
                codec=cast(Any, _Codec()),
                writes_enabled=lambda: False,
            )

            @asynccontextmanager
            async def session_factory() -> AsyncIterator[AsyncSession]:
                async with sessions() as session:
                    yield session

            context = {
                "request_id": "comments-integration",
                "session_factory": session_factory,
                "comment_service_factory": lambda: comments,
            }
            schema = strawberry.Schema(query=CommentQuery)

            async def execute(query: str) -> dict[str, Any]:
                result = await schema.execute(query, context_value=context)
                assert result.errors is None
                return cast(dict[str, Any], result.data)

            first = await execute(
                f'query {{ productDiscussion(productId: "{public_product_id}") '
                "{ items { id body replyCount replies { body } author { displayName "
                "avatarUrl publicProfileUrl } } nextCursor } }"
            )
            first_page = first["productDiscussion"]
            assert len(first_page["items"]) == 20
            assert [item["body"] for item in first_page["items"][:2]] == [
                "Root 21",
                "Root 20",
            ]
            newest = first_page["items"][0]
            assert newest["replyCount"] == 5
            assert [reply["body"] for reply in newest["replies"]] == [
                "Reply 2",
                "Reply 3",
                "Reply 4",
            ]
            assert newest["author"]["avatarUrl"].startswith(
                f"/api/v1/products/{public_product_id}/comment-authors/"
            )

            async with sessions() as session, session.begin():
                await _insert_comments(
                    session,
                    [
                        _comment(
                            product_id=public_product_id,
                            author_id=author_ids[0],
                            body="Concurrent root",
                            created_at=now + timedelta(days=1),
                        )
                    ],
                )
            second = await execute(
                f'query {{ productDiscussion(productId: "{public_product_id}", '
                f'after: "{first_page["nextCursor"]}") '
                "{ items { id body } nextCursor } }"
            )
            assert [item["body"] for item in second["productDiscussion"]["items"]] == [
                "Root 1",
                "Root 0",
            ]

            reply_page = await execute(
                f'query {{ commentReplies(productId: "{public_product_id}", '
                f'parentId: "{roots[-1].id}", first: 2) '
                "{ items { body } earlierCursor } }"
            )
            assert [item["body"] for item in reply_page["commentReplies"]["items"]] == [
                "Reply 3",
                "Reply 4",
            ]
            assert reply_page["commentReplies"]["earlierCursor"] is not None

            for query in (
                f'query {{ productDiscussion(productId: "{private_product_id}") '
                "{ items { id } } }",
                f'query {{ commentReplies(productId: "{public_product_id}", '
                f'parentId: "{wrong_product_root.id}") {{ items {{ id }} }} }}',
                f'query {{ commentReplies(productId: "{public_product_id}", '
                f'parentId: "{replies[0].id}") {{ items {{ id }} }} }}',
            ):
                result = await schema.execute(query, context_value=context)
                assert result.data is None
                assert result.errors
                assert isinstance(result.errors[0].original_error, Exception)
        finally:
            await database.close()

    asyncio.run(verify())
