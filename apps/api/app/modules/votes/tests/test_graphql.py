"""Vote GraphQL contracts and access boundaries."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import strawberry

from app.modules.auth.sessions import MemberContext
from app.modules.votes.graphql import VoteQuery
from app.modules.votes.policies import VoteForbiddenError
from app.modules.votes.service import (
    VoteDailyRankingItem,
    VoteDailyRankingPage,
    VoteReadService,
    VoteReviewQueuePage,
)


class _ReadService:
    async def daily_product_ranking(
        self, _session: object, **kwargs: object
    ) -> VoteDailyRankingPage:
        product_id = uuid4()
        product = SimpleNamespace(
            id=product_id,
            name="Public product",
            pitch="A public pitch",
            logo=SimpleNamespace(id=uuid4()),
            topics=("Tools",),
        )
        return VoteDailyRankingPage(
            today_date=date(2026, 10, 25),
            selected_date=date(2026, 10, 25),
            has_snapshot=True,
            items=(VoteDailyRankingItem(product, 1, 0, Decimal("0"), None),),
            next_cursor=None,
        )

    async def pending_vote_reviews(
        self, _session: object, **_kwargs: object
    ) -> VoteReviewQueuePage:
        return VoteReviewQueuePage((), None)


def _context(member: MemberContext | None = None) -> dict[str, object]:
    @asynccontextmanager
    async def session_factory() -> AsyncIterator[object]:
        yield object()

    return {
        "member": member,
        "session_factory": session_factory,
        "vote_read_service_factory": _ReadService,
        "request_id": "test-request",
    }


def test_daily_ranking_exposes_guest_safe_card_and_api_dates() -> None:
    schema = strawberry.Schema(query=VoteQuery)
    result = asyncio.run(
        schema.execute(
            """{ dailyProductRanking { todayDate selectedDate hasSnapshot
          items { rank activeVoteCount score viewerVoted product { id name pitch logoUrl topics } }
          nextCursor } }""",
            context_value=_context(),
        )
    )

    assert result.errors is None
    data = cast(dict[str, object], result.data)
    page = cast(dict[str, object], data["dailyProductRanking"])
    assert page["todayDate"] == "2026-10-25"
    assert page["selectedDate"] == "2026-10-25"
    item = cast(dict[str, object], cast(list[object], page["items"])[0])
    assert item["rank"] == 1
    assert item["activeVoteCount"] == 0
    assert item["viewerVoted"] is None
    product = cast(dict[str, object], item["product"])
    assert product["name"] == "Public product"
    assert cast(str, product["logoUrl"]).startswith("/api/v1/products/")


def test_pending_reviews_rejects_non_staff_member() -> None:
    schema = strawberry.Schema(query=VoteQuery)
    member = MemberContext(uuid4(), True, uuid4(), role="member")
    context = _context(member)
    context["vote_read_service_factory"] = lambda: VoteReadService(
        products=cast(Any, object()), repository=cast(Any, object())
    )
    result = asyncio.run(
        schema.execute("{ pendingVoteReviews { items { id } } }", context_value=context)
    )

    assert result.errors
    assert isinstance(result.errors[0].original_error, VoteForbiddenError)


def test_vote_graphql_schema_contains_bounded_read_fields() -> None:
    schema = strawberry.Schema(query=VoteQuery)
    fields = schema.as_str()
    assert "dailyProductRanking(date: Date" in fields
    assert "pendingVoteReviews(first: Int! = 20, after: String = null)" in fields
    assert "memberId: UUID!" in fields
    assert "rawIp" not in fields
