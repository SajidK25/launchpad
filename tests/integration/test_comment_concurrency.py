"""PostgreSQL serialization checks for discussion safeguards."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

from alembic import command
from app.modules.auth.models import Account
from app.modules.auth.staff import AccountState
from app.modules.comments.models import Comment, CommentIdempotencyReceipt
from app.modules.comments.policies import CommentForbiddenError, CommentRateLimitError
from app.modules.comments.repository import CommentRepository
from app.modules.comments.service import CommentService
from app.modules.products.models import Product
from app.modules.users.comment_attribution import CommentAttributionService
from app.modules.users.models import Profile
from app.modules.users.repository import ProfileRepository
from app.modules.users.service import (
    MemberIdentity,
    ProfileAttributionConflictError,
    ProfileService,
)
from app.shared.db.database import Database, _alembic_config
from app.shared.events.models import OutboxMessage
from app.shared.events.outbox import OutboxRepository
from sqlalchemy import Connection, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _Accounts:
    async def current_account(
        self, session: AsyncSession, account_id: UUID, *, lock: bool = False
    ) -> AccountState | None:
        statement = select(Account).where(Account.id == account_id)
        if lock:
            statement = statement.with_for_update()
        account = await session.scalar(statement)
        if account is None:
            return None
        return AccountState(
            account_id=account.id,
            verified=account.verified_at is not None,
            role=account.role,
            suspended_at=account.suspended_at,
        )


class _Attribution:
    async def batch(self, _session: AsyncSession, account_ids: tuple[UUID, ...]) -> dict[UUID, Any]:
        return {
            account_id: type(
                "Attribution",
                (),
                {
                    "account_id": account_id,
                    "display_name": "Race author",
                    "has_photo": True,
                    "public_profile_url": None,
                },
            )()
            for account_id in account_ids
        }


class _Products:
    async def discussion_context(
        self, session: AsyncSession, *, product_id: UUID, lock: bool = False
    ) -> Any | None:
        statement = select(Product).where(Product.id == product_id)
        if lock:
            statement = statement.with_for_update()
        product = await session.scalar(statement)
        if product is None or product.status != "launched" or product.launched_at is None:
            return None
        return type("DiscussionContext", (), {"product_id": product.id})()


class _Codec:
    def encode(self, payload: Any) -> tuple[str, bytes]:
        return "test", repr(sorted(payload.items())).encode()


class _ProfileMembers:
    async def get_member(
        self, session: AsyncSession, account_id: UUID, *, lock: bool = False
    ) -> MemberIdentity | None:
        statement = select(Account).where(Account.id == account_id)
        if lock:
            statement = statement.with_for_update()
        account = await session.scalar(statement)
        if account is None:
            return None
        return MemberIdentity(
            account_id=account.id,
            email_display=account.email_display,
            verified=account.verified_at is not None,
        )


class _NoopOutbox:
    async def add(self, _session: AsyncSession, _event: Any) -> UUID:
        return uuid4()


def _upgrade(sync_connection: Connection) -> None:
    config = _alembic_config()
    config.attributes["connection"] = sync_connection
    command.upgrade(config, "head")


def test_concurrent_posts_enforce_exact_account_limit_and_atomic_effect(
    integration_settings_fixture: Any,
    reset_database: None,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        author_id, owner_id, product_id = uuid4(), uuid4(), uuid4()
        now = datetime(2026, 10, 24, 12, tzinfo=UTC)
        try:
            async with database.engine.begin() as connection:
                await connection.run_sync(_upgrade)
                for account_id, email in (
                    (author_id, "comment-author@example.test"),
                    (owner_id, "comment-owner@example.test"),
                ):
                    await connection.execute(
                        text(
                            "INSERT INTO accounts "
                            "(id,email_display,email_key,password_hash,verified_at,role,"
                            "created_at,updated_at) "
                            "VALUES (:id,:email,:email,'hash',:now,'member',:now,:now)"
                        ),
                        {"id": account_id, "email": email, "now": now},
                    )
                await connection.execute(
                    text(
                        "INSERT INTO products "
                        "(id,founder_id,status,version,name,pitch,description,website_url,"
                        "website_key,launched_at,created_at,updated_at) VALUES "
                        "(:id,:owner,'launched',0,'Comments target','Pitch','Description',"
                        "'https://comments-race.test','comments-race.test',:now,:now,:now)"
                    ),
                    {"id": product_id, "owner": owner_id, "now": now},
                )

            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            service = CommentService(
                account_access=cast(Any, _Accounts()),
                attribution_access=cast(Any, _Attribution()),
                product_access=cast(Any, _Products()),
                repository=CommentRepository(),
                outbox=OutboxRepository(),
                codec=cast(Any, _Codec()),
                writes_enabled=lambda: True,
                clock=lambda: now,
            )

            async def post(index: int) -> str:
                async with sessions() as session:
                    try:
                        async with session.begin():
                            await service.create_root(
                                session,
                                author_id=author_id,
                                product_id=product_id,
                                body=f"Concurrent body {index}",
                                idempotency_key=f"concurrent-{index}",
                            )
                        return "accepted"
                    except CommentRateLimitError:
                        return "limited"

            outcomes = await asyncio.gather(*(post(index) for index in range(6)))
            assert sorted(outcomes) == ["accepted"] * 5 + ["limited"]
            async with sessions() as session:
                comment_count = await session.scalar(select(func.count()).select_from(Comment))
                receipt_count = await session.scalar(
                    select(func.count()).select_from(CommentIdempotencyReceipt)
                )
                outbox_count = await session.scalar(
                    select(func.count())
                    .select_from(OutboxMessage)
                    .where(OutboxMessage.event_type == "comment.created.v1")
                )
                assert comment_count == receipt_count == outbox_count == 5
        finally:
            await database.close()

    asyncio.run(verify())


def test_profile_clear_and_post_share_the_authoritative_account_lock(
    integration_settings_fixture: Any,
    reset_database: None,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        author_id, owner_id, product_id, upload_id = uuid4(), uuid4(), uuid4(), uuid4()
        now = datetime(2026, 10, 24, 14, tzinfo=UTC)
        photo_key = f"profile-clean/{author_id.hex}/{upload_id.hex}"
        try:
            async with database.engine.begin() as connection:
                await connection.run_sync(_upgrade)
                for account_id, email in (
                    (author_id, "profile-race-author@example.test"),
                    (owner_id, "profile-race-owner@example.test"),
                ):
                    await connection.execute(
                        text(
                            "INSERT INTO accounts "
                            "(id,email_display,email_key,password_hash,verified_at,role,"
                            "created_at,updated_at) VALUES "
                            "(:id,:email,:email,'hash',:now,'member',:now,:now)"
                        ),
                        {"id": account_id, "email": email, "now": now},
                    )
                await connection.execute(
                    text(
                        "INSERT INTO profiles "
                        "(account_id,display_name,bio,photo_key,visibility,version) VALUES "
                        "(:account,'Race author','Builder',:photo,'private',0)"
                    ),
                    {"account": author_id, "photo": photo_key},
                )
                await connection.execute(
                    text(
                        "INSERT INTO photo_uploads "
                        "(id,account_id,staging_key,clean_key,expires_at,state,byte_count,"
                        "media_type) VALUES "
                        "(:id,:account,:staging,:clean,:now,'cleaned',128,'image/png')"
                    ),
                    {
                        "id": upload_id,
                        "account": author_id,
                        "staging": f"profile-staging/{author_id.hex}/{upload_id.hex}",
                        "clean": photo_key,
                        "now": now,
                    },
                )
                await connection.execute(
                    text(
                        "INSERT INTO products "
                        "(id,founder_id,status,version,name,pitch,description,website_url,"
                        "website_key,launched_at,created_at,updated_at) VALUES "
                        "(:id,:owner,'launched',0,'Profile race','Pitch','Description',"
                        "'https://profile-race.test','profile-race.test',:now,:now,:now)"
                    ),
                    {"id": product_id, "owner": owner_id, "now": now},
                )

            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            repository = ProfileRepository()
            attribution = CommentAttributionService(
                repository=repository, storage=SimpleNamespace()
            )
            comments = CommentService(
                account_access=cast(Any, _Accounts()),
                attribution_access=attribution,
                product_access=cast(Any, _Products()),
                repository=CommentRepository(),
                outbox=OutboxRepository(),
                codec=cast(Any, _Codec()),
                writes_enabled=lambda: True,
                clock=lambda: now,
            )
            profiles = ProfileService(
                repository=repository,
                member_access=cast(Any, _ProfileMembers()),
                outbox_repository=cast(Any, _NoopOutbox()),
                payload_codec=cast(Any, _Codec()),
                mail_web_origin="https://launchpad.example",
                comment_activity=comments,
                clock=lambda: now,
            )

            async def clear_profile() -> str:
                async with sessions() as session:
                    try:
                        async with session.begin():
                            await profiles.update_profile(
                                session,
                                actor_id=author_id,
                                display_name=None,
                                photo_key=None,
                            )
                        return "cleared"
                    except ProfileAttributionConflictError:
                        return "conflict"

            async def publish_comment() -> str:
                async with sessions() as session:
                    try:
                        async with session.begin():
                            await comments.create_root(
                                session,
                                author_id=author_id,
                                product_id=product_id,
                                body="Race-safe attribution",
                                idempotency_key="profile-clear-race",
                            )
                        return "posted"
                    except CommentForbiddenError:
                        return "forbidden"

            outcome = await asyncio.gather(clear_profile(), publish_comment())
            assert tuple(outcome) in {("cleared", "forbidden"), ("conflict", "posted")}

            async with sessions() as session:
                profile = await session.get(Profile, author_id)
                comment_count = await session.scalar(
                    select(func.count())
                    .select_from(Comment)
                    .where(Comment.author_account_id == author_id)
                )
                assert profile is not None
                if comment_count == 0:
                    assert profile.display_name is None and profile.photo_key is None
                else:
                    assert comment_count == 1
                    assert profile.display_name == "Race author" and profile.photo_key == photo_key
        finally:
            await database.close()

    asyncio.run(verify())
