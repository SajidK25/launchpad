"""Database serialization tests for concurrent vote commands."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from app.modules.auth.staff import AccountState
from app.modules.votes.models import Vote
from app.modules.votes.policies import VoteConflictError
from app.modules.votes.repository import VoteRepository
from app.modules.votes.service import VoteService
from app.shared.db.database import Database, _alembic_config
from sqlalchemy import Connection, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker


class _Members:
    def __init__(self, member_id: UUID) -> None:
        self.member_id = member_id

    async def current_account(
        self, session: Any, account_id: UUID, *, lock: bool = False
    ) -> AccountState | None:
        if account_id != self.member_id:
            return None
        return AccountState(account_id, True, "member", None)


class _Products:
    def __init__(self, product_id: UUID, owner_id: UUID) -> None:
        self.product_id = product_id
        self.owner_id = owner_id

    async def voting_context(
        self, session: Any, *, product_id: UUID, lock: bool = False
    ) -> Any | None:
        if product_id != self.product_id:
            return None
        return type(
            "VotingContext",
            (),
            {
                "product_id": product_id,
                "owner_account_id": self.owner_id,
                "launch_date": date(2026, 10, 24),
                "launched": True,
            },
        )()


class _Codec:
    def encode(self, payload: Any) -> tuple[str, bytes]:
        return "test", repr(payload).encode()


class _Outbox:
    async def add(self, session: Any, event: Any) -> UUID:
        return uuid4()


class _FailingOutbox:
    async def add(self, session: Any, event: Any) -> UUID:
        raise RuntimeError("outbox unavailable")


def _upgrade(sync_connection: Connection) -> None:
    config = _alembic_config()
    config.attributes["connection"] = sync_connection
    command.upgrade(config, "head")


def test_concurrent_casts_leave_at_most_one_active_vote(
    integration_settings_fixture: Any,
    reset_database: None,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        member_id, owner_id, product_id = uuid4(), uuid4(), uuid4()
        now = datetime(2026, 10, 24, 12, tzinfo=UTC)
        try:
            async with database.engine.begin() as connection:
                await connection.run_sync(_upgrade)
                for account_id, email in ((member_id, "race-voter"), (owner_id, "race-owner")):
                    await connection.execute(
                        text(
                            "INSERT INTO accounts "
                            "(id,email_display,email_key,password_hash,verified_at,role,"
                            "created_at,updated_at) "
                            "VALUES (:id,:email,:email,'hash',:now,'member',:now,:now)"
                        ),
                        {"id": account_id, "email": f"{email}@vote.test", "now": now},
                    )
                await connection.execute(
                    text(
                        "INSERT INTO products (id,founder_id,status,version,name,pitch,description,"
                        "website_url,website_key,launched_at,created_at,updated_at) "
                        "VALUES (:id,:owner,'launched',0,'Race target','Pitch','Description',"
                        "'https://race.test','race.test',:now,:now,:now)"
                    ),
                    {"id": product_id, "owner": owner_id, "now": now},
                )

            session_factory = async_sessionmaker(database.engine, expire_on_commit=False)
            service = VoteService(
                member_access=cast(Any, _Members(member_id)),
                product_access=cast(Any, _Products(product_id, owner_id)),
                repository=VoteRepository(),
                outbox=cast(Any, _Outbox()),
                codec=cast(Any, _Codec()),
                writes_enabled=lambda: True,
                clock=lambda: now,
            )

            async def cast_once(key: str) -> str:
                async with session_factory() as session:
                    try:
                        async with session.begin():
                            await service.cast(
                                session,
                                member_id=member_id,
                                product_id=product_id,
                                idempotency_key=key,
                            )
                        return "accepted"
                    except VoteConflictError:
                        return "conflict"

            results = await asyncio.gather(cast_once("race-a"), cast_once("race-b"))
            assert sorted(results) == ["accepted", "conflict"]
            async with session_factory() as session:
                active_count = await session.scalar(
                    select(func.count()).select_from(Vote).where(Vote.state == "active")
                )
                assert active_count == 1

            service.outbox = cast(Any, _FailingOutbox())
            with pytest.raises(RuntimeError, match="outbox unavailable"):
                async with session_factory() as session:
                    async with session.begin():
                        await service.withdraw(
                            session,
                            member_id=member_id,
                            product_id=product_id,
                            idempotency_key="rollback-withdrawal",
                        )
            async with session_factory() as session:
                active_count = await session.scalar(
                    select(func.count()).select_from(Vote).where(Vote.state == "active")
                )
                receipt_count = await session.scalar(
                    text("SELECT count(*) FROM vote_idempotency_receipts")
                )
                assert active_count == 1 and receipt_count == 1
        finally:
            await database.close()

    asyncio.run(verify())
