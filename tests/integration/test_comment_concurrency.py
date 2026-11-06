"""PostgreSQL serialization checks for discussion safeguards."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from alembic import command
from app.modules.auth.models import Account
from app.modules.auth.staff import AccountState
from app.modules.comments.models import Comment, CommentIdempotencyReceipt
from app.modules.comments.policies import CommentRateLimitError
from app.modules.comments.repository import CommentRepository
from app.modules.comments.service import CommentService
from app.modules.products.models import Product
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
