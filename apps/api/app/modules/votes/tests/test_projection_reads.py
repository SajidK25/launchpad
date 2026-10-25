"""Bounded public ranking reads from the rebuildable Redis projection."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

from app.modules.votes.service import (
    LiveRankEntry,
    VoteRankingProjectionService,
    _encode_live_cursor,
    _rank_index_member,
    _rank_sort_key,
)


class _Redis:
    def __init__(self) -> None:
        self.sorted: dict[str, set[str]] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.values: dict[str, str] = {}

    async def exists(self, name: str) -> int:
        return int(name in self.values)

    async def zadd(self, name: str, mapping: dict[str, float]) -> int:
        bucket = self.sorted.setdefault(name, set())
        before = len(bucket)
        bucket.update(mapping)
        return len(bucket) - before

    async def zrem(self, name: str, *values: str) -> int:
        bucket = self.sorted.setdefault(name, set())
        before = len(bucket)
        bucket.difference_update(values)
        return before - len(bucket)

    async def zrangebylex(
        self, name: str, minimum: str, maximum: str, start: int = 0, num: int | None = None
    ) -> list[str]:
        values = sorted(self.sorted.get(name, set()))
        if minimum != "-":
            inclusive_min = not minimum.startswith("(")
            min_value = minimum[1:] if minimum[:1] in "([" else minimum
            if inclusive_min:
                values = [value for value in values if value >= min_value]
            else:
                values = [value for value in values if value > min_value]
        if maximum != "+":
            inclusive_max = not maximum.startswith("(")
            max_value = maximum[1:] if maximum[:1] in "([" else maximum
            if inclusive_max:
                values = [value for value in values if value <= max_value]
            else:
                values = [value for value in values if value < max_value]
        values = values[start:]
        return values if num is None else values[:num]

    async def zrank(self, name: str, value: str) -> int | None:
        try:
            return sorted(self.sorted.get(name, set())).index(value)
        except ValueError:
            return None

    async def zlexcount(self, name: str, minimum: str, maximum: str) -> int:
        values = await self.zrangebylex(name, minimum, maximum)
        return len(values)

    async def hset(self, name: str, mapping: dict[str, str]) -> int:
        bucket = self.hashes.setdefault(name, {})
        added = sum(key not in bucket for key in mapping)
        bucket.update(mapping)
        return added

    async def hget(self, name: str, key: str) -> str | None:
        return self.hashes.get(name, {}).get(key)

    async def hmget(self, name: str, keys: list[str]) -> list[str | None]:
        values = self.hashes.get(name, {})
        return [values.get(key) for key in keys]

    async def hgetall(self, name: str) -> dict[str, str]:
        return dict(self.hashes.get(name, {}))

    async def delete(self, *names: str) -> int:
        removed = 0
        for name in names:
            removed += int(self.values.pop(name, None) is not None)
            self.sorted.pop(name, None)
            self.hashes.pop(name, None)
        return removed

    async def publish(self, _channel: str, _message: str) -> int:
        return 0

    async def expire(self, _name: str, _seconds: int) -> bool:
        return True

    async def set(self, name: str, value: str, ex: int | None = None) -> bool:
        del ex
        self.values[name] = value
        return True


class _Products:
    def __init__(self, products: dict[object, object] | None = None) -> None:
        self.products = products or {}

    async def public_launches(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("a warm Redis ranking page must not scan the product catalog")

    async def public_launch_cards_by_ids(
        self, _session: Any, *, product_ids: tuple[object, ...], launch_date: date | None = None
    ) -> tuple[object, ...]:
        del launch_date
        return tuple(self.products[value] for value in product_ids if value in self.products)

    async def public_launch_cards_for_date(self, *_args: Any, **_kwargs: Any) -> tuple[object, ...]:
        raise AssertionError("a single-product rank lookup must not load the day's cards")

    async def public_projection(self, *_args: Any, **_kwargs: Any) -> object | None:
        return None


class _Repository:
    async def lock_projection_rebuild(self, *_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the ready projection should not be rebuilt")


def _seed(redis: _Redis, launch_date: date, entries: list[LiveRankEntry]) -> None:
    suffix = launch_date.isoformat()
    order_key = f"launchpad:votes:ranking:{suffix}:ordered-v2"
    metadata_key = f"launchpad:votes:ranking:{suffix}:entries"
    ready_key = f"launchpad:votes:ranking:{suffix}:ready-v2"
    redis.values[ready_key] = "1"
    for entry in entries:
        redis.sorted.setdefault(order_key, set()).add(_rank_index_member(entry))
        redis.hashes.setdefault(metadata_key, {})[str(entry.product_id)] = json.dumps(
            {
                "name": entry.name,
                "active_vote_count": entry.active_vote_count,
                "score": str(entry.score),
            }
        )


def test_warm_ranking_projection_pages_without_catalog_scan() -> None:
    async def verify() -> None:
        launch_date = date(2026, 10, 25)
        redis = _Redis()
        entries = [
            LiveRankEntry(uuid4(), "Zero", 0, Decimal(0)),
            LiveRankEntry(uuid4(), "Alpha", 2, Decimal("0.75")),
            LiveRankEntry(uuid4(), "Beta", 2, Decimal("1.25")),
        ]
        product = type("PublicCard", (), {"id": entries[1].product_id})()
        products = _Products({entries[1].product_id: product})
        _seed(redis, launch_date, entries)
        projection = VoteRankingProjectionService(
            products=cast(Any, products),
            repository=_Repository(),  # type: ignore[arg-type]
            redis=redis,  # type: ignore[arg-type]
            clock=lambda: datetime(2026, 10, 25, 12, tzinfo=UTC),
        )

        first, next_cursor = await projection.read_page(
            cast(Any, None),
            launch_date=launch_date,
            first=1,
            after=None,
            product_id=None,
        )
        second, _ = await projection.read_page(
            cast(Any, None),
            launch_date=launch_date,
            first=1,
            after=next_cursor,
            product_id=None,
        )

        assert first == [(entries[2], 1)]
        assert second == [(entries[1], 2)]
        assert next_cursor == _encode_live_cursor(launch_date, _rank_sort_key(entries[2]))

    asyncio.run(verify())


def test_product_rank_uses_direct_index_lookup() -> None:
    async def verify() -> None:
        launch_date = date(2026, 10, 25)
        redis = _Redis()
        entries = [
            LiveRankEntry(uuid4(), "First", 1, Decimal("1")),
            LiveRankEntry(uuid4(), "Chosen", 1, Decimal("0.5")),
            LiveRankEntry(uuid4(), "Zero", 0, Decimal(0)),
        ]
        product = type("PublicCard", (), {"id": entries[1].product_id})()
        _seed(redis, launch_date, entries)
        projection = VoteRankingProjectionService(
            products=cast(Any, _Products({entries[1].product_id: product})),
            repository=_Repository(),  # type: ignore[arg-type]
            redis=redis,  # type: ignore[arg-type]
            clock=lambda: datetime(2026, 10, 25, 12, tzinfo=UTC),
        )

        ranked, cursor = await projection.read_page(
            cast(Any, None),
            launch_date=launch_date,
            first=1,
            after=None,
            product_id=entries[1].product_id,
        )

        assert ranked == [(entries[1], 2)]
        assert cursor is None

    asyncio.run(verify())


def test_redis_lex_order_matches_score_count_name_id_and_zero_vote_ties() -> None:
    first_id, second_id = sorted((uuid4(), uuid4()), key=str)
    entries = [
        LiveRankEntry(first_id, "Same Name", 1, Decimal("1.25")),
        LiveRankEntry(second_id, "same name", 1, Decimal("1.25")),
        LiveRankEntry(uuid4(), "More votes", 2, Decimal("1.25")),
        LiveRankEntry(uuid4(), "Zero B", 0, Decimal(0)),
        LiveRankEntry(uuid4(), "Zero A", 0, Decimal(0)),
        LiveRankEntry(uuid4(), "Lower score", 5, Decimal("1.2")),
    ]

    assert sorted(entries, key=_rank_sort_key) == sorted(entries, key=_rank_index_member)
