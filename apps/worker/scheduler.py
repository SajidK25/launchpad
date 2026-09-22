"""Scheduler that publishes durable outbox due-work hints."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.shared.db.database import Database
from app.shared.events.models import OutboxMessage
from health import ProgressHealth, progress_is_fresh, record_progress, redis_is_available
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

HEALTH_PATH = Path("/tmp/launchpad-scheduler.progress")
FRESHNESS_SECONDS = 5.0


def is_healthy() -> bool:
    """Check real scheduler-loop progress and Redis availability."""
    return progress_is_fresh(HEALTH_PATH, FRESHNESS_SECONDS) and redis_is_available(
        os.environ.get("LAUNCHPAD_REDIS_URL", "redis://redis:6379/0")
    )


async def run_scheduler(health: ProgressHealth) -> None:
    database = Database.connect(
        os.environ.get(
            "LAUNCHPAD_DATABASE_URL",
            "postgresql://launchpad_development:launchpad_development_password@postgres:5432/launchpad_development",
        )
    )
    redis = Redis.from_url(os.environ.get("LAUNCHPAD_REDIS_URL", "redis://redis:6379/0"))
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    try:
        await database.ensure_compatible()
        while True:
            try:
                async with sessions() as session:
                    ids = list(
                        (
                            await session.scalars(
                                select(OutboxMessage.id)
                                .where(
                                    OutboxMessage.state == "pending",
                                    OutboxMessage.available_at <= datetime.now(UTC),
                                )
                                .order_by(OutboxMessage.available_at, OutboxMessage.id)
                                .limit(100)
                            )
                        ).all()
                    )
                if ids:
                    await asyncio.to_thread(
                        redis.rpush, "launchpad:outbox:due", *(str(event_id) for event_id in ids)
                    )
                health.tick()
                record_progress(HEALTH_PATH)
            except (RedisError, OSError):
                pass
            await asyncio.sleep(1)
    finally:
        redis.close()
        await database.close()


def main() -> None:
    if "--health" in sys.argv:
        raise SystemExit(0 if is_healthy() else 1)

    health = ProgressHealth(
        connections=(
            lambda: redis_is_available(
                os.environ.get("LAUNCHPAD_REDIS_URL", "redis://redis:6379/0")
            ),
        )
    )
    asyncio.run(run_scheduler(health))


if __name__ == "__main__":
    main()
