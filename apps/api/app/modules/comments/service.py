"""Transactional discussion commands and public bounded reads."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.staff import AccountState
from app.modules.comments.models import Comment
from app.modules.comments.policies import (
    CommentConflictError,
    CommentInfrastructureError,
    CommentNotFoundError,
    CommentRateLimitError,
    normalize_comment_body,
    require_comment_author,
    validate_idempotency_key,
    validate_page_size,
)
from app.modules.comments.repository import CommentRepository
from app.shared.events.outbox import OutboxEvent, OutboxRepository


class CommentAccountAccess(Protocol):
    async def current_account(
        self, session: AsyncSession, account_id: UUID, *, lock: bool = False
    ) -> AccountState | None: ...


class CommentAuthorAttribution(Protocol):
    account_id: UUID
    display_name: str | None
    has_photo: bool
    public_profile_url: str | None


class CommentAttributionAccess(Protocol):
    async def batch(
        self, session: AsyncSession, account_ids: tuple[UUID, ...]
    ) -> dict[UUID, CommentAuthorAttribution]: ...


class ProductDiscussionContext(Protocol):
    product_id: UUID


class ProductDiscussionAccess(Protocol):
    async def discussion_context(
        self, session: AsyncSession, *, product_id: UUID, lock: bool = False
    ) -> ProductDiscussionContext | None: ...


class CommentPayloadCodec(Protocol):
    def encode(self, payload: Mapping[str, object]) -> tuple[str, bytes]: ...


class CommentOutbox(Protocol):
    async def add(self, session: AsyncSession, event: OutboxEvent) -> UUID: ...


@dataclass(frozen=True, slots=True)
class CommentEntry:
    id: UUID
    product_id: UUID
    author_account_id: UUID
    parent_id: UUID | None
    body: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CommentCommandResult:
    entry: CommentEntry
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class CommentThread:
    entry: CommentEntry
    reply_count: int
    replies: tuple[CommentEntry, ...]


@dataclass(frozen=True, slots=True)
class CommentDiscussionPage:
    items: tuple[CommentThread, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class CommentReplyPage:
    items: tuple[CommentEntry, ...]
    earlier_cursor: str | None


class CommentService:
    """Coordinate visibility, author state, safeguards, persistence, and outbox."""

    SHORT_LIMIT = 5
    SHORT_WINDOW = timedelta(seconds=60)
    DAILY_LIMIT = 100
    DAILY_WINDOW = timedelta(hours=24)
    DUPLICATE_WINDOW = timedelta(minutes=5)

    def __init__(
        self,
        *,
        account_access: CommentAccountAccess,
        attribution_access: CommentAttributionAccess,
        product_access: ProductDiscussionAccess,
        repository: CommentRepository | None = None,
        outbox: CommentOutbox | None = None,
        codec: CommentPayloadCodec,
        writes_enabled: Callable[[], bool],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.account_access = account_access
        self.attribution_access = attribution_access
        self.product_access = product_access
        self.repository = repository or CommentRepository()
        self.outbox = outbox or OutboxRepository()
        self.codec = codec
        self.writes_enabled = writes_enabled
        self.clock = clock or (lambda: datetime.now(UTC))

    async def create_root(
        self,
        session: AsyncSession,
        *,
        author_id: UUID,
        product_id: UUID,
        body: str,
        idempotency_key: str,
    ) -> CommentCommandResult:
        return await self._create(
            session,
            author_id=author_id,
            product_id=product_id,
            parent_id=None,
            body=body,
            idempotency_key=idempotency_key,
        )

    async def create_reply(
        self,
        session: AsyncSession,
        *,
        author_id: UUID,
        product_id: UUID,
        parent_id: UUID,
        body: str,
        idempotency_key: str,
    ) -> CommentCommandResult:
        return await self._create(
            session,
            author_id=author_id,
            product_id=product_id,
            parent_id=parent_id,
            body=body,
            idempotency_key=idempotency_key,
        )

    async def _create(
        self,
        session: AsyncSession,
        *,
        author_id: UUID,
        product_id: UUID,
        parent_id: UUID | None,
        body: str,
        idempotency_key: str,
    ) -> CommentCommandResult:
        now = _utc(self.clock())
        normalized = normalize_comment_body(body)
        key = validate_idempotency_key(idempotency_key)
        body_fingerprint = hashlib.sha256(normalized.encode()).hexdigest()
        request_fingerprint = _request_fingerprint(product_id, parent_id, normalized)
        async with session.begin_nested():
            account = await self.account_access.current_account(session, author_id, lock=True)
            attributions = await self.attribution_access.batch(session, (author_id,))
            require_comment_author(account, attributions.get(author_id))
            await self.repository.lock_idempotency_key(
                session, author_id=author_id, idempotency_key=key
            )
            context = await self.product_access.discussion_context(
                session, product_id=product_id, lock=True
            )
            if context is None:
                raise CommentNotFoundError("discussion is unavailable")
            receipt = await self.repository.get_receipt(
                session, author_id=author_id, idempotency_key=key
            )
            if receipt is not None:
                if receipt.request_fingerprint != request_fingerprint:
                    raise CommentConflictError("idempotency key was used for a different comment")
                original = await self.repository.comment_by_id(
                    session, comment_id=receipt.comment_id
                )
                if original is None or original.product_id != product_id:
                    raise CommentConflictError("original comment is unavailable")
                return CommentCommandResult(entry=_entry(original), replayed=True)
            if not self.writes_enabled():
                raise CommentConflictError("discussion posting is not currently enabled")
            if (
                parent_id is not None
                and await self.repository.visible_root(
                    session, product_id=product_id, parent_id=parent_id
                )
                is None
            ):
                raise CommentNotFoundError("discussion parent is unavailable")
            activity = await self.repository.author_activity(
                session, author_id=author_id, since=now - self.DAILY_WINDOW
            )
            _require_within_limits(activity, now=now)
            if await self.repository.has_recent_duplicate(
                session,
                author_id=author_id,
                product_id=product_id,
                body_fingerprint=body_fingerprint,
                since=now - self.DUPLICATE_WINDOW,
            ):
                raise CommentConflictError("recent duplicate comment")
            try:
                comment = await self.repository.create_comment(
                    session,
                    product_id=product_id,
                    author_id=author_id,
                    depth=1 if parent_id is not None else 0,
                    parent_id=parent_id,
                    body=normalized,
                    body_fingerprint=body_fingerprint,
                    created_at=now,
                )
                await self.repository.add_receipt(
                    session,
                    author_id=author_id,
                    idempotency_key=key,
                    request_fingerprint=request_fingerprint,
                    comment_id=comment.id,
                    created_at=now,
                )
                key_id, encrypted_payload = self.codec.encode(
                    {
                        "product_id": str(product_id),
                        "comment_id": str(comment.id),
                        "parent_id": str(parent_id) if parent_id is not None else None,
                    }
                )
                await self.outbox.add(
                    session,
                    OutboxEvent(
                        event_type="comment.created.v1",
                        aggregate_id=product_id,
                        key_id=key_id,
                        encrypted_payload=encrypted_payload,
                        available_at=now,
                    ),
                )
            except Exception as error:
                raise CommentInfrastructureError(
                    "discussion comment could not be recorded"
                ) from error
            return CommentCommandResult(entry=_entry(comment))

    async def discussion(
        self,
        session: AsyncSession,
        *,
        product_id: UUID,
        first: int = 20,
        after: str | None = None,
    ) -> CommentDiscussionPage:
        limit = validate_page_size(first)
        if (
            await self.product_access.discussion_context(session, product_id=product_id, lock=True)
            is None
        ):
            raise CommentNotFoundError("discussion is unavailable")
        roots, next_cursor = await self.repository.list_roots(
            session, product_id=product_id, limit=limit, after=after
        )
        summaries = await self.repository.reply_summaries(
            session, product_id=product_id, parent_ids=tuple(root.id for root in roots)
        )
        return CommentDiscussionPage(
            items=tuple(
                CommentThread(
                    entry=_entry(root),
                    reply_count=summaries[root.id].count,
                    replies=tuple(_entry(reply) for reply in summaries[root.id].replies),
                )
                for root in roots
            ),
            next_cursor=next_cursor,
        )

    async def replies(
        self,
        session: AsyncSession,
        *,
        product_id: UUID,
        parent_id: UUID,
        first: int = 20,
        before: str | None = None,
    ) -> CommentReplyPage:
        limit = validate_page_size(first)
        if (
            await self.product_access.discussion_context(session, product_id=product_id, lock=True)
            is None
        ):
            raise CommentNotFoundError("discussion is unavailable")
        if (
            await self.repository.visible_root(session, product_id=product_id, parent_id=parent_id)
            is None
        ):
            raise CommentNotFoundError("discussion parent is unavailable")
        replies, earlier_cursor = await self.repository.list_replies(
            session,
            product_id=product_id,
            parent_id=parent_id,
            limit=limit,
            before=before,
        )
        return CommentReplyPage(
            items=tuple(_entry(reply) for reply in replies),
            earlier_cursor=earlier_cursor,
        )

    async def has_visible_entries(self, session: AsyncSession, *, account_id: UUID) -> bool:
        return await self.repository.has_visible_entries(session, author_id=account_id)


def _require_within_limits(activity: tuple[datetime, ...], *, now: datetime) -> None:
    recent = tuple(value for value in activity if value > now - CommentService.SHORT_WINDOW)
    if len(recent) >= CommentService.SHORT_LIMIT:
        raise CommentRateLimitError(
            "discussion posting limit exceeded",
            retry_at=recent[0] + CommentService.SHORT_WINDOW,
        )
    daily = tuple(value for value in activity if value > now - CommentService.DAILY_WINDOW)
    if len(daily) >= CommentService.DAILY_LIMIT:
        raise CommentRateLimitError(
            "discussion daily posting limit exceeded",
            retry_at=daily[0] + CommentService.DAILY_WINDOW,
        )


def _request_fingerprint(product_id: UUID, parent_id: UUID | None, body: str) -> str:
    encoded = json.dumps(
        {
            "operation": "reply" if parent_id is not None else "root",
            "product_id": str(product_id),
            "parent_id": str(parent_id) if parent_id is not None else None,
            "body": body,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _entry(comment: Comment) -> CommentEntry:
    return CommentEntry(
        id=comment.id,
        product_id=comment.product_id,
        author_account_id=comment.author_account_id,
        parent_id=comment.parent_id,
        body=comment.body,
        created_at=_utc(comment.created_at),
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
