"""Worker-side comment invalidation contracts."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.comments.events import (
    CommentCreatedPublisher,
    CommentEventProductAccess,
    CommentEventRedis,
    CommentEventRepository,
)
from app.modules.comments.live import comment_product_channel
from app.shared.events.outbox import PermanentEventError


class _Comments:
    def __init__(self, comment: SimpleNamespace | None) -> None:
        self.comment = comment

    async def comment_by_id(
        self, _session: AsyncSession, *, comment_id: UUID
    ) -> SimpleNamespace | None:
        if self.comment is not None and self.comment.id == comment_id:
            return self.comment
        return None


class _Products:
    def __init__(self, product_id: UUID, *, visible: bool = True) -> None:
        self.product_id = product_id
        self.visible = visible

    async def discussion_context(
        self, _session: AsyncSession, *, product_id: UUID, lock: bool = False
    ) -> SimpleNamespace | None:
        del lock
        if self.visible and product_id == self.product_id:
            return SimpleNamespace(product_id=product_id)
        return None


class _Redis:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable
        self.messages: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        if self.unavailable:
            raise OSError("redis unavailable")
        self.messages.append((channel, message))
        return 1


def _publisher(
    *,
    product_id: UUID,
    comment: SimpleNamespace | None,
    visible: bool = True,
    unavailable: bool = False,
) -> tuple[CommentCreatedPublisher, _Redis]:
    redis = _Redis(unavailable=unavailable)
    return (
        CommentCreatedPublisher(
            comments=cast(CommentEventRepository, _Comments(comment)),
            products=cast(CommentEventProductAccess, _Products(product_id, visible=visible)),
            redis=cast(CommentEventRedis, redis),
        ),
        redis,
    )


def test_visible_comment_publishes_identifier_only_invalidation_on_replay() -> None:
    async def verify() -> None:
        product_id, comment_id, author_id = uuid4(), uuid4(), uuid4()
        comment = SimpleNamespace(
            id=comment_id,
            product_id=product_id,
            parent_id=None,
            moderation_status="visible",
            body="must never enter Redis",
            author_account_id=author_id,
        )
        publisher, redis = _publisher(product_id=product_id, comment=comment)
        payload: dict[str, object] = {
            "product_id": str(product_id),
            "comment_id": str(comment_id),
            "parent_id": None,
        }

        for _ in range(2):
            await publisher.handle_outbox_event(
                cast(AsyncSession, object()),
                event_type="comment.created.v1",
                aggregate_id=product_id,
                payload=payload,
            )

        assert len(redis.messages) == 2
        assert all(channel == comment_product_channel(product_id) for channel, _ in redis.messages)
        assert json.loads(redis.messages[0][1]) == {
            "type": "comment.created",
            "product_id": str(product_id),
            "comment_id": str(comment_id),
            "parent_id": None,
        }
        assert "must never enter Redis" not in redis.messages[0][1]
        assert str(author_id) not in redis.messages[0][1]

    asyncio.run(verify())


@pytest.mark.parametrize("missing,visible", [(True, True), (False, False)])
def test_missing_comment_or_private_product_suppresses_publication(
    missing: bool, visible: bool
) -> None:
    async def verify() -> None:
        product_id, comment_id = uuid4(), uuid4()
        comment = None
        if not missing:
            comment = SimpleNamespace(
                id=comment_id,
                product_id=product_id,
                parent_id=None,
                moderation_status="visible",
            )
        publisher, redis = _publisher(product_id=product_id, comment=comment, visible=visible)

        await publisher.handle_outbox_event(
            cast(AsyncSession, object()),
            event_type="comment.created.v1",
            aggregate_id=product_id,
            payload={
                "product_id": str(product_id),
                "comment_id": str(comment_id),
                "parent_id": None,
            },
        )

        assert redis.messages == []

    asyncio.run(verify())


def test_malformed_or_mismatched_event_is_permanently_invalid() -> None:
    async def verify() -> None:
        product_id = uuid4()
        publisher, _redis = _publisher(product_id=product_id, comment=None)
        with pytest.raises(PermanentEventError):
            await publisher.handle_outbox_event(
                cast(AsyncSession, object()),
                event_type="comment.created.v1",
                aggregate_id=product_id,
                payload={"product_id": str(product_id), "comment_id": "not-a-uuid"},
            )
        with pytest.raises(PermanentEventError):
            await publisher.handle_outbox_event(
                cast(AsyncSession, object()),
                event_type="comment.created.v1",
                aggregate_id=uuid4(),
                payload={
                    "product_id": str(product_id),
                    "comment_id": str(uuid4()),
                    "parent_id": None,
                },
            )

    asyncio.run(verify())


def test_redis_failure_remains_retryable() -> None:
    async def verify() -> None:
        product_id, comment_id = uuid4(), uuid4()
        comment = SimpleNamespace(
            id=comment_id,
            product_id=product_id,
            parent_id=None,
            moderation_status="visible",
        )
        publisher, _redis = _publisher(product_id=product_id, comment=comment, unavailable=True)
        with pytest.raises(OSError, match="redis unavailable"):
            await publisher.handle_outbox_event(
                cast(AsyncSession, object()),
                event_type="comment.created.v1",
                aggregate_id=product_id,
                payload={
                    "product_id": str(product_id),
                    "comment_id": str(comment_id),
                    "parent_id": None,
                },
            )

    asyncio.run(verify())
