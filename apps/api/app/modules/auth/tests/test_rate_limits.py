from __future__ import annotations

import asyncio

import pytest

from app.shared.security.rate_limit import RateLimiter, RateLimitExceeded, RateLimitUnavailable


class FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.values: dict[str, int] = {}
        self.fail = fail

    def incr(self, key: str) -> int:
        if self.fail:
            raise OSError("redis down")
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key: str, seconds: int) -> bool:
        return True


def test_address_and_source_buckets_are_independent() -> None:
    async def run() -> None:
        limiter = RateLimiter(FakeRedis(), limit=1)
        await limiter.check(address_key="a", source_key="one")
        with pytest.raises(RateLimitExceeded):
            await limiter.check(address_key="a", source_key="two")
        await limiter.check(address_key="b", source_key="three")

    asyncio.run(run())


def test_redis_failure_fails_closed() -> None:
    async def run() -> None:
        with pytest.raises(RateLimitUnavailable):
            await RateLimiter(FakeRedis(fail=True)).check(address_key="a", source_key="one")

    asyncio.run(run())


def test_expiry_failure_fails_closed() -> None:
    class ExpiryFailureRedis(FakeRedis):
        def expire(self, key: str, seconds: int) -> bool:
            return False

    async def run() -> None:
        with pytest.raises(RateLimitUnavailable):
            await RateLimiter(ExpiryFailureRedis()).check(address_key="a", source_key="one")

    asyncio.run(run())
