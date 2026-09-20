"""Real prepared-dependency health checks."""

from __future__ import annotations

import asyncio

from app.modules.health.probes import database_probe, redis_probe, storage_probe
from app.modules.health.service import HealthService
from app.shared.db.database import Database
from app.shared.storage.client import StorageClient
from conftest import IntegrationSettings
from redis import Redis


def test_real_health_accepts_prepared_dependencies(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            service = HealthService(
                [
                    database_probe(database),
                    redis_probe(Redis.from_url(integration_settings_fixture.redis_url)),
                    storage_probe(
                        StorageClient(
                            integration_settings_fixture.s3_endpoint_url,
                            integration_settings_fixture.s3_access_key_id,
                            integration_settings_fixture.s3_secret_access_key,
                        ),
                        "launchpad-private",
                    ),
                ]
            )
            assert await service.readiness() is True
        finally:
            await database.close()

    asyncio.run(verify())
