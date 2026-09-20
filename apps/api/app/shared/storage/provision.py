"""MinIO-only bootstrap operations for a private local bucket and runtime identity."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from urllib.parse import urlsplit

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError
from minio.credentials.providers import StaticProvider
from minio.error import MinioAdminException
from minio.minioadmin import MinioAdmin


class StorageProvisioningError(RuntimeError):
    """A safe local provisioning failure that does not include credentials or object data."""


class PublicBucketPolicyError(StorageProvisioningError):
    """The bucket policy would expose objects anonymously and is left unchanged."""


@dataclass(frozen=True)
class StorageProvisioner:
    """Create and verify a private MinIO bucket with a limited runtime identity."""

    endpoint_url: str
    bootstrap_access_key_id: str
    bootstrap_secret_access_key: str
    runtime_access_key_id: str
    runtime_secret_access_key: str

    async def prepare(self, bucket_name: str) -> None:
        """Prepare the named bucket without deleting objects or weakening existing policy."""

        await asyncio.to_thread(self._prepare_sync, bucket_name)

    def _prepare_sync(self, bucket_name: str) -> None:
        """Perform local MinIO administration outside an application event loop."""

        client = self._bootstrap_client()
        if not _bucket_exists(client, bucket_name):
            client.create_bucket(Bucket=bucket_name)
        _assert_private_policy(client, bucket_name)
        self._ensure_runtime_identity(bucket_name)

    def _bootstrap_client(self) -> BaseClient:
        """Create the administration-plane S3 client with bootstrap credentials only."""

        return boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.bootstrap_access_key_id,
            aws_secret_access_key=self.bootstrap_secret_access_key,
            region_name="us-east-1",
        )

    def _ensure_runtime_identity(self, bucket_name: str) -> None:
        """Create or update the MinIO runtime identity with bucket-scoped read permission."""

        endpoint = urlsplit(self.endpoint_url)
        if endpoint.hostname is None or endpoint.port is None:
            raise StorageProvisioningError("Storage endpoint is invalid.")
        admin = MinioAdmin(
            endpoint=f"{endpoint.hostname}:{endpoint.port}",
            credentials=StaticProvider(
                self.bootstrap_access_key_id, self.bootstrap_secret_access_key
            ),
            secure=endpoint.scheme == "https",
        )
        try:
            admin.user_add(self.runtime_access_key_id, self.runtime_secret_access_key)
        except MinioAdminException as error:
            # Repeated preparation can encounter an existing runtime identity.
            if "already exists" not in str(error).lower():
                raise StorageProvisioningError(
                    "Storage runtime identity could not be prepared."
                ) from None
        policy_name = f"launchpad-runtime-{bucket_name}"
        admin.policy_add(policy_name, policy=_runtime_policy(bucket_name))
        admin.policy_set(policy_name, user=self.runtime_access_key_id)


def _bucket_exists(client: BaseClient, bucket_name: str) -> bool:
    """Return whether the bootstrap identity can see the named bucket."""

    try:
        client.head_bucket(Bucket=bucket_name)
    except ClientError as error:
        if str(error.response.get("Error", {}).get("Code", "")) in {"404", "NoSuchBucket"}:
            return False
        raise StorageProvisioningError("Storage bucket could not be inspected.") from None
    return True


def _assert_private_policy(client: BaseClient, bucket_name: str) -> None:
    """Reject a public policy without changing it or any stored objects."""

    try:
        policy = client.get_bucket_policy(Bucket=bucket_name)["Policy"]
    except ClientError as error:
        if str(error.response.get("Error", {}).get("Code", "")) == "NoSuchBucketPolicy":
            return
        raise StorageProvisioningError("Storage bucket policy could not be inspected.") from None
    if _policy_allows_anonymous_access(policy):
        raise PublicBucketPolicyError("Storage bucket policy permits anonymous access.")


def _policy_allows_anonymous_access(policy: str) -> bool:
    """Recognize anonymous Allow statements without logging policy contents."""

    try:
        statements = json.loads(policy).get("Statement", [])
    except json.JSONDecodeError:
        raise StorageProvisioningError("Storage bucket policy is invalid.") from None
    for statement in statements:
        if statement.get("Effect") != "Allow":
            continue
        principal = statement.get("Principal")
        if principal == "*" or principal in ({"AWS": "*"}, {"AWS": ["*"]}):
            return True
    return False


def _runtime_policy(bucket_name: str) -> dict[str, object]:
    """Grant only the runtime calls required for private read-only readiness checks."""

    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:GetBucketLocation", "s3:GetBucketPolicy", "s3:ListBucket"],
                "Resource": [f"arn:aws:s3:::{bucket_name}"],
            }
        ],
    }
