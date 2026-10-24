"""Worker projection contracts backed by PostgreSQL values and rebuildable Redis fakes."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from app.modules.votes.service import VoteRankingProjectionService
from app.shared.events.outbox import PermanentEventError
from sqlalchemy.ext.asyncio import AsyncSession


class _Redis:
    def __init__(self, *, fail_on: str | None = None) -> None:
        self.fail_on = fail_on
        self.sorted_sets: dict[str, dict[str, float]] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.messages: list[tuple[str, str]] = []
        self.expirations: dict[str, int] = {}

    async def zadd(self, name: str, mapping: dict[str, float]) -> int:
        if self.fail_on == "zadd":
            raise OSError("redis unavailable")
        values = self.sorted_sets.setdefault(name, {})
        added = sum(member not in values for member in mapping)
        values.update(mapping)
        return added

    async def hset(self, name: str, *, mapping: dict[str, str]) -> int:
        if self.fail_on == "hset":
            raise OSError("redis unavailable")
        values = self.hashes.setdefault(name, {})
        added = sum(member not in values for member in mapping)
        values.update(mapping)
        return added

    async def hgetall(self, name: str) -> dict[str, str]:
        if self.fail_on == "hgetall":
            raise OSError("redis unavailable")
        return self.hashes.get(name, {}).copy()

    async def delete(self, *names: str) -> int:
        count = 0
        for name in names:
            count += name in self.hashes or name in self.sorted_sets
            self.hashes.pop(name, None)
            self.sorted_sets.pop(name, None)
        return int(count)

    async def publish(self, channel: str, message: str) -> int:
        if self.fail_on == "publish":
            raise OSError("redis unavailable")
        self.messages.append((channel, message))
        return 1

    async def expire(self, name: str, time: int) -> bool:
        self.expirations[name] = time
        return True


class _Products:
    def __init__(self, products: list[SimpleNamespace]) -> None:
        self.products = products

    async def public_projection(
        self, _session: AsyncSession, *, product_id: UUID
    ) -> SimpleNamespace | None:
        return next((item for item in self.products if item.id == product_id), None)

    async def public_launches(
        self,
        _session: AsyncSession,
        *,
        requested_date: date | None,
        first: int = 20,
        after: str | None = None,
    ) -> SimpleNamespace:
        del requested_date
        start = int(after or 0)
        items = self.products[start : start + first]
        next_cursor = str(start + first) if start + first < len(self.products) else None
        return SimpleNamespace(items=tuple(items), next_cursor=next_cursor)


class _VoteRepository:
    def __init__(self, values: dict[UUID, tuple[int, Decimal]]) -> None:
        self.values = values

    async def lock_projection_product(
        self, _session: AsyncSession, *, product_id: UUID, launch_date: date
    ) -> None:
        del product_id, launch_date

    async def lock_projection_rebuild(self, _session: AsyncSession, *, launch_date: date) -> None:
        del launch_date

    async def ranking_values(
        self, _session: AsyncSession, *, product_id: UUID, launch_date: date
    ) -> tuple[int, Decimal]:
        del launch_date
        return self.values.get(product_id, (0, Decimal(0)))

    async def ranking_values_for_products(
        self, _session: AsyncSession, *, product_ids: tuple[UUID, ...], launch_date: date
    ) -> dict[UUID, tuple[int, Decimal]]:
        del launch_date
        return {
            product_id: self.values.get(product_id, (0, Decimal(0))) for product_id in product_ids
        }


def _product(name: str, *, product_id: UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=product_id or uuid4(),
        name=name,
        launched_at=datetime(2026, 10, 24, 8, tzinfo=UTC),
    )


def _service(
    products: list[SimpleNamespace],
    values: dict[UUID, tuple[int, Decimal]],
    *,
    redis: _Redis | None = None,
) -> tuple[VoteRankingProjectionService, _Redis]:
    cache = redis or _Redis()
    return (
        VoteRankingProjectionService(
            products=cast(object, _Products(products)),
            repository=cast(object, _VoteRepository(values)),
            redis=cast(object, cache),
            clock=lambda: datetime(2026, 10, 24, 14, tzinfo=UTC),
        ),
        cache,
    )


def test_launch_event_adds_zero_vote_public_product_to_projection() -> None:
    async def verify() -> None:
        product = _product("Zero votes")
        service, redis = _service([product], {})
        await service.handle_outbox_event(
            cast(AsyncSession, object()),
            event_type="product.launched.v1",
            aggregate_id=product.id,
            payload={"product_id": str(product.id), "launch_date": "2026-10-24"},
        )

        entries = await service.read_projection(launch_date=date(2026, 10, 24))
        assert [(item.name, item.active_vote_count, item.score) for item in entries] == [
            ("Zero votes", 0, Decimal(0))
        ]
        assert len(redis.messages) == 1
        assert len(redis.expirations) == 2
        assert all(ttl > 0 for ttl in redis.expirations.values())
        assert json.loads(redis.messages[0][1]) == {
            "type": "ranking.invalidated",
            "date": "2026-10-24",
        }

    asyncio.run(verify())


def test_vote_change_recomputes_from_authoritative_values_on_replay() -> None:
    async def verify() -> None:
        product = _product("Voted product")
        values = {product.id: (2, Decimal("3.5"))}
        service, redis = _service([product], values)
        event = {
            "product_id": str(product.id),
            "launch_date": "2026-10-24",
            "action": "cast",
            "vote_id": str(uuid4()),
        }
        for _ in range(2):
            await service.handle_outbox_event(
                cast(AsyncSession, object()),
                event_type="vote.changed.v1",
                aggregate_id=product.id,
                payload=event,
            )

        entries = await service.read_projection(launch_date=date(2026, 10, 24))
        assert [(item.active_vote_count, item.score) for item in entries] == [(2, Decimal("3.5"))]
        assert len(redis.messages) == 2

    asyncio.run(verify())


def test_projection_order_uses_score_count_name_and_id_deterministically() -> None:
    async def verify() -> None:
        duplicate_a = _product("Alpha", product_id=UUID(int=4))
        duplicate_b = _product("alpha", product_id=UUID(int=3))
        stronger_score = _product("Zulu", product_id=UUID(int=2))
        no_votes = _product("Aardvark", product_id=UUID(int=1))
        values = {
            duplicate_a.id: (1, Decimal("2")),
            duplicate_b.id: (2, Decimal("2")),
            stronger_score.id: (1, Decimal("3")),
            no_votes.id: (0, Decimal("0")),
        }
        service, _ = _service([duplicate_a, duplicate_b, stronger_score, no_votes], values)
        entries = await service.rebuild(
            cast(AsyncSession, object()), launch_date=date(2026, 10, 24)
        )

        assert [entry.product_id for entry in entries] == [
            stronger_score.id,
            duplicate_b.id,
            duplicate_a.id,
            no_votes.id,
        ]

    asyncio.run(verify())


def test_rebuild_restores_zero_and_voted_products_from_public_database_page() -> None:
    async def verify() -> None:
        products = [_product("One"), _product("Two"), _product("Three")]
        service, _ = _service(products, {products[1].id: (1, Decimal("1.5"))})
        entries = await service.rebuild(
            cast(AsyncSession, object()), launch_date=date(2026, 10, 24)
        )
        assert {entry.product_id for entry in entries} == {item.id for item in products}
        assert [(entry.name, entry.active_vote_count) for entry in entries] == [
            ("Two", 1),
            ("One", 0),
            ("Three", 0),
        ]

    asyncio.run(verify())


def test_redis_failure_propagates_for_outbox_retry_without_false_completion() -> None:
    async def verify() -> None:
        product = _product("Retry me")
        redis = _Redis(fail_on="zadd")
        service, _ = _service([product], {}, redis=redis)
        with pytest.raises(OSError, match="redis unavailable"):
            await service.handle_outbox_event(
                cast(AsyncSession, object()),
                event_type="product.launched.v1",
                aggregate_id=product.id,
                payload={"product_id": str(product.id), "launch_date": "2026-10-24"},
            )
        assert redis.messages == []

    asyncio.run(verify())


def test_old_day_event_does_not_populate_current_live_projection() -> None:
    async def verify() -> None:
        product = _product("Past day")
        service, redis = _service([product], {})
        await service.handle_outbox_event(
            cast(AsyncSession, object()),
            event_type="vote.changed.v1",
            aggregate_id=product.id,
            payload={"product_id": str(product.id), "launch_date": "2026-10-23"},
        )
        assert redis.hashes == {}
        assert redis.messages == []

    asyncio.run(verify())


def test_malformed_product_event_is_permanent() -> None:
    async def verify() -> None:
        service, _ = _service([], {})
        with pytest.raises(PermanentEventError):
            await service.handle_outbox_event(
                cast(AsyncSession, object()),
                event_type="product.launched.v1",
                aggregate_id=uuid4(),
                payload={"product_id": "not-a-uuid", "launch_date": "2026-10-24"},
            )

    asyncio.run(verify())
