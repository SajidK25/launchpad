"""Unit checks for repository-level persistence boundaries."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import BindParameter
from sqlalchemy.sql.visitors import iterate

from app.modules.votes.repository import VoteRepository


class _Session:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flushed = 0
        self.executed: list[tuple[Any, Any]] = []
        self.statements: list[Any] = []

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flushed += 1

    async def scalars(self, statement: Any) -> Any:
        self.statements.append(statement)
        return SimpleNamespace(one=lambda: SimpleNamespace(id=uuid4()))

    async def execute(self, statement: Any, params: Any = None) -> None:
        self.executed.append((statement, params))


def test_create_vote_adds_active_history_and_flushes_in_callers_transaction() -> None:
    async def verify() -> None:
        session, repository = _Session(), VoteRepository()
        member_id, product_id = uuid4(), uuid4()
        now = datetime.now(UTC)
        vote = await repository.create_vote(
            cast(AsyncSession, session), member_id=member_id, product_id=product_id, cast_at=now
        )
        assert vote.id is not None
        assert "INSERT INTO votes" in str(session.statements[0])
        assert session.flushed == 0

    asyncio.run(verify())


def test_first_voting_enabled_date_is_inserted_without_replacing_existing_state() -> None:
    async def verify() -> None:
        session, repository = _Session(), VoteRepository()
        now = datetime.now(UTC)
        await repository.ensure_voting_enabled_from(
            cast(AsyncSession, session), enabled_from=now.date(), now=now
        )
        statement, params = session.executed[0]
        assert "ON CONFLICT (singleton_id) DO NOTHING" in str(statement)
        assert params == {"enabled_from": now.date(), "created_at": now}

    asyncio.run(verify())


def test_live_and_snapshot_score_queries_share_the_configured_half_life() -> None:
    class Rows:
        def one(self) -> tuple[int, int]:
            return (0, 0)

        def __iter__(self) -> Any:
            return iter(())

    class RankingSession:
        def __init__(self) -> None:
            self.statements: list[Any] = []

        async def execute(self, statement: Any) -> Rows:
            self.statements.append(statement)
            return Rows()

    async def verify() -> None:
        from datetime import date

        from app.modules.votes.repository import VoteRepository

        session = RankingSession()
        repository = VoteRepository(score_half_life_seconds=3600)
        product_id = uuid4()
        await repository.ranking_values(
            cast(AsyncSession, session), product_id=product_id, launch_date=date(2026, 10, 24)
        )
        await repository.ranking_values_for_products(
            cast(AsyncSession, session),
            product_ids=(product_id,),
            launch_date=date(2026, 10, 24),
        )
        await repository.snapshot_values_for_products(
            cast(AsyncSession, session),
            product_ids=(product_id,),
            cutoff_at=datetime(2026, 10, 25, tzinfo=UTC),
        )

        assert len(session.statements) == 3
        for statement in session.statements:
            assert any(
                isinstance(node, BindParameter) and node.value == 3600
                for node in iterate(statement)
            )

    asyncio.run(verify())
