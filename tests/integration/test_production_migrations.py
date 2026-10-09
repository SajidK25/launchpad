"""Production migration command checks using the disposable integration database."""

from __future__ import annotations

import asyncio

import pytest
from app.migrate import main, migrate
from app.shared.db.database import Database, DatabasePreparationError, migration_head
from conftest import IntegrationSettings


def _production_database_env(monkeypatch: pytest.MonkeyPatch, database_url: str) -> None:
    monkeypatch.setenv("LAUNCHPAD_ENVIRONMENT", "production")
    monkeypatch.setenv("LAUNCHPAD_DATABASE_URL", database_url)
    for name in (
        "LAUNCHPAD_STORAGE_PROVIDER",
        "LAUNCHPAD_STORAGE_REGION",
        "LAUNCHPAD_STORAGE_ENDPOINT_URL",
        "LAUNCHPAD_STORAGE_ACCESS_KEY_ID",
        "LAUNCHPAD_STORAGE_SECRET_ACCESS_KEY",
        "LAUNCHPAD_BOOTSTRAP_STORAGE_ACCESS_KEY_ID",
        "LAUNCHPAD_BOOTSTRAP_STORAGE_SECRET_ACCESS_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_production_migration_needs_only_database_configuration(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _production_database_env(monkeypatch, integration_settings_fixture.database_url)

    asyncio.run(migrate())

    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            assert await database.current_revision() == migration_head()
        finally:
            await database.close()

    asyncio.run(verify())


def test_concurrent_production_migrations_share_the_database_lock(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _production_database_env(monkeypatch, integration_settings_fixture.database_url)

    async def run() -> None:
        await asyncio.gather(migrate(), migrate())

    asyncio.run(run())

    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            assert await database.current_revision() == migration_head()
        finally:
            await database.close()

    asyncio.run(verify())


def test_migration_failure_exits_nonzero_without_storage_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _production_database_env(monkeypatch, "postgresql://test:test@localhost/test")

    class FailingDatabase:
        async def prepare(self) -> None:
            raise DatabasePreparationError("database migration failed")

        async def close(self) -> None:
            return None

    monkeypatch.setattr(Database, "connect", lambda _: FailingDatabase())

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 1
    assert capsys.readouterr().err == "Production migration failed: database migration failed\n"
