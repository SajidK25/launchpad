"""Independent Redis-backed temporary abuse limits with fail-closed semantics."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol


class RateLimitUnavailable(RuntimeError):
    """Redis could not enforce a sensitive-action limit."""


class RateLimitExceeded(RuntimeError):
    """A temporary address or source bucket is cooling down."""


class RedisLike(Protocol):
    def incr(self, key: str) -> int: ...
    def expire(self, key: str, seconds: int) -> bool: ...


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int


class RateLimiter:
    """Check address and source buckets independently; never silently fail open."""

    def __init__(self, client: RedisLike, *, limit: int = 10, window_seconds: int = 60) -> None:
        self.client = client
        self.limit = limit
        self.window_seconds = window_seconds

    async def check(self, *, address_key: str, source_key: str) -> RateLimitDecision:
        try:
            address, source = await asyncio.gather(
                asyncio.to_thread(self._increment, f"launchpad:limit:address:{address_key}"),
                asyncio.to_thread(self._increment, f"launchpad:limit:source:{source_key}"),
            )
        except Exception as exc:
            raise RateLimitUnavailable("rate limiting unavailable") from exc
        if max(address, source) > self.limit:
            raise RateLimitExceeded("too many attempts")
        return RateLimitDecision(True, self.window_seconds)

    def _increment(self, key: str) -> int:
        value = int(self.client.incr(key))
        if value == 1:
            if not self.client.expire(key, self.window_seconds):
                raise RateLimitUnavailable("rate limit expiry unavailable")
        return value
