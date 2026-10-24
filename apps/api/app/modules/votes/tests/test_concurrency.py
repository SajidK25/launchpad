"""Guard the database serialization primitive used by vote commands."""

from __future__ import annotations

import asyncio
from typing import Any, cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.votes.repository import VoteRepository


class _Session:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any]] = []

    async def execute(self, statement: Any, params: Any) -> None:
        self.calls.append((statement, params))


def test_member_product_commands_use_transaction_scoped_pair_lock() -> None:
    async def verify() -> None:
        session, repository = _Session(), VoteRepository()
        member_id, product_id = uuid4(), uuid4()
        await repository.lock_member_product(
            cast(AsyncSession, session), member_id=member_id, product_id=product_id
        )
        statement, params = session.calls[0]
        assert "pg_advisory_xact_lock" in str(statement)
        assert params == {"member_id": str(member_id), "product_id": str(product_id)}

    asyncio.run(verify())


def test_member_idempotency_key_is_serialized_across_product_commands() -> None:
    async def verify() -> None:
        session, repository = _Session(), VoteRepository()
        member_id = uuid4()
        await repository.lock_idempotency_key(
            cast(AsyncSession, session), member_id=member_id, idempotency_key="same-key"
        )
        statement, params = session.calls[0]
        assert "pg_advisory_xact_lock" in str(statement)
        assert params == {"member_id": str(member_id), "idempotency_key": "same-key"}

    asyncio.run(verify())
