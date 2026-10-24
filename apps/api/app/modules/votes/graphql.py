"""Public ranking and staff vote-review reads for the composed GraphQL root."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

import strawberry
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.sessions import MemberContext
from app.modules.auth.staff import AccountState
from app.modules.products.graphql import PublicLaunchCard
from app.modules.votes.policies import VoteForbiddenError, VoteReadValidationError
from app.modules.votes.service import VoteReadService
from app.shared.observability.logging import log_event, request_context

logger = logging.getLogger("launchpad.graphql")


@strawberry.type
class DailyRankingEntry:
    product: PublicLaunchCard
    rank: int | None
    active_vote_count: int | None
    score: Decimal | None
    viewer_voted: bool | None


@strawberry.type
class DailyRankingPage:
    today_date: date
    selected_date: date
    has_snapshot: bool
    items: list[DailyRankingEntry]
    next_cursor: str | None


@strawberry.type
class PendingVoteReviewEntry:
    id: UUID
    vote_id: UUID
    member_id: UUID
    product: PublicLaunchCard
    signal_code: str
    created_at: datetime


@strawberry.type
class PendingVoteReviewPage:
    items: list[PendingVoteReviewEntry]
    next_cursor: str | None


@asynccontextmanager
async def _safe_read(info: strawberry.Info, *, operation: str) -> AsyncIterator[None]:
    """Keep database and internal values out of GraphQL error messages and logs."""

    try:
        yield
    except (PermissionError, VoteForbiddenError, VoteReadValidationError):
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


def _service(info: strawberry.Info) -> VoteReadService:
    return cast(VoteReadService, info.context["vote_read_service_factory"]())


def _public_card(product: object) -> PublicLaunchCard:
    logo = getattr(product, "logo", None)
    logo_url = (
        f"/api/v1/products/{getattr(product, 'id')}/assets/{getattr(logo, 'id')}/public"
        if logo is not None
        else None
    )
    return PublicLaunchCard(
        id=getattr(product, "id"),
        name=getattr(product, "name"),
        pitch=getattr(product, "pitch"),
        logo_url=logo_url,
        topics=list(getattr(product, "topics")),
    )


@strawberry.type
class VoteQuery:
    """Read-only vote ranking and staff queue fields."""

    @strawberry.field
    async def daily_product_ranking(
        self,
        info: strawberry.Info,
        date: date | None = None,
        product_id: UUID | None = None,
        first: int = 20,
        after: str | None = None,
    ) -> DailyRankingPage:
        """Read today's live rank, a frozen archive, or a pre-voting date."""

        async with _safe_read(info, operation="dailyProductRanking"):
            member: MemberContext | None = info.context.get("member")
            viewer_id = (
                member.account_id
                if member is not None
                and member.verified
                and member.role == "member"
                and member.suspended_at is None
                else None
            )
            async with info.context["session_factory"]() as session:
                page = await _service(info).daily_product_ranking(
                    cast(AsyncSession, session),
                    requested_date=date,
                    product_id=product_id,
                    first=first,
                    after=after,
                    viewer_id=viewer_id,
                )
            return DailyRankingPage(
                today_date=page.today_date,
                selected_date=page.selected_date,
                has_snapshot=page.has_snapshot,
                items=[
                    DailyRankingEntry(
                        product=_public_card(item.product),
                        rank=item.rank,
                        active_vote_count=item.active_vote_count,
                        score=item.score,
                        viewer_voted=item.viewer_voted,
                    )
                    for item in page.items
                ],
                next_cursor=page.next_cursor,
            )

    @strawberry.field
    async def pending_vote_reviews(
        self,
        info: strawberry.Info,
        first: int = 20,
        after: str | None = None,
    ) -> PendingVoteReviewPage:
        """Page flagged votes for verified, active reviewers and admins only."""

        async with _safe_read(info, operation="pendingVoteReviews"):
            member: MemberContext | None = info.context.get("member")
            if member is None:
                raise PermissionError("authentication required")
            reviewer = AccountState(
                account_id=member.account_id,
                verified=member.verified,
                role=member.role,
                suspended_at=member.suspended_at,
            )
            async with info.context["session_factory"]() as session:
                page = await _service(info).pending_vote_reviews(
                    cast(AsyncSession, session), reviewer=reviewer, first=first, after=after
                )
            return PendingVoteReviewPage(
                items=[
                    PendingVoteReviewEntry(
                        id=item.flag_id,
                        vote_id=item.vote_id,
                        member_id=item.member_id,
                        product=_public_card(item.product),
                        signal_code=item.signal_code,
                        created_at=item.created_at,
                    )
                    for item in page.items
                ],
                next_cursor=page.next_cursor,
            )
