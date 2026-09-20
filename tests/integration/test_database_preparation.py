"""Real PostgreSQL checks for serialized, repeatable migration preparation."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import asyncpg
import pytest
from app.shared.db.database import (
    FOUNDATION_REVISION,
    PREPARATION_LOCK_KEY,
    Database,
    MigrationCompatibilityError,
    PreparationLockTimeout,
)
from conftest import IntegrationSettings
from sqlalchemy import text


def test_fresh_preparation_establishes_only_the_foundation_revision(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    """A new disposable database gains Alembic state without product tables."""

    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            assert await database.current_revision() is None
            await database.prepare()
            assert await database.current_revision() == FOUNDATION_REVISION
        finally:
            await database.close()

    asyncio.run(verify())


def test_preparation_wait_is_bounded_and_releases_for_a_retry(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    """A held session lock rejects a contender, then allows a safe retry."""

    async def verify() -> None:
        holder = await asyncpg.connect(integration_settings_fixture.database_url, timeout=2)
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            await holder.execute("SELECT pg_advisory_lock($1)", PREPARATION_LOCK_KEY)
            with pytest.raises(PreparationLockTimeout):
                await database.prepare(lock_timeout_seconds=0.1)
            await holder.execute("SELECT pg_advisory_unlock($1)", PREPARATION_LOCK_KEY)
            await database.prepare(lock_timeout_seconds=0.5)
            assert await database.current_revision() == FOUNDATION_REVISION
        finally:
            await holder.close()
            await database.close()

    asyncio.run(verify())


def test_lost_lock_session_releases_ownership_for_new_preparation(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    """Terminating the owning session releases its lock instead of retaining stale ownership."""

    async def verify() -> None:
        holder = await asyncpg.connect(integration_settings_fixture.database_url, timeout=2)
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            await holder.execute("SELECT pg_advisory_lock($1)", PREPARATION_LOCK_KEY)
            holder.terminate()
            await asyncio.sleep(0.05)
            await database.prepare(lock_timeout_seconds=0.5)
            assert await database.current_revision() == FOUNDATION_REVISION
        finally:
            await database.close()

    asyncio.run(verify())


def test_failed_migration_is_transactional_and_leaves_no_false_revision(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
    tmp_path: Path,
) -> None:
    """A failing disposable migration rolls back its DDL and releases the session lock."""

    script_location = tmp_path / "alembic"
    versions = script_location / "versions"
    versions.mkdir(parents=True)
    shutil.copy(Path("apps/api/alembic/env.py"), script_location / "env.py")
    (versions / "0001_failure.py").write_text(
        '''"""Disposable failure migration."""
from alembic import op

revision = "0001_failure"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.execute("CREATE TABLE t4_partial_migration (id integer PRIMARY KEY)")
    raise RuntimeError("intentional migration failure")

def downgrade():
    pass
'''
    )

    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            with pytest.raises(RuntimeError, match="intentional migration failure"):
                await database.prepare(script_location=script_location)
            assert await database.current_revision() is None
            async with database.engine.connect() as connection:
                partial_table = await connection.scalar(
                    text("SELECT to_regclass('t4_partial_migration')")
                )
                assert partial_table is None
            await database.prepare()
            assert await database.current_revision() == FOUNDATION_REVISION
        finally:
            await database.close()

    asyncio.run(verify())


def test_revision_compatibility_rejects_missing_and_unexpected_state(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    """Readiness callers can detect incompatible state without a downgrade or mutation."""

    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            with pytest.raises(MigrationCompatibilityError, match="missing"):
                await database.ensure_compatible()
            await database.prepare()
            async with database.engine.begin() as connection:
                await connection.execute(
                    text("UPDATE alembic_version SET version_num = 'unexpected_newer'")
                )
            with pytest.raises(MigrationCompatibilityError, match="unexpected_newer"):
                await database.ensure_compatible()
            assert await database.current_revision() == "unexpected_newer"
        finally:
            await database.close()

    asyncio.run(verify())


def test_repeat_preparation_preserves_existing_records(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    """Repeated migrations retain a test-only sentinel record."""

    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            await database.prepare()
            async with database.engine.begin() as connection:
                await connection.exec_driver_sql(
                    "CREATE TABLE t4_sentinels (value text PRIMARY KEY NOT NULL)"
                )
                await connection.exec_driver_sql(
                    "INSERT INTO t4_sentinels (value) VALUES ('present')"
                )
            await database.prepare()
            async with database.engine.connect() as connection:
                assert await connection.scalar(text("SELECT value FROM t4_sentinels")) == "present"
        finally:
            await database.close()

    asyncio.run(verify())
