"""Product-scoped private object upload and validation behavior."""

import io
from uuid import uuid4

import pytest
from app.shared.storage.objects import (
    CLEAN_PREFIX,
    MAX_PHOTO_BYTES,
    PRODUCT_CLEAN_PREFIX,
    PRODUCT_STAGING_PREFIX,
    ObjectOperationError,
    ObjectValidationError,
    PrivateObjectStore,
)
from botocore.exceptions import ClientError
from PIL import Image, PngImagePlugin


class _S3:
    def __init__(self, body: bytes = b"") -> None:
        self.body = body
        self.presigned: dict[str, object] | None = None
        self.calls: list[tuple[str, str]] = []
        self.puts: dict[str, bytes] = {}
        self.last_body: _Body | None = None
        self.fail_put = False
        self.fail_delete = False

    def generate_presigned_post(self, **kwargs: object) -> dict[str, object]:
        self.presigned = kwargs
        return {"url": "http://minio/upload", "fields": {"key": kwargs["Key"]}}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        self.calls.append(("get", Key))
        self.last_body = _Body(self.body)
        return {"Body": self.last_body, "ContentType": "image/png"}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, **kwargs: object) -> None:
        if self.fail_put:
            raise ClientError({"Error": {"Code": "InternalError"}}, "PutObject")
        self.calls.append(("put", Key))
        self.puts[Key] = Body

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.calls.append(("delete", Key))
        if self.fail_delete:
            raise ClientError({"Error": {"Code": "InternalError"}}, "DeleteObject")


class _Body:
    def __init__(self, value: bytes) -> None:
        self.value = value
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        return self.value if size < 0 else self.value[:size]

    def close(self) -> None:
        self.closed = True


def _png_with_metadata() -> bytes:
    image = Image.new("RGBA", (2, 2), (20, 40, 60, 255))
    info = PngImagePlugin.PngInfo()
    info.add_text("secret", "private metadata")
    output = io.BytesIO()
    image.save(output, format="PNG", pnginfo=info)
    return output.getvalue()


@pytest.mark.anyio
async def test_product_upload_is_scoped_and_bounded() -> None:
    client = _S3()
    account_id, product_id, asset_id = uuid4(), uuid4(), uuid4()
    store = PrivateObjectStore(
        endpoint_url="http://minio:9000",
        bucket_name="private",
        access_key_id="runtime",
        secret_access_key="secret",
        client_factory=lambda: client,
    )

    upload = await store.create_product_staging_upload(
        account_id=account_id,
        product_id=product_id,
        asset_id=asset_id,
        content_type="image/webp",
        size=MAX_PHOTO_BYTES,
    )

    assert upload.object_key == (
        f"{PRODUCT_STAGING_PREFIX}{account_id.hex}/{product_id.hex}/{asset_id.hex}"
    )
    assert upload.expires_in == 300
    assert client.presigned is not None
    assert client.presigned["Key"] == upload.object_key
    assert client.presigned["Conditions"] == [
        {"Content-Type": "image/webp"},
        ["content-length-range", 1, MAX_PHOTO_BYTES],
        {"key": upload.object_key},
    ]

    with pytest.raises(ObjectValidationError):
        await store.create_product_staging_upload(
            account_id=account_id,
            product_id=product_id,
            asset_id=uuid4(),
            content_type="image/gif",
            size=100,
        )
    with pytest.raises(ObjectValidationError):
        await store.create_product_staging_upload(
            account_id=account_id,
            product_id=product_id,
            asset_id=uuid4(),
            content_type="image/png",
            size=MAX_PHOTO_BYTES + 1,
        )


@pytest.mark.anyio
async def test_product_finalize_reencodes_bytes_and_strips_metadata() -> None:
    client = _S3(_png_with_metadata())
    account_id, product_id, asset_id = uuid4(), uuid4(), uuid4()
    store = PrivateObjectStore(
        endpoint_url="http://minio:9000",
        bucket_name="private",
        access_key_id="runtime",
        secret_access_key="secret",
        client_factory=lambda: client,
    )

    clean = await store.finalize_product_staging(
        account_id=account_id,
        product_id=product_id,
        asset_id=asset_id,
        declared_content_type="image/png",
    )

    staging_key = f"{PRODUCT_STAGING_PREFIX}{account_id.hex}/{product_id.hex}/{asset_id.hex}"
    assert clean.object_key == (
        f"{PRODUCT_CLEAN_PREFIX}{account_id.hex}/{product_id.hex}/{asset_id.hex}"
    )
    assert clean.media_type == "image/png"
    assert ("get", staging_key) in client.calls
    assert ("delete", staging_key) in client.calls
    with Image.open(io.BytesIO(client.puts[clean.object_key])) as image:
        assert image.info == {}
    assert client.last_body is not None and client.last_body.closed


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("body", "declared_content_type"),
    [
        (b"not an image", "image/png"),
        (_png_with_metadata(), "image/jpeg"),
        (b"x" * (MAX_PHOTO_BYTES + 1), None),
    ],
)
async def test_product_finalize_rejects_invalid_or_spoofed_bytes(
    body: bytes, declared_content_type: str | None
) -> None:
    client = _S3(body)
    store = PrivateObjectStore(
        endpoint_url="http://minio:9000",
        bucket_name="private",
        access_key_id="runtime",
        secret_access_key="secret",
        client_factory=lambda: client,
    )

    with pytest.raises(ObjectValidationError):
        await store.finalize_product_staging(
            account_id=uuid4(),
            product_id=uuid4(),
            asset_id=uuid4(),
            declared_content_type=declared_content_type,
        )

    assert not client.puts
    assert not any(action == "delete" for action, _ in client.calls)


@pytest.mark.anyio
async def test_product_object_reads_and_deletes_enforce_account_and_product_key() -> None:
    client = _S3(b"private image")
    account_id, product_id, asset_id = uuid4(), uuid4(), uuid4()
    store = PrivateObjectStore(
        endpoint_url="http://minio:9000",
        bucket_name="private",
        access_key_id="runtime",
        secret_access_key="secret",
        client_factory=lambda: client,
    )
    own_clean_key = f"{PRODUCT_CLEAN_PREFIX}{account_id.hex}/{product_id.hex}/{asset_id.hex}"

    assert await store.get_product_private(
        account_id=account_id, product_id=product_id, object_key=own_clean_key
    ) == (b"private image", "image/png")
    await store.delete_product_private(
        account_id=account_id, product_id=product_id, object_key=own_clean_key
    )

    invalid_keys = (
        f"{CLEAN_PREFIX}{account_id.hex}/{asset_id.hex}",
        f"{PRODUCT_CLEAN_PREFIX}{uuid4().hex}/{product_id.hex}/{asset_id.hex}",
        f"{PRODUCT_CLEAN_PREFIX}{account_id.hex}/{uuid4().hex}/{asset_id.hex}",
        f"{PRODUCT_CLEAN_PREFIX}{account_id.hex}/{product_id.hex}/./{asset_id.hex}",
        "arbitrary/object/path",
    )
    for object_key in invalid_keys:
        with pytest.raises(ObjectValidationError):
            await store.get_product_private(
                account_id=account_id, product_id=product_id, object_key=object_key
            )
        with pytest.raises(ObjectValidationError):
            await store.delete_product_private(
                account_id=account_id, product_id=product_id, object_key=object_key
            )
    own_staging_key = f"{PRODUCT_STAGING_PREFIX}{account_id.hex}/{product_id.hex}/{asset_id.hex}"
    with pytest.raises(ObjectValidationError):
        await store.get_product_private(
            account_id=account_id, product_id=product_id, object_key=own_staging_key
        )
    await store.delete_product_private(
        account_id=account_id, product_id=product_id, object_key=own_staging_key
    )
    assert client.calls == [
        ("get", own_clean_key),
        ("delete", own_clean_key),
        ("delete", own_staging_key),
    ]


@pytest.mark.anyio
async def test_product_finalize_fails_safely_without_deleting_staging_on_store_error() -> None:
    client = _S3(_png_with_metadata())
    client.fail_put = True
    account_id, product_id, asset_id = uuid4(), uuid4(), uuid4()
    staging_key = f"{PRODUCT_STAGING_PREFIX}{account_id.hex}/{product_id.hex}/{asset_id.hex}"
    store = PrivateObjectStore(
        endpoint_url="http://minio:9000",
        bucket_name="private",
        access_key_id="runtime",
        secret_access_key="secret",
        client_factory=lambda: client,
    )

    with pytest.raises(ObjectOperationError, match="could not be stored"):
        await store.finalize_product_staging(
            account_id=account_id,
            product_id=product_id,
            asset_id=asset_id,
            declared_content_type="image/png",
        )

    assert ("get", staging_key) in client.calls
    assert not any(action == "delete" for action, _ in client.calls)
