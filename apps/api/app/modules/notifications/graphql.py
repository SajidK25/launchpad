"""Read-only GraphQL composition for the founder notification inbox."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from enum import StrEnum
from typing import cast
from uuid import UUID

import strawberry
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.sessions import MemberContext
from app.modules.notifications.schemas import NotificationInbox as NotificationInboxResult
from app.modules.notifications.service import NotificationService


@strawberry.enum
class NotificationKindEnum(StrEnum):
    REVIEW_APPROVED = "review_approved"
    REVIEW_REJECTED = "review_rejected"
    REVIEW_CHANGES_REQUESTED = "review_changes_requested"


@strawberry.type
class NotificationEntry:
    id: UUID
    kind: NotificationKindEnum
    created_at: datetime
    read_at: datetime | None


@strawberry.type
class NotificationInbox:
    items: list[NotificationEntry]
    unread_count: int
    next_cursor: str | None


def _member(info: strawberry.Info) -> MemberContext:
    member: MemberContext | None = info.context.get("member")
    if member is None:
        raise PermissionError("authentication required")
    return member


def _service(info: strawberry.Info) -> NotificationService:
    return cast(NotificationService, info.context["notification_service_factory"]())


@asynccontextmanager
async def _safe_read() -> AsyncIterator[None]:
    try:
        yield
    except PermissionError:
        raise
    except Exception:
        raise RuntimeError("request could not be completed") from None


@strawberry.type
class NotificationQuery:
    """Founder notification reads; opening the inbox never mutates read state."""

    @strawberry.field
    async def viewer_notification_inbox(
        self, info: strawberry.Info, first: int = 20, after: str | None = None
    ) -> NotificationInbox:
        async with _safe_read():
            member = _member(info)
            async with info.context["session_factory"]() as session:
                page: NotificationInboxResult = await _service(info).inbox(
                    cast(AsyncSession, session),
                    actor_id=member.account_id,
                    first=first,
                    after=after,
                )
            return NotificationInbox(
                items=[
                    NotificationEntry(
                        id=item.id,
                        kind=NotificationKindEnum(item.kind),
                        created_at=item.created_at,
                        read_at=item.read_at,
                    )
                    for item in page.items
                ],
                unread_count=page.unread_count,
                next_cursor=page.next_cursor,
            )
