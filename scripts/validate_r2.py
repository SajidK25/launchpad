"""Run a bounded private-object compatibility check against the isolated R2 bucket."""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from app.shared.storage.objects import (  # noqa: E402
    ObjectNotFound,
    PrivateObjectStore,
)


def _sample_png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (1, 1), color=(32, 64, 128)).save(output, format="PNG")
    return output.getvalue()


class ValidationConfigurationError(ValueError):
    """Safe configuration error that does not include credential values."""


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValidationConfigurationError(f"required validation setting is missing: {name}")
    return value


def validate() -> None:
    if os.environ.get("LAUNCHPAD_R2_VALIDATION_ENABLED") != "1":
        raise ValidationConfigurationError("explicit R2 validation opt-in is required")
    bucket = _required("LAUNCHPAD_R2_VALIDATION_BUCKET")
    production_bucket = _required("LAUNCHPAD_R2_PRODUCTION_BUCKET")
    if bucket == production_bucket:
        raise ValidationConfigurationError("validation bucket must differ from production")
    if bucket.lower().startswith(("prod-", "production-")):
        raise ValidationConfigurationError("production-named bucket cannot be a validation target")
    endpoint = _required("LAUNCHPAD_R2_ENDPOINT_URL")
    r2_account_id = _required("LAUNCHPAD_R2_ACCOUNT_ID")
    if (
        not r2_account_id.isalnum()
        or len(r2_account_id) != 32
        or r2_account_id.lower() != r2_account_id
    ):
        raise ValidationConfigurationError("validation account identifier is invalid")
    parsed_endpoint = urlsplit(endpoint)
    if (
        parsed_endpoint.scheme != "https"
        or parsed_endpoint.netloc != f"{r2_account_id}.r2.cloudflarestorage.com"
        or parsed_endpoint.path not in {"", "/"}
        or parsed_endpoint.query
        or parsed_endpoint.fragment
    ):
        raise ValidationConfigurationError("validation endpoint must be an HTTPS account endpoint")
    key_id = _required("LAUNCHPAD_R2_ACCESS_KEY_ID")
    secret = _required("LAUNCHPAD_R2_SECRET_ACCESS_KEY")
    owner_id = UUID(hex=secrets.token_hex(16))
    upload_id = UUID(hex=secrets.token_hex(16))
    staging_key = f"profile-staging/{owner_id.hex}/{upload_id.hex}"
    clean_key = f"profile-clean/{owner_id.hex}/{upload_id.hex}"
    body = _sample_png()
    client = boto3.client(
        "s3",
        endpoint_url=endpoint.rstrip("/"),
        region_name="auto",
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=5,
            read_timeout=10,
            retries={"max_attempts": 2},
        ),
    )
    storage = PrivateObjectStore(
        endpoint_url=endpoint,
        region_name="auto",
        bucket_name=bucket,
        access_key_id=key_id,
        secret_access_key=secret,
        client_factory=lambda: client,
    )
    staging_created = False
    clean_created = False
    try:
        client.head_bucket(Bucket=bucket)

        async def exercise_upload_lifecycle() -> None:
            nonlocal staging_created, clean_created
            staging_created = True
            await storage.put_staging(object_key=staging_key, body=body, content_type="image/png")
            finalized = await storage.finalize_staging(
                account_id=owner_id, upload_id=upload_id, declared_content_type="image/png"
            )
            staging_created = False
            clean_created = True
            if finalized.object_key != clean_key or finalized.media_type != "image/png":
                raise RuntimeError("R2 finalization returned unexpected private metadata")
            private_body, media_type = await storage.get_private(object_key=clean_key)
            if media_type != "image/png":
                raise RuntimeError("private finalized object did not match the staged image")
            with Image.open(BytesIO(private_body)) as image:
                image.load()
                if image.size != (1, 1) or image.getpixel((0, 0))[:3] != (32, 64, 128):
                    raise RuntimeError("private finalized image did not match the staged image")

        asyncio.run(exercise_upload_lifecycle())
        client.delete_object(Bucket=bucket, Key=clean_key)
        clean_created = False
        try:
            asyncio.run(storage.get_private(object_key=clean_key))
        except ObjectNotFound:
            pass
        else:
            raise RuntimeError("validation object remained readable after deletion")
        print(f"R2 validation succeeded for the private validation bucket '{bucket}'.")
    finally:
        if staging_created:
            try:
                asyncio.run(storage.delete_staging(account_id=owner_id, upload_id=upload_id))
            except (BotoCoreError, ClientError):
                print("R2 validation cleanup failed for its generated key.", file=sys.stderr)
        if clean_created:
            try:
                client.delete_object(Bucket=bucket, Key=clean_key)
            except (BotoCoreError, ClientError):
                print("R2 validation cleanup failed for its generated key.", file=sys.stderr)


def main() -> int:
    try:
        validate()
    except (
        ValidationConfigurationError,
        BotoCoreError,
        ClientError,
        TimeoutError,
        OSError,
        RuntimeError,
    ):
        print(
            "R2 validation failed; check protected validation configuration "
            "and bucket permissions.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
