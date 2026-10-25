"""Database serialization tests for concurrent vote commands."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from app.modules.auth.models import Account
from app.modules.auth.staff import AccountState
from app.modules.products.models import Product
from app.modules.votes.models import Vote
from app.modules.votes.policies import VoteConflictError
from app.modules.votes.repository import VoteRepository
from app.modules.votes.service import VoteService
from app.shared.db.database import Database, _alembic_config
from sqlalchemy import Connection, delete, func, select, text
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

            async def cast_again() -> str:
                async with session_factory() as session:
                    try:
                        async with session.begin():
                            await service.cast(
                                session,
                                member_id=member_id,
                                product_id=product_id,
                                idempotency_key="cast-withdraw-race",
                            )
                        return "accepted"
                    except VoteConflictError:
                        return "conflict"

            async def withdraw_racing() -> str:
                async with session_factory() as session:
                    try:
                        async with session.begin():
                            await service.withdraw(
                                session,
                                member_id=member_id,
                                product_id=product_id,
                                idempotency_key="withdraw-cast-race",
                            )
                        return "accepted"
                    except VoteConflictError:
                        return "conflict"

            race_results = await asyncio.gather(cast_again(), withdraw_racing())
            assert race_results[1] == "accepted"
            expected_active = int(race_results[0] == "accepted")
            async with session_factory() as session:
                active_count = await session.scalar(
                    select(func.count()).select_from(Vote).where(Vote.state == "active")
                )
                assert active_count == expected_active

            if expected_active == 0:
                async with session_factory() as session, session.begin():
                    await service.cast(
                        session,
                        member_id=member_id,
                        product_id=product_id,
                        idempotency_key="restore-after-race",
                    )

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
                assert active_count == 1 and receipt_count == 3
        finally:
            await database.close()

    asyncio.run(verify())


def test_live_score_aggregate_ranks_newer_equal_count_votes_higher(
    integration_settings_fixture: Any,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        launch_date = date(2026, 10, 24)
        start = datetime(2026, 10, 24, 0, tzinfo=UTC)
        owners = (uuid4(), uuid4())
        voters = (uuid4(), uuid4())
        products = (uuid4(), uuid4())
        initialized = False
        try:
            await database.prepare()
            initialized = True
            async with database.engine.begin() as connection:
                for index, account_id in enumerate((*owners, *voters)):
                    await connection.execute(
                        text(
                            "INSERT INTO accounts "
                            "(id,email_display,email_key,password_hash,verified_at,role,"
                            "created_at,updated_at) "
                            "VALUES (:id,:email,:email,'hash',:now,'member',:now,:now)"
                        ),
                        {
                            "id": account_id,
                            "email": f"score-{index}@vote.test",
                            "now": start,
                        },
                    )
                for index, product_id in enumerate(products):
                    await connection.execute(
                        text(
                            "INSERT INTO products "
                            "(id,founder_id,status,version,name,pitch,description,"
                            "website_url,website_key,launched_at,created_at,updated_at) "
                            "VALUES (:id,:owner,'launched',0,:name,'Pitch','Description',"
                            ":url,:key,:now,:now,:now)"
                        ),
                        {
                            "id": product_id,
                            "owner": owners[index],
                            "name": f"Score target {index}",
                            "url": f"https://score-{index}.test",
                            "key": f"score-{index}.test",
                            "now": start,
                        },
                    )
                for index, (voter_id, product_id) in enumerate(zip(voters, products, strict=True)):
                    await connection.execute(
                        text(
                            "INSERT INTO votes (id,member_id,product_id,cast_at,state) "
                            "VALUES (:id,:member,:product,:cast_at,'active')"
                        ),
                        {
                            "id": uuid4(),
                            "member": voter_id,
                            "product": product_id,
                            "cast_at": start + timedelta(hours=2 if index == 0 else 18),
                        },
                    )

            session_factory = async_sessionmaker(database.engine, expire_on_commit=False)
            async with session_factory() as session:
                values = await VoteRepository(
                    score_half_life_seconds=6 * 60 * 60
                ).ranking_values_for_products(
                    session, product_ids=products, launch_date=launch_date
                )
            older_count, older_score = values[products[0]]
            newer_count, newer_score = values[products[1]]
            assert older_count == newer_count == 1
            assert newer_score > older_score
        finally:
            if initialized:
                async with database.engine.begin() as connection:
                    await connection.execute(delete(Vote).where(Vote.product_id.in_(products)))
                    await connection.execute(delete(Product).where(Product.id.in_(products)))
                    await connection.execute(
                        delete(Account).where(Account.id.in_((*owners, *voters)))
                    )
            await database.close()

    asyncio.run(verify())
