"""Founder-only launch booking reads for the composed GraphQL endpoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import cast
from uuid import UUID

import strawberry
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.sessions import MemberContext
from app.modules.launches.service import LaunchBookingPage as LaunchBookingPageResult
from app.modules.launches.service import LaunchBookingService


@strawberry.type
class LaunchBookingEntry:
    id: UUID
    product_id: UUID
    state: str
    product_status: str
    launch_date: date
    launch_at: datetime
    failure_reason: str | None
    created_at: datetime
    closed_at: datetime | None


@strawberry.type
class LaunchBookingPage:
    items: list[LaunchBookingEntry]
    next_cursor: str | None


def _member(info: strawberry.Info) -> MemberContext:
    member: MemberContext | None = info.context.get("member")
    if member is None:
        raise PermissionError("authentication required")
    return member


@asynccontextmanager
async def _safe_read() -> AsyncIterator[None]:
    try:
        yield
    except PermissionError:
        raise
    except Exception:
        raise RuntimeError("request could not be completed") from None


@strawberry.type
class LaunchQuery:
    """Read a founder's own booking lifecycle and persistent failure reason."""

    @strawberry.field
    async def viewer_launch_bookings(
        self, info: strawberry.Info, first: int = 20, after: str | None = None
    ) -> LaunchBookingPage:
        async with _safe_read():
            member = _member(info)
            async with info.context["session_factory"]() as session:
                page: LaunchBookingPageResult = await cast(
                    LaunchBookingService, info.context["launch_booking_service_factory"]()
                ).owner_bookings(
                    cast(AsyncSession, session),
                    actor_id=member.account_id,
                    first=first,
                    after=after,
                )
            return LaunchBookingPage(
                items=[
                    LaunchBookingEntry(
                        id=item.id,
                        product_id=item.product_id,
                        state=item.state,
                        product_status=item.product_status,
                        launch_date=item.launch_date,
                        launch_at=item.launch_at,
                        failure_reason=item.failure_reason,
                        created_at=item.created_at,
                        closed_at=item.closed_at,
                    )
                    for item in page.items
                ],
                next_cursor=page.next_cursor,
            )
