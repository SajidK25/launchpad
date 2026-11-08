"""Bounded public discussion reads for the composed GraphQL root."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import cast
from uuid import UUID

import strawberry
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.comments.policies import CommentNotFoundError, CommentValidationError
from app.modules.comments.service import (
    CommentDiscussionPage as DiscussionResultPage,
)
from app.modules.comments.service import CommentEntry as CommentEntryResult
from app.modules.comments.service import CommentReplyPage as ReplyResultPage
from app.modules.comments.service import CommentService
from app.modules.users.comment_attribution import CommentAuthorAttribution
from app.shared.observability.logging import log_event, request_context

logger = logging.getLogger("launchpad.graphql")


@strawberry.type
class CommentAuthor:
    account_id: UUID
    display_name: str
    avatar_url: str
    public_profile_url: str | None


@strawberry.type
class CommentEntry:
    id: UUID
    product_id: UUID
    parent_id: UUID | None
    body: str
    created_at: datetime
    author: CommentAuthor


@strawberry.type
class CommentThread(CommentEntry):
    reply_count: int
    replies: list[CommentEntry]


@strawberry.type
class ProductDiscussionPage:
    items: list[CommentThread]
    next_cursor: str | None


@strawberry.type
class CommentReplyPage:
    items: list[CommentEntry]
    earlier_cursor: str | None


@asynccontextmanager
async def _safe_read(info: strawberry.Info, *, operation: str) -> AsyncIterator[None]:
    """Preserve safe typed failures and collapse every internal detail."""

    try:
        yield
    except (CommentNotFoundError, CommentValidationError):
        raise
    except Exception as error:
        request_id = str(info.context.get("request_id") or "unknown")
        with request_context(request_id):
            log_event(
                logger,
                component="graphql",
                operation=operation,
                outcome="failed",
                exception_type=type(error).__name__,
            )
        raise RuntimeError("request could not be completed") from None


def _service(info: strawberry.Info) -> CommentService:
    return cast(CommentService, info.context["comment_service_factory"]())


def _author_ids(entries: Iterable[CommentEntryResult]) -> tuple[UUID, ...]:
    return tuple(dict.fromkeys(entry.author_account_id for entry in entries))


def _author(
    entry: CommentEntryResult,
    attributions: dict[UUID, CommentAuthorAttribution],
) -> CommentAuthor:
    attribution = attributions.get(entry.author_account_id)
    if (
        attribution is None
        or not isinstance(attribution.display_name, str)
        or not attribution.display_name.strip()
        or not attribution.has_photo
    ):
        raise RuntimeError("current comment attribution is unavailable")
    return CommentAuthor(
        account_id=entry.author_account_id,
        display_name=attribution.display_name,
        avatar_url=(
            f"/api/v1/products/{entry.product_id}/comment-authors/{entry.author_account_id}/photo"
        ),
        public_profile_url=attribution.public_profile_url,
    )


def _entry(
    value: CommentEntryResult,
    attributions: dict[UUID, CommentAuthorAttribution],
) -> CommentEntry:
    return CommentEntry(
        id=value.id,
        product_id=value.product_id,
        parent_id=value.parent_id,
        body=value.body,
        created_at=value.created_at,
        author=_author(value, attributions),
    )


async def _discussion_page(
    session: AsyncSession,
    service: CommentService,
    result: DiscussionResultPage,
) -> ProductDiscussionPage:
    entries = tuple(entry for thread in result.items for entry in (thread.entry, *thread.replies))
    attributions = cast(
        dict[UUID, CommentAuthorAttribution],
        await service.attribution_access.batch(session, _author_ids(entries)),
    )
    return ProductDiscussionPage(
        items=[
            CommentThread(
                id=thread.entry.id,
                product_id=thread.entry.product_id,
                parent_id=thread.entry.parent_id,
                body=thread.entry.body,
                created_at=thread.entry.created_at,
                author=_author(thread.entry, attributions),
                reply_count=thread.reply_count,
                replies=[_entry(reply, attributions) for reply in thread.replies],
            )
            for thread in result.items
        ],
        next_cursor=result.next_cursor,
    )


async def _reply_page(
    session: AsyncSession,
    service: CommentService,
    result: ReplyResultPage,
) -> CommentReplyPage:
    attributions = cast(
        dict[UUID, CommentAuthorAttribution],
        await service.attribution_access.batch(session, _author_ids(result.items)),
    )
    return CommentReplyPage(
        items=[_entry(reply, attributions) for reply in result.items],
        earlier_cursor=result.earlier_cursor,
    )


@strawberry.type
class CommentQuery:
    """Independent public roots for discussion and earlier reply pages."""

    @strawberry.field
    async def product_discussion(
        self,
        info: strawberry.Info,
        product_id: UUID,
        first: int = 20,
        after: str | None = None,
    ) -> ProductDiscussionPage:
        async with _safe_read(info, operation="productDiscussion"):
            service = _service(info)
            async with info.context["session_factory"]() as raw_session:
                session = cast(AsyncSession, raw_session)
                result = await service.discussion(
                    session, product_id=product_id, first=first, after=after
                )
                return await _discussion_page(session, service, result)
        raise AssertionError("unreachable")

    @strawberry.field
    async def comment_replies(
        self,
        info: strawberry.Info,
        product_id: UUID,
        parent_id: UUID,
        first: int = 20,
        before: str | None = None,
    ) -> CommentReplyPage:
        async with _safe_read(info, operation="commentReplies"):
            service = _service(info)
            async with info.context["session_factory"]() as raw_session:
                session = cast(AsyncSession, raw_session)
                result = await service.replies(
                    session,
                    product_id=product_id,
                    parent_id=parent_id,
                    first=first,
                    before=before,
                )
                return await _reply_page(session, service, result)
        raise AssertionError("unreachable")
