"""Minimal Dramatiq worker process without product actors."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from health import ProgressHealth, progress_is_fresh, record_progress, redis_is_available

HEALTH_PATH = Path("/tmp/launchpad-worker.progress")
FRESHNESS_SECONDS = 5.0


def is_healthy() -> bool:
    """Check real worker-loop progress and Redis availability."""
    return progress_is_fresh(HEALTH_PATH, FRESHNESS_SECONDS) and redis_is_available(
        os.environ.get("LAUNCHPAD_REDIS_URL", "redis://redis:6379/0")
    )


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
    while True:
        health.tick()
        record_progress(HEALTH_PATH)
        time.sleep(1)


if __name__ == "__main__":
    main()
