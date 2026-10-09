"""Database-only migration command for production releases."""

from __future__ import annotations

import asyncio
import os
import sys

from app.shared.config.settings import ConfigurationError
from app.shared.db.database import Database, DatabasePreparationError


def _production_database_url() -> str:
    """Require explicit production intent and a database URL without loading storage config."""

    if os.environ.get("LAUNCHPAD_ENVIRONMENT") != "production":
        raise ConfigurationError("Invalid configuration: LAUNCHPAD_ENVIRONMENT")
    database_url = os.environ.get("LAUNCHPAD_DATABASE_URL")
    if not database_url:
        raise ConfigurationError("Invalid configuration: LAUNCHPAD_DATABASE_URL")
    return database_url


async def migrate() -> None:
    """Apply Alembic migrations under the existing database preparation lock."""

    database = Database.connect(_production_database_url())
    try:
        await database.prepare()
    finally:
        await database.close()


def main() -> None:
    """Exit nonzero with a bounded diagnostic on any migration failure."""

    try:
        asyncio.run(migrate())
    except (ConfigurationError, DatabasePreparationError) as error:
        print(f"Production migration failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        print("Production migration failed.", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
