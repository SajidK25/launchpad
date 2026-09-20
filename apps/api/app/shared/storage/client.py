"""Bounded, read-only S3-compatible storage access."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

import boto3
from botocore.client import BaseClient, Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)


class StorageError(RuntimeError):
    """Base storage error that is safe to surface in internal diagnostics."""


class StorageAccessDenied(StorageError):
    """Storage credentials are invalid or lack the required read-only permission."""


class StorageUnavailable(StorageError):
    """Storage could not be reached or did not complete within its transport budget."""


class StorageProbeTimeout(StorageError):
    """A read-only storage probe exceeded its application deadline."""


StorageClientFactory = Callable[[], BaseClient]


@dataclass(frozen=True)
class StorageClient:
    """Run portable S3 read-only probes outside the event loop."""

    endpoint_url: str
    access_key_id: str
    secret_access_key: str
    transport_timeout_seconds: float = 1.0
    client_factory: StorageClientFactory | None = None

    async def probe(self, bucket_name: str, timeout_seconds: float = 2.0) -> None:
        """Confirm authenticated private-bucket access without object mutation or listing."""

        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._probe_sync, bucket_name), timeout=timeout_seconds
            )
        except TimeoutError as error:
            raise StorageProbeTimeout("Storage readiness probe timed out.") from error

    def _probe_sync(self, bucket_name: str) -> None:
        """Use only bucket metadata calls in a worker thread."""

        client = self._client()
        try:
            client.head_bucket(Bucket=bucket_name)
            try:
                client.get_bucket_policy(Bucket=bucket_name)
            except ClientError as error:
                if str(error.response.get("Error", {}).get("Code", "")) == "NoSuchBucketPolicy":
                    return
                raise
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}:
                raise StorageAccessDenied("Storage access was denied.") from None
            raise StorageUnavailable("Storage request failed.") from None
        except (BotoCoreError, ConnectTimeoutError, EndpointConnectionError, ReadTimeoutError):
            raise StorageUnavailable("Storage is unavailable.") from None

    def _client(self) -> BaseClient:
        """Build a client with transport retries and timeouts bounded by this probe."""

        if self.client_factory is not None:
            return self.client_factory()
        return boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name="us-east-1",
            config=Config(
                connect_timeout=self.transport_timeout_seconds,
                read_timeout=self.transport_timeout_seconds,
                retries={"max_attempts": 0},
            ),
        )
