"""Durable transactional-email worker process."""

from __future__ import annotations

import asyncio
import base64
import os
import sys
from pathlib import Path

from app.shared.config.settings import load_settings
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.email.transport import EmailTransport
from app.shared.events.dispatcher import dispatch_due
from app.shared.events.outbox import OutboxRepository
from health import ProgressHealth, progress_is_fresh, record_progress, redis_is_available
from sqlalchemy.ext.asyncio import async_sessionmaker

HEALTH_PATH = Path("/tmp/launchpad-worker.progress")
FRESHNESS_SECONDS = 5.0


def is_healthy() -> bool:
    """Check real worker-loop progress and Redis availability."""
    return progress_is_fresh(HEALTH_PATH, FRESHNESS_SECONDS) and redis_is_available(
        os.environ.get("LAUNCHPAD_REDIS_URL", "redis://redis:6379/0")
    )


async def run_worker(health: ProgressHealth) -> None:
    settings = load_settings()
    database = Database.connect(str(settings.database_url))
    key = base64.b64decode(settings.outbox_key.get_secret_value(), validate=True)  # type: ignore[union-attr]
    codec = EmailPayloadCodec({settings.outbox_key_id: key}, settings.outbox_key_id)  # type: ignore[arg-type]
    transport = EmailTransport(
        hostname=settings.smtp_host,  # type: ignore[arg-type]
        port=settings.smtp_port,  # type: ignore[arg-type]
        sender=str(settings.mail_sender),
        use_tls=settings.smtp_use_tls,  # type: ignore[arg-type]
        username=settings.smtp_username.get_secret_value() if settings.smtp_username else None,
        password=settings.smtp_password.get_secret_value() if settings.smtp_password else None,
    )
    repository = OutboxRepository()
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    try:
        await database.ensure_compatible()
        while True:
            try:
                async with sessions.begin() as session:
                    await dispatch_due(
                        session,
                        repository=repository,
                        codec=codec,
                        sender=transport,
                    )
                health.tick()
                record_progress(HEALTH_PATH)
            except Exception:
                # A stale progress file makes the container unhealthy while the
                # next iteration retries the durable database work.
                pass
            await asyncio.sleep(1)
    finally:
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
    asyncio.run(run_worker(health))


if __name__ == "__main__":
    main()
