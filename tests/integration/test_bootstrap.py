"""Combined database and private-storage preparation checks."""

from __future__ import annotations

import asyncio

from _pytest.monkeypatch import MonkeyPatch
from app.bootstrap import prepare
from app.shared.db.database import FOUNDATION_REVISION, Database
from conftest import IntegrationSettings


def test_bootstrap_prepares_database_and_private_storage(
    integration_settings_fixture: IntegrationSettings,
    monkeypatch: MonkeyPatch,
) -> None:
    """Bootstrap uses the shared lock path and leaves a usable migration revision."""

    monkeypatch.setenv("LAUNCHPAD_ENVIRONMENT", "test")
    monkeypatch.setenv("LAUNCHPAD_DATABASE_URL", integration_settings_fixture.database_url)
    monkeypatch.setenv(
        "LAUNCHPAD_STORAGE_ENDPOINT_URL", integration_settings_fixture.s3_endpoint_url
    )
    monkeypatch.setenv("LAUNCHPAD_STORAGE_ACCESS_KEY_ID", "launchpad_check_runtime")
    monkeypatch.setenv("LAUNCHPAD_STORAGE_SECRET_ACCESS_KEY", "launchpad_check_runtime_password")
    monkeypatch.setenv(
        "LAUNCHPAD_BOOTSTRAP_STORAGE_ACCESS_KEY_ID", integration_settings_fixture.s3_access_key_id
    )
    monkeypatch.setenv(
        "LAUNCHPAD_BOOTSTRAP_STORAGE_SECRET_ACCESS_KEY",
        integration_settings_fixture.s3_secret_access_key,
    )
    monkeypatch.setenv("LAUNCHPAD_STORAGE_BUCKET", "launchpad-private")
    asyncio.run(prepare())

    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            assert await database.current_revision() == FOUNDATION_REVISION
        finally:
            await database.close()

    asyncio.run(verify())
