"""Async PostgreSQL access and serialized Alembic preparation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import cast

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

FOUNDATION_REVISION = "0001_foundation"
PREPARATION_LOCK_KEY = 8_741_430_129


class DatabasePreparationError(RuntimeError):
    """Base error for a preparation failure safe to expose in diagnostics."""


class PreparationLockTimeout(DatabasePreparationError):
    """Raised when another preparation session retains the advisory lock."""


class MigrationCompatibilityError(DatabasePreparationError):
    """Raised when the applied Alembic revision is not the expected head."""


@dataclass
class Database:
    """Own an async engine and serialize migrations through a session lock."""

    database_url: str
    engine: AsyncEngine

    @classmethod
    def connect(cls, database_url: str) -> Database:
        """Create a database boundary with bounded connection setup."""

        return cls(
            database_url=database_url,
            engine=create_async_engine(_async_database_url(database_url), pool_pre_ping=True),
        )

    async def close(self) -> None:
        """Release all pooled PostgreSQL connections."""

        await self.engine.dispose()

    async def current_revision(self) -> str | None:
        """Return the applied Alembic revision, or ``None`` before initialization."""

        async with self.engine.connect() as connection:
            return await _current_revision(connection)

    async def ensure_compatible(self, expected_revision: str = FOUNDATION_REVISION) -> None:
        """Reject missing, older, or newer schema state without mutating the database."""

        revision = await self.current_revision()
        if revision != expected_revision:
            actual = revision or "missing"
            raise MigrationCompatibilityError(
                f"Database revision is {actual}; expected {expected_revision}."
            )

    async def prepare(
        self,
        lock_timeout_seconds: float = 5.0,
        expected_revision: str = FOUNDATION_REVISION,
        script_location: Path | None = None,
    ) -> None:
        """Acquire the session lock, apply migrations, and verify the expected head."""

        async with self.engine.connect() as connection:
            await _acquire_preparation_lock(connection, lock_timeout_seconds)
            try:
                await connection.commit()
                await connection.run_sync(_upgrade_to_head, script_location)
                await connection.commit()
                revision = await _current_revision(connection)
                if revision != expected_revision:
                    actual = revision or "missing"
                    raise MigrationCompatibilityError(
                        f"Database revision is {actual}; expected {expected_revision}."
                    )
            finally:
                await _release_preparation_lock(connection)
                await connection.commit()


async def _current_revision(connection: AsyncConnection) -> str | None:
    """Read Alembic state without triggering an error for an uninitialized database."""

    table_exists = await connection.scalar(text("SELECT to_regclass('alembic_version')"))
    if table_exists is None:
        return None
    revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    return cast(str | None, revision)


async def _acquire_preparation_lock(connection: AsyncConnection, timeout_seconds: float) -> None:
    """Acquire the documented session-level lock within a finite deadline."""

    deadline = monotonic() + timeout_seconds
    while True:
        acquired = await connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": PREPARATION_LOCK_KEY}
        )
        if acquired:
            return
        if monotonic() >= deadline:
            raise PreparationLockTimeout("Database preparation lock timed out.")
        await asyncio.sleep(0.05)


async def _release_preparation_lock(connection: AsyncConnection) -> None:
    """Release the session lock when its connection remains usable."""

    try:
        await connection.execute(
            text("SELECT pg_advisory_unlock(:key)"), {"key": PREPARATION_LOCK_KEY}
        )
    except Exception:
        # A lost PostgreSQL session releases its session-level advisory locks itself.
        pass


def _upgrade_to_head(connection: Connection, script_location: Path | None = None) -> None:
    """Run Alembic using the connection that owns the preparation lock."""

    api_root = Path(__file__).resolve().parents[3]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(script_location or api_root / "alembic"))
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


def _async_database_url(database_url: str) -> str:
    """Select asyncpg for PostgreSQL URLs that do not name a driver."""

    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return database_url
