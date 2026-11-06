"""PostgreSQL persistence and bounded cursor reads for public discussion."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_, func, insert, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from uuid6 import uuid7

from app.modules.comments.models import Comment, CommentIdempotencyReceipt
from app.modules.comments.policies import CommentValidationError


@dataclass(frozen=True, slots=True)
class ReplySummary:
    """Bounded newest replies plus the complete count for one root."""

    count: int
    replies: tuple[Comment, ...]


class CommentRepository:
    """Own comment tables, safeguard queries, and deterministic pagination."""

    async def lock_idempotency_key(
        self, session: AsyncSession, *, author_id: UUID, idempotency_key: str
    ) -> None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:author), hashtext(:key))"),
            {"author": str(author_id), "key": idempotency_key},
        )

    async def get_receipt(
        self, session: AsyncSession, *, author_id: UUID, idempotency_key: str
    ) -> CommentIdempotencyReceipt | None:
        return cast(
            CommentIdempotencyReceipt | None,
            await session.scalar(
                select(CommentIdempotencyReceipt).where(
                    CommentIdempotencyReceipt.author_account_id == author_id,
                    CommentIdempotencyReceipt.idempotency_key == idempotency_key,
                )
            ),
        )

    async def comment_by_id(self, session: AsyncSession, *, comment_id: UUID) -> Comment | None:
        return cast(Comment | None, await session.get(Comment, comment_id))

    async def visible_root(
        self, session: AsyncSession, *, product_id: UUID, parent_id: UUID
    ) -> Comment | None:
        return cast(
            Comment | None,
            await session.scalar(
                select(Comment).where(
                    Comment.id == parent_id,
                    Comment.product_id == product_id,
                    Comment.depth == 0,
                    Comment.moderation_status == "visible",
                )
            ),
        )

    async def author_activity(
        self, session: AsyncSession, *, author_id: UUID, since: datetime
    ) -> tuple[datetime, ...]:
        values = await session.scalars(
            select(Comment.created_at)
            .where(
                Comment.author_account_id == author_id,
                Comment.created_at >= since,
                Comment.moderation_status == "visible",
            )
            .order_by(Comment.created_at, Comment.id)
        )
        return tuple(_utc(value) for value in values.all())

    async def has_recent_duplicate(
        self,
        session: AsyncSession,
        *,
        author_id: UUID,
        product_id: UUID,
        body_fingerprint: str,
        since: datetime,
    ) -> bool:
        value = await session.scalar(
            select(Comment.id)
            .where(
                Comment.author_account_id == author_id,
                Comment.product_id == product_id,
                Comment.body_fingerprint == body_fingerprint,
                Comment.created_at >= since,
                Comment.moderation_status == "visible",
            )
            .limit(1)
        )
        return value is not None

    async def create_comment(
        self,
        session: AsyncSession,
        *,
        product_id: UUID,
        author_id: UUID,
        depth: int,
        parent_id: UUID | None,
        body: str,
        body_fingerprint: str,
        created_at: datetime,
    ) -> Comment:
        return (
            await session.scalars(
                insert(Comment)
                .values(
                    id=uuid7(),
                    product_id=product_id,
                    author_account_id=author_id,
                    depth=depth,
                    parent_id=parent_id,
                    parent_depth=0 if depth == 1 else None,
                    body=body,
                    body_fingerprint=body_fingerprint,
                    moderation_status="visible",
                    created_at=created_at,
                )
                .returning(Comment)
            )
        ).one()

    async def add_receipt(
        self,
        session: AsyncSession,
        *,
        author_id: UUID,
        idempotency_key: str,
        request_fingerprint: str,
        comment_id: UUID,
        created_at: datetime,
    ) -> CommentIdempotencyReceipt:
        return (
            await session.scalars(
                insert(CommentIdempotencyReceipt)
                .values(
                    id=uuid7(),
                    author_account_id=author_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    comment_id=comment_id,
                    created_at=created_at,
                )
                .returning(CommentIdempotencyReceipt)
            )
        ).one()

    async def list_roots(
        self,
        session: AsyncSession,
        *,
        product_id: UUID,
        limit: int,
        after: str | None = None,
    ) -> tuple[tuple[Comment, ...], str | None]:
        statement = select(Comment).where(
            Comment.product_id == product_id,
            Comment.depth == 0,
            Comment.moderation_status == "visible",
        )
        if after is not None:
            created_at, comment_id = _decode_cursor(after)
            statement = statement.where(_older_than(created_at, comment_id))
        rows = list(
            (
                await session.scalars(
                    statement.order_by(Comment.created_at.desc(), Comment.id.desc()).limit(
                        limit + 1
                    )
                )
            ).all()
        )
        visible = tuple(rows[:limit])
        next_cursor = _encode_cursor(visible[-1]) if len(rows) > limit and visible else None
        return visible, next_cursor

    async def list_replies(
        self,
        session: AsyncSession,
        *,
        product_id: UUID,
        parent_id: UUID,
        limit: int,
        before: str | None = None,
    ) -> tuple[tuple[Comment, ...], str | None]:
        statement = select(Comment).where(
            Comment.product_id == product_id,
            Comment.parent_id == parent_id,
            Comment.depth == 1,
            Comment.moderation_status == "visible",
        )
        if before is not None:
            created_at, comment_id = _decode_cursor(before)
            statement = statement.where(_older_than(created_at, comment_id))
        rows = list(
            (
                await session.scalars(
                    statement.order_by(Comment.created_at.desc(), Comment.id.desc()).limit(
                        limit + 1
                    )
                )
            ).all()
        )
        newest_first = rows[:limit]
        visible = tuple(reversed(newest_first))
        earlier_cursor = (
            _encode_cursor(newest_first[-1]) if len(rows) > limit and newest_first else None
        )
        return visible, earlier_cursor

    async def reply_summaries(
        self, session: AsyncSession, *, product_id: UUID, parent_ids: tuple[UUID, ...]
    ) -> dict[UUID, ReplySummary]:
        if not parent_ids:
            return {}
        ranked = (
            select(
                Comment.id.label("comment_id"),
                Comment.parent_id.label("parent_id"),
                func.count().over(partition_by=Comment.parent_id).label("reply_count"),
                func.row_number()
                .over(
                    partition_by=Comment.parent_id,
                    order_by=(Comment.created_at.desc(), Comment.id.desc()),
                )
                .label("newest_rank"),
            )
            .where(
                Comment.product_id == product_id,
                Comment.parent_id.in_(parent_ids),
                Comment.depth == 1,
                Comment.moderation_status == "visible",
            )
            .subquery()
        )
        result = await session.execute(
            select(Comment, ranked.c.reply_count)
            .join(ranked, ranked.c.comment_id == Comment.id)
            .where(ranked.c.newest_rank <= 3)
            .order_by(Comment.parent_id, Comment.created_at, Comment.id)
        )
        grouped: dict[UUID, list[Comment]] = {parent_id: [] for parent_id in parent_ids}
        counts: dict[UUID, int] = {}
        for comment, count in result.all():
            if comment.parent_id is None:
                continue
            grouped[comment.parent_id].append(comment)
            counts[comment.parent_id] = int(count)
        return {
            parent_id: ReplySummary(
                count=counts.get(parent_id, 0), replies=tuple(grouped[parent_id])
            )
            for parent_id in parent_ids
        }

    async def has_visible_entries(self, session: AsyncSession, *, author_id: UUID) -> bool:
        value = await session.scalar(
            select(Comment.id)
            .where(
                Comment.author_account_id == author_id,
                Comment.moderation_status == "visible",
            )
            .limit(1)
        )
        return value is not None


def _older_than(created_at: datetime, comment_id: UUID) -> ColumnElement[bool]:
    return or_(
        Comment.created_at < created_at,
        and_(Comment.created_at == created_at, Comment.id < comment_id),
    )


def _encode_cursor(comment: Comment) -> str:
    raw = f"{_utc(comment.created_at).isoformat()}|{comment.id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: str) -> tuple[datetime, UUID]:
    try:
        padding = "=" * (-len(value) % 4)
        created_raw, id_raw = base64.urlsafe_b64decode(value + padding).decode().split("|", 1)
        created_at = datetime.fromisoformat(created_raw)
        if created_at.tzinfo is None:
            raise ValueError
        return created_at.astimezone(UTC), UUID(id_raw)
    except (binascii.Error, ValueError, UnicodeDecodeError) as error:
        raise CommentValidationError("invalid discussion cursor") from error


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
