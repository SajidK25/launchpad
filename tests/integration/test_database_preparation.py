"""Real PostgreSQL checks for serialized, repeatable migration preparation."""

from __future__ import annotations

import asyncio
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from app.modules.users.models import PhotoUpload, Profile, ProfileLink
from app.shared.db.database import (
    PREPARATION_LOCK_KEY,
    Database,
    MigrationCompatibilityError,
    PreparationLockTimeout,
    migration_head,
)
from conftest import IntegrationSettings
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError


def test_fresh_preparation_establishes_the_application_revision(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    """A new disposable database gains the current application schema."""

    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            assert await database.current_revision() is None
            await database.prepare()
            assert await database.current_revision() == migration_head()
            async with database.engine.connect() as connection:
                tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
                assert {
                    "accounts",
                    "sessions",
                    "email_verifications",
                    "password_resets",
                    "profiles",
                    "profile_links",
                    "photo_uploads",
                    "outbox_messages",
                    "email_deliveries",
                }.issubset(tables)
                assert {
                    Profile.__tablename__,
                    ProfileLink.__tablename__,
                    PhotoUpload.__tablename__,
                }.issubset(tables)
                foreign_keys = await connection.run_sync(
                    lambda sync: {
                        table: {
                            key["referred_table"] for key in inspect(sync).get_foreign_keys(table)
                        }
                        for table in ("sessions", "profiles", "profile_links", "email_deliveries")
                    }
                )
                assert foreign_keys == {
                    "sessions": {"accounts"},
                    "profiles": {"accounts"},
                    "profile_links": {"profiles"},
                    "email_deliveries": {"outbox_messages"},
                }
                profile_checks = await connection.run_sync(
                    lambda sync: {
                        check["name"] for check in inspect(sync).get_check_constraints("profiles")
                    }
                )
                assert {"ck_profiles_bio", "ck_profiles_public_local_fields"}.issubset(
                    profile_checks
                )
                indexes = await connection.run_sync(
                    lambda sync: {
                        table: {index["name"] for index in inspect(sync).get_indexes(table)}
                        for table in (
                            "sessions",
                            "email_verifications",
                            "password_resets",
                            "profiles",
                            "photo_uploads",
                            "outbox_messages",
                        )
                    }
                )
                assert "uq_email_verifications_current_account" in indexes["email_verifications"]
                assert "uq_password_resets_current_account" in indexes["password_resets"]
                assert "ix_profiles_public_account" in indexes["profiles"]
                assert "ix_photo_uploads_pending_expiry" in indexes["photo_uploads"]
                assert "ix_outbox_due" in indexes["outbox_messages"]
        finally:
            await database.close()

    asyncio.run(verify())


def test_identity_constraints_reject_duplicate_and_incomplete_public_rows(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    """Database constraints defend identity and local publication state."""

    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        account_id = uuid4()
        now = datetime.now(UTC)
        try:
            await database.prepare()
            async with database.engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO accounts "
                        "(id, email_display, email_key, password_hash, created_at, updated_at) "
                        "VALUES (:id, :display, :key, :hash, :now, :now)"
                    ),
                    {
                        "id": account_id,
                        "display": "Member@example.com",
                        "key": "member@example.com",
                        "hash": "hashed",
                        "now": now,
                    },
                )
                await connection.execute(
                    text("INSERT INTO profiles (account_id) VALUES (:id)"),
                    {"id": account_id},
                )
            async with database.engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT visibility FROM profiles WHERE account_id = :id"),
                        {"id": account_id},
                    )
                    == "private"
                )
            with pytest.raises(IntegrityError):
                async with database.engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO accounts "
                            "(id, email_display, email_key, password_hash, created_at, updated_at) "
                            "VALUES (:id, :display, :key, :hash, :now, :now)"
                        ),
                        {
                            "id": uuid4(),
                            "display": "MEMBER@example.com",
                            "key": "member@example.com",
                            "hash": "hashed",
                            "now": now,
                        },
                    )
            with pytest.raises(IntegrityError):
                async with database.engine.begin() as connection:
                    await connection.execute(
                        text(
                            "UPDATE profiles SET visibility = 'public', published_at = :now "
                            "WHERE account_id = :id"
                        ),
                        {"id": account_id, "now": now},
                    )
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
            assert await database.current_revision() == migration_head()
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
            assert await database.current_revision() == migration_head()
        finally:
            await database.close()

    asyncio.run(verify())


def test_concurrent_preparation_serializes_a_fresh_migration(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    """Two consumers can start against an empty check database without a false head."""

    async def verify() -> None:
        first = Database.connect(integration_settings_fixture.database_url)
        second = Database.connect(integration_settings_fixture.database_url)
        try:
            await asyncio.gather(first.prepare(), second.prepare())
            assert await first.current_revision() == migration_head()
            assert await second.current_revision() == migration_head()
        finally:
            await first.close()
            await second.close()

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
            assert await database.current_revision() == migration_head()
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
                    text("UPDATE alembic_version SET version_num = '0001_foundation'")
                )
            with pytest.raises(MigrationCompatibilityError, match="0001_foundation"):
                await database.ensure_compatible()
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
