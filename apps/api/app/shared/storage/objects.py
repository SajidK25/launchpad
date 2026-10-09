"""Bounded private profile-photo staging and finalization operations."""

from __future__ import annotations

import asyncio
import io
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol, cast
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import boto3
from botocore.client import BaseClient, Config
from botocore.exceptions import BotoCoreError, ClientError
from PIL import Image, UnidentifiedImageError

MAX_PHOTO_BYTES = 5 * 1024 * 1024
STAGING_PREFIX = "profile-staging/"
CLEAN_PREFIX = "profile-clean/"
PRODUCT_STAGING_PREFIX = "product-staging/"
PRODUCT_CLEAN_PREFIX = "product-clean/"
SUPPORTED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_SAFE_ID = re.compile(r"^[0-9a-f]{32}$")
ClientFactory = Callable[[], BaseClient]


class _BodyStream(Protocol):
    def read(self, size: int = -1) -> bytes: ...

    def close(self) -> None: ...


class ObjectOperationError(RuntimeError):
    """Base error for safe private-object operations."""


class ObjectValidationError(ObjectOperationError):
    """The staged bytes are not a supported bounded image."""


class ObjectNotFound(ObjectOperationError):
    """The requested private object does not exist."""


@dataclass(frozen=True, slots=True)
class StagingUpload:
    """Opaque one-object upload instructions."""

    object_key: str
    upload_url: str
    fields: dict[str, str]
    expires_in: int


@dataclass(frozen=True, slots=True)
class CleanPhoto:
    """Opaque reference to a validated private image."""

    object_key: str
    media_type: str
    byte_count: int


class PrivateObjectStore:
    """Perform private S3 operations without producing public URLs."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        public_endpoint_url: str | None = None,
        region_name: str = "us-east-1",
        bucket_name: str,
        access_key_id: str,
        secret_access_key: str,
        client_factory: ClientFactory | None = None,
        max_photo_bytes: int = MAX_PHOTO_BYTES,
        image_concurrency: int = 4,
    ) -> None:
        if max_photo_bytes <= 0 or max_photo_bytes > MAX_PHOTO_BYTES:
            raise ValueError("photo size limit is invalid")
        if image_concurrency <= 0:
            raise ValueError("image concurrency is invalid")
        self.endpoint_url = endpoint_url
        self.public_endpoint_url = public_endpoint_url or endpoint_url
        self.region_name = region_name
        self.bucket_name = bucket_name
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.client_factory = client_factory
        self.max_photo_bytes = max_photo_bytes
        self._image_slots = threading.BoundedSemaphore(image_concurrency)

    async def create_staging_upload(
        self,
        *,
        account_id: UUID | str,
        upload_id: UUID | str,
        content_type: str,
        size: int,
        expires_in: int = 300,
    ) -> StagingUpload:
        """Issue a short-lived presigned POST for exactly one bounded staging object."""

        return await self._create_staging_upload(
            key=_staging_key(account_id, upload_id),
            content_type=content_type,
            size=size,
            expires_in=expires_in,
        )

    async def create_product_staging_upload(
        self,
        *,
        account_id: UUID | str,
        product_id: UUID | str,
        asset_id: UUID | str,
        content_type: str,
        size: int,
        expires_in: int = 300,
    ) -> StagingUpload:
        """Issue a bounded upload restricted to one account/product/asset key."""

        return await self._create_staging_upload(
            key=_product_staging_key(account_id, product_id, asset_id),
            content_type=content_type,
            size=size,
            expires_in=expires_in,
        )

    async def put_staging(self, *, object_key: str, body: bytes, content_type: str) -> None:
        """Write bounded bytes to an owner-scoped private staging key."""

        _assert_staging_key(object_key)
        if content_type not in SUPPORTED_MEDIA_TYPES:
            raise ObjectValidationError("unsupported image type")
        if not body or len(body) > self.max_photo_bytes:
            raise ObjectValidationError("image is too large or empty")

        def write() -> None:
            try:
                self._client().put_object(
                    Bucket=self.bucket_name,
                    Key=object_key,
                    Body=body,
                    ContentType=content_type,
                )
            except (ClientError, BotoCoreError):
                raise ObjectOperationError("staged image could not be stored") from None

        await asyncio.to_thread(write)

    async def _create_staging_upload(
        self, *, key: str, content_type: str, size: int, expires_in: int
    ) -> StagingUpload:
        """Create the common signed POST after applying the image and expiry bounds."""

        if content_type not in SUPPORTED_MEDIA_TYPES:
            raise ObjectValidationError("unsupported image type")
        if size <= 0 or size > self.max_photo_bytes:
            raise ObjectValidationError("image is too large")
        if expires_in < 60 or expires_in > 900:
            raise ValueError("upload expiry is outside the allowed range")

        def issue() -> StagingUpload:
            client = self._client()
            response = client.generate_presigned_post(
                Bucket=self.bucket_name,
                Key=key,
                Fields={"Content-Type": content_type},
                Conditions=[
                    {"Content-Type": content_type},
                    ["content-length-range", 1, size],
                    {"key": key},
                ],
                ExpiresIn=expires_in,
            )
            fields = {str(name): str(value) for name, value in response["fields"].items()}
            upload_url = _replace_upload_endpoint(str(response["url"]), self.public_endpoint_url)
            return StagingUpload(key, upload_url, fields, expires_in)

        return await asyncio.to_thread(issue)

    async def finalize_staging(
        self,
        *,
        account_id: UUID | str,
        upload_id: UUID | str,
        declared_content_type: str | None = None,
    ) -> CleanPhoto:
        """Validate actual staged bytes, strip metadata, and promote privately."""

        return await self._finalize_objects(
            staging_key=_staging_key(account_id, upload_id),
            clean_key=_clean_key(account_id, upload_id),
            declared_content_type=declared_content_type,
        )

    async def finalize_product_staging(
        self,
        *,
        account_id: UUID | str,
        product_id: UUID | str,
        asset_id: UUID | str,
        declared_content_type: str | None = None,
    ) -> CleanPhoto:
        """Validate product staging bytes, remove metadata, and promote to a private key."""

        return await self._finalize_objects(
            staging_key=_product_staging_key(account_id, product_id, asset_id),
            clean_key=_product_clean_key(account_id, product_id, asset_id),
            declared_content_type=declared_content_type,
        )

    async def _finalize_objects(
        self,
        *,
        staging_key: str,
        clean_key: str,
        declared_content_type: str | None,
    ) -> CleanPhoto:
        """Share byte-level validation and private promotion for both storage namespaces."""

        def finalize() -> CleanPhoto:
            client = self._client()
            try:
                response = client.get_object(Bucket=self.bucket_name, Key=staging_key)
                body = _read_response_body(response, self.max_photo_bytes + 1)
            except ClientError as error:
                if str(error.response.get("Error", {}).get("Code", "")) in {
                    "404",
                    "NoSuchKey",
                    "NoSuchObject",
                }:
                    raise ObjectNotFound("staged image was not found") from None
                raise ObjectOperationError("staged image could not be read") from None
            except BotoCoreError:
                raise ObjectOperationError("staged image could not be read") from None

            with self._image_slots:
                media_type, encoded = _validate_and_reencode(body, self.max_photo_bytes)
            if declared_content_type is not None and declared_content_type != media_type:
                raise ObjectValidationError("declared image type does not match bytes")
            try:
                client.put_object(
                    Bucket=self.bucket_name,
                    Key=clean_key,
                    Body=encoded,
                    ContentType=media_type,
                )
                client.delete_object(Bucket=self.bucket_name, Key=staging_key)
            except (ClientError, BotoCoreError):
                raise ObjectOperationError("validated image could not be stored") from None
            return CleanPhoto(clean_key, media_type, len(encoded))

        return await asyncio.to_thread(finalize)

    async def get_private(self, *, object_key: str) -> tuple[bytes, str | None]:
        """Read an object only from the adapter's private profile prefixes."""

        _assert_private_key(object_key)

        def read() -> tuple[bytes, str | None]:
            try:
                response = self._client().get_object(Bucket=self.bucket_name, Key=object_key)
                body = _read_response_body(response, self.max_photo_bytes + 1)
            except ClientError as error:
                if _is_not_found(error):
                    raise ObjectNotFound("private object was not found") from None
                raise ObjectOperationError("private object could not be read") from None
            except BotoCoreError:
                raise ObjectOperationError("private object could not be read") from None
            if len(body) > self.max_photo_bytes:
                raise ObjectOperationError("private object exceeds the size limit")
            return body, response.get("ContentType")

        return await asyncio.to_thread(read)

    async def get_product_private(
        self, *, account_id: UUID | str, product_id: UUID | str, object_key: str
    ) -> tuple[bytes, str | None]:
        """Read only a clean product key owned by the supplied account and product."""

        _assert_product_key(
            object_key, account_id=account_id, product_id=product_id, clean_only=True
        )

        def read() -> tuple[bytes, str | None]:
            try:
                response = self._client().get_object(Bucket=self.bucket_name, Key=object_key)
                body = _read_response_body(response, self.max_photo_bytes + 1)
            except ClientError as error:
                if _is_not_found(error):
                    raise ObjectNotFound("product object was not found") from None
                raise ObjectOperationError("product object could not be read") from None
            except BotoCoreError:
                raise ObjectOperationError("product object could not be read") from None
            if len(body) > self.max_photo_bytes:
                raise ObjectOperationError("product object exceeds the size limit")
            return body, response.get("ContentType")

        return await asyncio.to_thread(read)

    async def delete_product_private(
        self, *, account_id: UUID | str, product_id: UUID | str, object_key: str
    ) -> None:
        """Delete only a product-scoped object belonging to the supplied account/product."""

        _assert_product_key(object_key, account_id=account_id, product_id=product_id)

        def delete() -> None:
            try:
                self._client().delete_object(Bucket=self.bucket_name, Key=object_key)
            except (ClientError, BotoCoreError):
                raise ObjectOperationError("product object could not be deleted") from None

        await asyncio.to_thread(delete)

    async def delete_staging(self, *, account_id: UUID | str, upload_id: UUID | str) -> None:
        """Delete exactly one owner-scoped staging object."""

        key = _staging_key(account_id, upload_id)

        def delete() -> None:
            try:
                self._client().delete_object(Bucket=self.bucket_name, Key=key)
            except (ClientError, BotoCoreError):
                raise ObjectOperationError("staged image could not be deleted") from None

        await asyncio.to_thread(delete)

    async def cleanup_staging(
        self, *, account_id: UUID | str, object_keys: list[str], limit: int = 100
    ) -> int:
        """Delete only bounded staging keys belonging to one account."""

        if limit <= 0 or limit > 1000:
            raise ValueError("cleanup limit is invalid")
        account = _id(account_id)
        owned = [
            key
            for key in object_keys[:limit]
            if key.startswith(f"{STAGING_PREFIX}{account}/")
            and PurePosixPath(key).name
            and _SAFE_ID.fullmatch(PurePosixPath(key).name)
        ]

        def cleanup() -> int:
            client = self._client()
            try:
                for key in owned:
                    client.delete_object(Bucket=self.bucket_name, Key=key)
            except (ClientError, BotoCoreError):
                raise ObjectOperationError("staged images could not be cleaned up") from None
            return len(owned)

        return await asyncio.to_thread(cleanup)

    def _client(self) -> BaseClient:
        if self.client_factory is not None:
            return self.client_factory()
        return boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name=self.region_name,
            config=Config(retries={"max_attempts": 0}),
        )


def _id(value: UUID | str) -> str:
    try:
        normalized = UUID(str(value)).hex
    except ValueError as error:
        raise ObjectValidationError("object identifier is invalid") from error
    return normalized


def _staging_key(account_id: UUID | str, upload_id: UUID | str) -> str:
    return f"{STAGING_PREFIX}{_id(account_id)}/{_id(upload_id)}"


def _replace_upload_endpoint(upload_url: str, public_endpoint_url: str) -> str:
    """Keep the signed path while exposing a browser-reachable endpoint."""

    signed = urlsplit(upload_url)
    public = urlsplit(public_endpoint_url)
    if not signed.scheme or not signed.netloc or not public.scheme or not public.netloc:
        raise ObjectOperationError("storage upload endpoint is invalid")
    return urlunsplit((public.scheme, public.netloc, signed.path, signed.query, signed.fragment))


def _clean_key(account_id: UUID | str, upload_id: UUID | str) -> str:
    return f"{CLEAN_PREFIX}{_id(account_id)}/{_id(upload_id)}"


def _product_staging_key(
    account_id: UUID | str, product_id: UUID | str, asset_id: UUID | str
) -> str:
    return f"{PRODUCT_STAGING_PREFIX}{_id(account_id)}/{_id(product_id)}/{_id(asset_id)}"


def _product_clean_key(account_id: UUID | str, product_id: UUID | str, asset_id: UUID | str) -> str:
    return f"{PRODUCT_CLEAN_PREFIX}{_id(account_id)}/{_id(product_id)}/{_id(asset_id)}"


def _assert_private_key(object_key: str) -> None:
    parts = PurePosixPath(object_key).parts
    if (
        len(parts) != 3
        or parts[0] not in {STAGING_PREFIX[:-1], CLEAN_PREFIX[:-1]}
        or not all(_SAFE_ID.fullmatch(part) for part in parts[1:])
    ):
        raise ObjectValidationError("object key is outside the private profile prefixes")


def _assert_staging_key(object_key: str) -> None:
    """Accept only canonical profile or product staging keys, never clean objects."""

    parts = PurePosixPath(object_key).parts
    if len(parts) == 3 and parts[0] == STAGING_PREFIX[:-1]:
        _assert_private_key(object_key)
        return
    if (
        len(parts) == 4
        and parts[0] == PRODUCT_STAGING_PREFIX[:-1]
        and PurePosixPath(object_key).as_posix() == object_key
        and all(_SAFE_ID.fullmatch(part) for part in parts[1:])
    ):
        _assert_product_key(object_key, account_id=parts[1], product_id=parts[2])
        return
    raise ObjectValidationError("object key is outside private staging prefixes")


def _assert_product_key(
    object_key: str,
    *,
    account_id: UUID | str,
    product_id: UUID | str,
    clean_only: bool = False,
) -> None:
    parts = PurePosixPath(object_key).parts
    expected_account = _id(account_id)
    expected_product = _id(product_id)
    if (
        len(parts) != 4
        or PurePosixPath(object_key).as_posix() != object_key
        or parts[0] not in {PRODUCT_STAGING_PREFIX[:-1], PRODUCT_CLEAN_PREFIX[:-1]}
        or (clean_only and parts[0] != PRODUCT_CLEAN_PREFIX[:-1])
        or parts[1] != expected_account
        or parts[2] != expected_product
        or not _SAFE_ID.fullmatch(parts[3])
    ):
        raise ObjectValidationError("object key is outside the owned product prefixes")


def _is_not_found(error: ClientError) -> bool:
    return str(error.response.get("Error", {}).get("Code", "")) in {
        "404",
        "NoSuchKey",
        "NoSuchObject",
    }


def _read_response_body(response: dict[str, object], limit: int) -> bytes:
    body = cast(_BodyStream, response["Body"])
    try:
        return body.read(limit)
    finally:
        close = getattr(body, "close", None)
        if callable(close):
            close()


def _validate_and_reencode(body: bytes, max_bytes: int) -> tuple[str, bytes]:
    if not body or len(body) > max_bytes:
        raise ObjectValidationError("image is too large or empty")
    try:
        with Image.open(io.BytesIO(body)) as image:
            actual_format = (image.format or "").upper()
            media_type = {
                "JPEG": "image/jpeg",
                "PNG": "image/png",
                "WEBP": "image/webp",
            }.get(actual_format)
            if media_type is None:
                raise ObjectValidationError("unsupported image format")
            image.verify()
        with Image.open(io.BytesIO(body)) as image:
            output = io.BytesIO()
            save_format = actual_format
            output_image: Image.Image = image
            if save_format == "JPEG":
                output_image = image.convert("RGB")
            output_image.save(output, format=save_format, exif=b"")
            encoded = output.getvalue()
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        OverflowError,
        SyntaxError,
        ValueError,
    ) as error:
        raise ObjectValidationError("image bytes are invalid") from error
    if not encoded or len(encoded) > max_bytes:
        raise ObjectValidationError("encoded image is too large")
    return media_type, encoded
