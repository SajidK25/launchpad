"""Bounded health checks for worker and scheduler loops."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic, time

from redis import Redis
from redis.exceptions import RedisError


@dataclass
class ProgressHealth:
    """Track monitored-loop progress and its required dependencies."""

    freshness_seconds: float = 5.0
    connections: tuple[Callable[[], bool], ...] = ()
    last_progress: float | None = field(default=None)

    def tick(self) -> None:
        self.last_progress = monotonic()

    def healthy(self) -> bool:
        return (
            self.last_progress is not None
            and monotonic() - self.last_progress <= self.freshness_seconds
            and all(connection() for connection in self.connections)
        )


def record_progress(path: Path) -> None:
    """Record loop activity for an in-container health command."""
    path.write_text(str(time()))


def progress_is_fresh(path: Path, freshness_seconds: float) -> bool:
    """Report whether a loop has recorded progress within its allowed interval."""
    try:
        return time() - float(path.read_text()) <= freshness_seconds
    except (OSError, ValueError):
        return False


def redis_is_available(url: str) -> bool:
    """Probe Redis without allowing a connection error to expose credentials."""
    try:
        return bool(Redis.from_url(url).ping())
    except RedisError:
        return False
