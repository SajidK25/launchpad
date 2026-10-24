"""Unit checks for repository-level persistence boundaries."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

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
            session, member_id=member_id, product_id=product_id, cast_at=now
        )
        assert vote.id is not None
        assert "INSERT INTO votes" in str(session.statements[0])
        assert session.flushed == 0

    asyncio.run(verify())


def test_first_voting_enabled_date_is_inserted_without_replacing_existing_state() -> None:
    async def verify() -> None:
        session, repository = _Session(), VoteRepository()
        now = datetime.now(UTC)
        await repository.ensure_voting_enabled_from(session, enabled_from=now.date(), now=now)
        statement, params = session.executed[0]
        assert "ON CONFLICT (singleton_id) DO NOTHING" in str(statement)
        assert params == {"enabled_from": now.date(), "created_at": now}

    asyncio.run(verify())
