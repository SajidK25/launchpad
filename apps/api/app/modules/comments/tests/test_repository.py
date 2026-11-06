"""Bounded SQL persistence and cursor behavior for discussions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.comments.repository import CommentRepository


class _Rows:
    def __init__(self, values: list[Any]) -> None:
        self.values = values

    def all(self) -> list[Any]:
        return self.values


class _Session:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self.rows = rows or []
        self.statements: list[Any] = []
        self.params: list[Any] = []

    async def execute(self, statement: Any, params: Any = None) -> _Rows:
        self.statements.append(statement)
        self.params.append(params)
        return _Rows(self.rows)

    async def scalars(self, statement: Any) -> Any:
        self.statements.append(statement)
        return SimpleNamespace(
            one=lambda: SimpleNamespace(id=uuid4()),
            all=lambda: self.rows,
        )

    async def scalar(self, statement: Any) -> Any:
        self.statements.append(statement)
        return None


def test_root_and_reply_queries_are_bounded_and_use_compound_cursors() -> None:
    async def verify() -> None:
        repository = CommentRepository()
        product_id, parent_id = uuid4(), uuid4()
        now = datetime(2026, 10, 24, 12, tzinfo=UTC)
        rows = [SimpleNamespace(id=uuid4(), created_at=now) for _ in range(3)]
        root_session = _Session(rows)
        roots, next_cursor = await repository.list_roots(
            cast(AsyncSession, root_session), product_id=product_id, limit=2
        )
        assert len(roots) == 2 and next_cursor is not None
        root_sql = str(root_session.statements[0])
        assert "comments.depth =" in root_sql and "LIMIT" in root_sql
        resumed = _Session([])
        await repository.list_roots(
            cast(AsyncSession, resumed),
            product_id=product_id,
            limit=2,
            after=next_cursor,
        )
        assert "comments.created_at <" in str(resumed.statements[0])

        reply_session = _Session(rows)
        replies, earlier_cursor = await repository.list_replies(
            cast(AsyncSession, reply_session),
            product_id=product_id,
            parent_id=parent_id,
            limit=2,
        )
        assert len(replies) == 2 and earlier_cursor is not None
        assert tuple(item.id for item in reversed(rows[:2])) == tuple(reply.id for reply in replies)

    asyncio.run(verify())


def test_safeguard_queries_are_author_and_product_scoped() -> None:
    async def verify() -> None:
        repository, session = CommentRepository(), _Session([])
        author_id, product_id = uuid4(), uuid4()
        now = datetime(2026, 10, 24, 12, tzinfo=UTC)
        await repository.author_activity(
            cast(AsyncSession, session), author_id=author_id, since=now
        )
        await repository.has_recent_duplicate(
            cast(AsyncSession, session),
            author_id=author_id,
            product_id=product_id,
            body_fingerprint="a" * 64,
            since=now,
        )
        activity_sql, duplicate_sql = map(str, session.statements)
        assert "author_account_id" in activity_sql and "created_at" in activity_sql
        assert all(
            name in duplicate_sql
            for name in ("author_account_id", "product_id", "body_fingerprint", "created_at")
        )

    asyncio.run(verify())
