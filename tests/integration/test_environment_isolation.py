"""Real-service checks for development and check-environment isolation."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg
import pytest
from botocore.client import BaseClient
from conftest import IntegrationSettings
from redis import Redis

SENTINEL_BUCKET = "t2-check-sentinel"
SENTINEL_KEY = "environment.txt"
SENTINEL_VALUE = b"launchpad-t2-check-environment"


async def _database_user(database_url: str) -> str:
    connection = await asyncpg.connect(database_url, timeout=2)
    try:
        return str(await connection.fetchval("SELECT current_user"))
    finally:
        await connection.close()


async def _write_database_sentinel(database_url: str, environment_name: str) -> str:
    connection = await asyncpg.connect(database_url, timeout=2)
    try:
        await connection.execute(
            "CREATE TABLE IF NOT EXISTS t2_environment_sentinels "
            "(environment_name text PRIMARY KEY, value text NOT NULL)"
        )
        await connection.execute(
            "INSERT INTO t2_environment_sentinels (environment_name, value) VALUES ($1, $2) "
            "ON CONFLICT (environment_name) DO UPDATE SET value = EXCLUDED.value",
            environment_name,
            "present",
        )
        return str(
            await connection.fetchval(
                "SELECT value FROM t2_environment_sentinels WHERE environment_name = $1",
                environment_name,
            )
        )
    finally:
        await connection.close()


def _ensure_bucket(client: BaseClient) -> None:
    bucket_names = {bucket["Name"] for bucket in client.list_buckets().get("Buckets", [])}
    if SENTINEL_BUCKET not in bucket_names:
        client.create_bucket(Bucket=SENTINEL_BUCKET)


def test_real_services_are_available_and_persistent(
    integration_settings_fixture: IntegrationSettings,
    redis_client: Redis,
    s3_client: BaseClient,
) -> None:
    """Exercise PostgreSQL, Redis and MinIO without any external accounts."""

    settings = integration_settings_fixture
    assert asyncio.run(_database_user(settings.database_url)) == "launchpad_check"

    assert redis_client.ping()
    redis_client.set("t2:environment", settings.environment_name)
    assert redis_client.get("t2:environment") == settings.environment_name.encode()

    _ensure_bucket(s3_client)
    s3_client.put_object(Bucket=SENTINEL_BUCKET, Key=SENTINEL_KEY, Body=SENTINEL_VALUE)
    stored_object = s3_client.get_object(Bucket=SENTINEL_BUCKET, Key=SENTINEL_KEY)
    assert stored_object["Body"].read() == SENTINEL_VALUE


def test_check_identity_uses_only_check_credentials(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    """Guard against accidental development credentials or volume configuration."""

    settings = integration_settings_fixture
    assert settings.environment_name == "check"
    assert "development" not in settings.database_url
    assert "development" not in settings.s3_access_key_id
    assert asyncio.run(_database_user(settings.database_url)) == "launchpad_check"


def test_check_fixture_data_survives_an_ordinary_service_restart(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    """Write deterministic disposable sentinels for the restart verification command."""

    settings = integration_settings_fixture
    sentinel_value = asyncio.run(
        _write_database_sentinel(settings.database_url, settings.environment_name)
    )
    assert sentinel_value == "present"


def test_missing_required_dependency_fails_with_a_bounded_error() -> None:
    """A check must fail when PostgreSQL is not reachable; it must never silently skip."""

    with pytest.raises((OSError, asyncpg.PostgresError, TimeoutError)):
        asyncio.run(
            asyncpg.connect("postgresql://invalid:invalid@postgres-missing:5432/missing", timeout=1)
        )


def test_development_compose_keeps_database_and_redis_off_host_ports() -> None:
    """Inspect the declared development network boundary without requiring Docker in tests."""

    compose = Path("compose.yaml").read_text()
    postgres_block = compose.split("  postgres:\n", 1)[1].split("\n  redis:\n", 1)[0]
    redis_block = compose.split("  redis:\n", 1)[1].split("\n  minio:\n", 1)[0]

    assert "ports:" not in postgres_block
    assert "ports:" not in redis_block
    assert "127.0.0.1:" in compose


def test_separate_network_cannot_reach_a_supplied_development_database() -> None:
    """Exercise the cross-project boundary when the host verification supplies a dev URL."""

    development_url = os.environ.get("FORBIDDEN_DEVELOPMENT_DATABASE_URL")
    if development_url is None:
        return

    with pytest.raises((OSError, asyncpg.PostgresError, TimeoutError)):
        asyncio.run(asyncpg.connect(development_url, timeout=1))


def test_quality_compose_uses_isolated_check_credentials_and_named_volumes() -> None:
    """Keep concurrent quality projects away from development identities and storage."""

    compose = Path("compose.checks.yaml").read_text()

    assert "launchpad_check_password" in compose
    assert "launchpad_check_minio_password" in compose
    assert "check_postgres_data" in compose
    assert "check_redis_data" in compose
    assert "check_minio_data" in compose
    assert "launchpad_development" not in compose
