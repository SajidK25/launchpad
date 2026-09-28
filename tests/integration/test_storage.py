"""Real MinIO checks for private, repeatable, bounded storage preparation."""

from __future__ import annotations

import asyncio
import json
import time

import boto3
import pytest
from app.shared.storage.client import (
    StorageAccessDenied,
    StorageClient,
    StorageProbeTimeout,
    StorageUnavailable,
)
from app.shared.storage.provision import PublicBucketPolicyError, StorageProvisioner
from botocore import UNSIGNED
from botocore.client import BaseClient, Config
from botocore.exceptions import ClientError
from conftest import StorageCredentials


def _provisioner(credentials: StorageCredentials) -> StorageProvisioner:
    return StorageProvisioner(
        endpoint_url=credentials.endpoint_url,
        bootstrap_access_key_id=credentials.bootstrap_access_key_id,
        bootstrap_secret_access_key=credentials.bootstrap_secret_access_key,
        runtime_access_key_id=credentials.runtime_access_key_id,
        runtime_secret_access_key=credentials.runtime_secret_access_key,
    )


def _runtime_client(credentials: StorageCredentials) -> BaseClient:
    return boto3.client(
        "s3",
        endpoint_url=credentials.endpoint_url,
        aws_access_key_id=credentials.runtime_access_key_id,
        aws_secret_access_key=credentials.runtime_secret_access_key,
        region_name="us-east-1",
    )


def test_private_bucket_preparation_repeats_without_losing_objects(
    storage_credentials: StorageCredentials,
    storage_bucket: str,
    s3_client: BaseClient,
) -> None:
    """Provisioning creates a private bucket once and preserves its existing bytes."""

    async def verify() -> None:
        provisioner = _provisioner(storage_credentials)
        await provisioner.prepare(storage_bucket)
        s3_client.put_object(Bucket=storage_bucket, Key="sample.txt", Body=b"t5-preserved")
        await provisioner.prepare(storage_bucket)
        stored = s3_client.get_object(Bucket=storage_bucket, Key="sample.txt")
        assert stored["Body"].read() == b"t5-preserved"

    asyncio.run(verify())


def test_anonymous_access_is_denied_and_runtime_cannot_administer_bucket(
    storage_credentials: StorageCredentials,
    storage_bucket: str,
    s3_client: BaseClient,
) -> None:
    """Runtime credentials can probe prepared storage but cannot alter bucket administration."""

    async def verify() -> None:
        await _provisioner(storage_credentials).prepare(storage_bucket)
        s3_client.put_object(Bucket=storage_bucket, Key="private.txt", Body=b"T5_OBJECT_SENTINEL")
        await StorageClient(
            endpoint_url=storage_credentials.endpoint_url,
            access_key_id=storage_credentials.runtime_access_key_id,
            secret_access_key=storage_credentials.runtime_secret_access_key,
        ).probe(storage_bucket)

    asyncio.run(verify())
    anonymous = boto3.client(
        "s3",
        endpoint_url=storage_credentials.endpoint_url,
        config=Config(signature_version=UNSIGNED),
        region_name="us-east-1",
    )
    with pytest.raises(ClientError):
        anonymous.get_object(Bucket=storage_bucket, Key="private.txt")
    with pytest.raises(ClientError):
        _runtime_client(storage_credentials).create_bucket(Bucket=f"{storage_bucket}-denied")


def test_public_bucket_policy_is_rejected_without_being_rewritten(
    storage_credentials: StorageCredentials,
    storage_bucket: str,
    s3_client: BaseClient,
) -> None:
    """Provisioning fails safely when an existing bucket policy permits anonymous access."""

    s3_client.create_bucket(Bucket=storage_bucket)
    public_policy = json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:GetObject",
                    "Resource": f"arn:aws:s3:::{storage_bucket}/*",
                }
            ],
        }
    )
    s3_client.put_bucket_policy(Bucket=storage_bucket, Policy=public_policy)
    stored_policy = s3_client.get_bucket_policy(Bucket=storage_bucket)["Policy"]

    with pytest.raises(PublicBucketPolicyError) as error:
        asyncio.run(_provisioner(storage_credentials).prepare(storage_bucket))

    assert "anonymous" in str(error.value)
    assert s3_client.get_bucket_policy(Bucket=storage_bucket)["Policy"] == stored_policy


def test_safe_storage_failures_do_not_echo_credentials_or_object_content(
    storage_credentials: StorageCredentials,
    storage_bucket: str,
) -> None:
    """Unavailable and denied storage become typed failures without input disclosure."""

    async def verify() -> None:
        denied = StorageClient(
            endpoint_url=storage_credentials.endpoint_url,
            access_key_id="T5_ACCESS_SENTINEL",
            secret_access_key="T5_SECRET_SENTINEL",
        )
        unavailable = StorageClient(
            endpoint_url="http://storage-missing:9000",
            access_key_id="T5_ACCESS_SENTINEL",
            secret_access_key="T5_SECRET_SENTINEL",
            transport_timeout_seconds=0.1,
        )
        with pytest.raises(StorageAccessDenied) as denied_error:
            await denied.probe(storage_bucket)
        with pytest.raises(StorageUnavailable) as unavailable_error:
            await unavailable.probe(storage_bucket, timeout_seconds=0.2)
        message = f"{denied_error.value} {unavailable_error.value}"
        assert "T5_ACCESS_SENTINEL" not in message
        assert "T5_SECRET_SENTINEL" not in message
        assert "T5_OBJECT_SENTINEL" not in message

    asyncio.run(verify())


def test_probe_is_read_only_and_timeout_does_not_block_the_event_loop(
    storage_credentials: StorageCredentials,
    storage_bucket: str,
) -> None:
    """The probe uses only metadata calls and times out while other coroutines progress."""

    class SlowClient:
        def get_bucket_location(self, *, Bucket: str) -> None:
            time.sleep(0.2)

        def get_bucket_policy(self, *, Bucket: str) -> None:
            raise AssertionError("timed-out probe should not reach a second operation")

    async def verify() -> None:
        operations: list[str] = []
        await _provisioner(storage_credentials).prepare(storage_bucket)
        runtime = _runtime_client(storage_credentials)
        runtime.meta.events.register(
            "before-call.s3", lambda model, **_: operations.append(model.name)
        )
        await StorageClient(
            endpoint_url=storage_credentials.endpoint_url,
            access_key_id=storage_credentials.runtime_access_key_id,
            secret_access_key=storage_credentials.runtime_secret_access_key,
            client_factory=lambda: runtime,
        ).probe(storage_bucket)
        assert operations == ["GetBucketLocation", "GetBucketPolicy"]

        timed_out = StorageClient(
            endpoint_url=storage_credentials.endpoint_url,
            access_key_id=storage_credentials.runtime_access_key_id,
            secret_access_key=storage_credentials.runtime_secret_access_key,
            client_factory=SlowClient,
        ).probe(storage_bucket, timeout_seconds=0.05)
        task = asyncio.create_task(timed_out)
        ticks = 0
        while not task.done():
            ticks += 1
            await asyncio.sleep(0.01)
        with pytest.raises(StorageProbeTimeout):
            await task
        assert ticks >= 3

    asyncio.run(verify())
