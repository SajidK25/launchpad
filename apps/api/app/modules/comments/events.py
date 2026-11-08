"""Revalidated worker publication for durable comment creation events."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.comments.live import comment_created_message, comment_product_channel
from app.modules.comments.models import Comment
from app.shared.events.outbox import PermanentEventError


class CommentEventRepository(Protocol):
    async def comment_by_id(self, session: AsyncSession, *, comment_id: UUID) -> Comment | None: ...


class CommentEventRedis(Protocol):
    async def publish(self, channel: str, message: str) -> int: ...


class CommentEventProductAccess(Protocol):
    async def discussion_context(
        self, session: AsyncSession, *, product_id: UUID, lock: bool = False
    ) -> object | None: ...


class CommentCreatedPublisher:
    """Publish an identifier-only hint after authoritative visibility checks."""

    def __init__(
        self,
        *,
        comments: CommentEventRepository,
        products: CommentEventProductAccess,
        redis: CommentEventRedis,
    ) -> None:
        self.comments = comments
        self.products = products
        self.redis = redis

    async def handle_outbox_event(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        aggregate_id: UUID,
        payload: dict[str, object],
    ) -> None:
        if event_type != "comment.created.v1" or set(payload) != {
            "product_id",
            "comment_id",
            "parent_id",
        }:
            raise PermanentEventError("comment event shape is invalid")
        product_id = _event_uuid(payload, "product_id")
        comment_id = _event_uuid(payload, "comment_id")
        parent_id = _optional_event_uuid(payload, "parent_id")
        if aggregate_id != product_id:
            raise PermanentEventError("comment event aggregate does not match product")

        comment = await self.comments.comment_by_id(session, comment_id=comment_id)
        if comment is None or comment.moderation_status != "visible":
            return
        if comment.product_id != product_id or comment.parent_id != parent_id:
            raise PermanentEventError("comment event does not match persisted entry")
        if (
            await self.products.discussion_context(session, product_id=product_id, lock=False)
            is None
        ):
            return

        await self.redis.publish(
            comment_product_channel(product_id),
            comment_created_message(
                product_id=product_id,
                comment_id=comment_id,
                parent_id=parent_id,
            ),
        )


def _event_uuid(payload: dict[str, object], field: str) -> UUID:
    value = payload.get(field)
    if not isinstance(value, str):
        raise PermanentEventError(f"comment event {field} is invalid")
    try:
        return UUID(value)
    except ValueError as error:
        raise PermanentEventError(f"comment event {field} is invalid") from error


def _optional_event_uuid(payload: dict[str, object], field: str) -> UUID | None:
    value = payload.get(field)
    if value is None:
        return None
    return _event_uuid(payload, field)
