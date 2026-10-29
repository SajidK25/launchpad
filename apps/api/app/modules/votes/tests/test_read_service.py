"""Demo-home date selection for public ranking reads."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

from app.modules.votes.service import VoteDailyRankingPage, VoteReadService


class _Products:
    def __init__(self, latest: date | None) -> None:
        self.latest = latest
        self.latest_calls: list[date] = []
        self.requested_dates: list[date | None] = []

    async def latest_public_launch_date(
        self, _session: object, *, on_or_before: date
    ) -> date | None:
        self.latest_calls.append(on_or_before)
        return self.latest

    async def public_launches(
        self,
        _session: object,
        *,
        requested_date: date | None,
        first: int = 20,
        after: str | None = None,
    ) -> object:
        del first, after
        self.requested_dates.append(requested_date)
        return SimpleNamespace(
            today_date=date(2026, 10, 29),
            selected_date=requested_date,
            items=(),
            next_cursor=None,
        )

    async def public_launch_cards_by_ids(
        self,
        _session: object,
        *,
        product_ids: tuple[UUID, ...],
        launch_date: date | None = None,
    ) -> tuple[object, ...]:
        del product_ids, launch_date
        return ()

    async def public_launch_cards_for_date(
        self, _session: object, *, launch_date: date
    ) -> tuple[object, ...]:
        del launch_date
        return ()


class _Repository:
    async def voting_enabled_from(self, _session: object) -> None:
        return None


def _read(
    products: _Products,
    *,
    enabled: bool,
    requested_date: date | None = None,
    product_id: UUID | None = None,
) -> VoteDailyRankingPage:
    async def verify() -> VoteDailyRankingPage:
        service = VoteReadService(
            products=cast(Any, products),
            repository=cast(Any, _Repository()),
            clock=lambda: datetime(2026, 10, 29, 12, tzinfo=UTC),
            demo_home_latest_launch_enabled=enabled,
        )
        return await service.daily_product_ranking(
            cast(Any, None),
            requested_date=requested_date,
            product_id=product_id,
        )

    return asyncio.run(verify())


def test_demo_home_uses_latest_public_day_when_today_is_empty() -> None:
    products = _Products(date(2026, 10, 27))

    page = _read(products, enabled=True)

    assert page.today_date == date(2026, 10, 29)
    assert page.selected_date == date(2026, 10, 27)
    assert products.latest_calls == [date(2026, 10, 29)]
    assert products.requested_dates == [date(2026, 10, 27)]


def test_demo_home_keeps_today_when_today_is_latest_or_no_launch_exists() -> None:
    for latest in (date(2026, 10, 29), None):
        products = _Products(latest)

        page = _read(products, enabled=True)

        assert page.selected_date == date(2026, 10, 29)
        assert products.requested_dates == [date(2026, 10, 29)]


def test_demo_home_fallback_is_disabled_by_default() -> None:
    products = _Products(date(2026, 10, 27))

    page = _read(products, enabled=False)

    assert page.selected_date == date(2026, 10, 29)
    assert products.latest_calls == []


def test_explicit_archive_date_never_falls_back() -> None:
    products = _Products(date(2026, 10, 27))

    page = _read(products, enabled=True, requested_date=date(2026, 10, 25))

    assert page.selected_date == date(2026, 10, 25)
    assert products.latest_calls == []
    assert products.requested_dates == [date(2026, 10, 25)]
