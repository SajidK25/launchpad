"""Fixtures for real, disposable infrastructure integration tests."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Generator
from dataclasses import dataclass, field

import asyncpg
import boto3
import pytest
from botocore.client import BaseClient
from redis import Redis


@dataclass(frozen=True)
class IntegrationSettings:
    """Container-scoped settings for the current disposable check environment."""

    database_url: str = field(repr=False)
    redis_url: str = field(repr=False)
    s3_endpoint_url: str = field(repr=False)
    s3_access_key_id: str = field(repr=False)
    s3_secret_access_key: str = field(repr=False)
    environment_name: str


def integration_settings() -> IntegrationSettings:
    """Return required settings and fail clearly when the integration service is misconfigured."""

    required_names = (
        "DATABASE_URL",
        "REDIS_URL",
        "S3_ENDPOINT_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "LAUNCHPAD_ENVIRONMENT",
    )
    values = {name: os.environ.get(name, "") for name in required_names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(f"Missing integration settings: {', '.join(missing)}")

    return IntegrationSettings(
        database_url=values["DATABASE_URL"],
        redis_url=values["REDIS_URL"],
        s3_endpoint_url=values["S3_ENDPOINT_URL"],
        s3_access_key_id=values["AWS_ACCESS_KEY_ID"],
        s3_secret_access_key=values["AWS_SECRET_ACCESS_KEY"],
        environment_name=values["LAUNCHPAD_ENVIRONMENT"],
    )


@pytest.fixture
def integration_settings_fixture() -> IntegrationSettings:
    """Expose validated settings to integration tests."""

    return integration_settings()


@pytest.fixture
def redis_client(integration_settings_fixture: IntegrationSettings) -> Generator[Redis, None, None]:
    """Yield a Redis client with finite connection timeouts."""

    client = Redis.from_url(
        integration_settings_fixture.redis_url,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def s3_client(integration_settings_fixture: IntegrationSettings) -> BaseClient:
    """Create an S3-compatible client bound to the current MinIO service only."""

    return boto3.client(
        "s3",
        endpoint_url=integration_settings_fixture.s3_endpoint_url,
        aws_access_key_id=integration_settings_fixture.s3_access_key_id,
        aws_secret_access_key=integration_settings_fixture.s3_secret_access_key,
        region_name="us-east-1",
    )


@pytest.fixture
def reset_database(integration_settings_fixture: IntegrationSettings) -> None:
    """Reset only the disposable check schema before a migration scenario."""

    async def reset() -> None:
        connection = await asyncpg.connect(integration_settings_fixture.database_url, timeout=2)
        try:
            await connection.execute("DROP SCHEMA public CASCADE")
            await connection.execute("CREATE SCHEMA public")
        finally:
            await connection.close()

    asyncio.run(reset())
