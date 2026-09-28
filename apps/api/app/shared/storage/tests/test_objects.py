import io
from uuid import UUID, uuid4

import pytest
from botocore.exceptions import ClientError
from PIL import Image, PngImagePlugin

from app.shared.storage.objects import (
    CLEAN_PREFIX,
    MAX_PHOTO_BYTES,
    STAGING_PREFIX,
    ObjectOperationError,
    ObjectValidationError,
    PrivateObjectStore,
)


class _Body:
    def __init__(self, value: bytes) -> None:
        self.value = value
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        return self.value if size < 0 else self.value[:size]

    def close(self) -> None:
        self.closed = True


class _S3:
    def __init__(self, body: bytes = b"") -> None:
        self.body = body
        self.calls: list[tuple[str, str]] = []
        self.puts: dict[str, bytes] = {}
        self.last_body: _Body | None = None
        self.fail_delete = False
        self.fail_put = False
        self.presigned_kwargs: dict[str, object] | None = None

    def generate_presigned_post(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("presigned", str(kwargs["Key"])))
        self.presigned_kwargs = kwargs
        return {"url": "http://minio/upload", "fields": {"key": kwargs["Key"]}}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        self.calls.append(("get", Key))
        self.last_body = _Body(self.body)
        return {"Body": self.last_body, "ContentType": "image/png"}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, **kwargs: object) -> None:
        self.calls.append(("put", Key))
        if self.fail_put:
            raise ClientError({"Error": {"Code": "InternalError"}}, "PutObject")
        self.puts[Key] = Body

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.calls.append(("delete", Key))
        if self.fail_delete:
            raise ClientError({"Error": {"Code": "InternalError"}}, "DeleteObject")


def _store(
    client: _S3,
    max_photo_bytes: int = 5 * 1024 * 1024,
    public_endpoint_url: str | None = None,
) -> PrivateObjectStore:
    return PrivateObjectStore(
        endpoint_url="http://minio:9000",
        public_endpoint_url=public_endpoint_url,
        bucket_name="private",
        access_key_id="runtime",
        secret_access_key="secret",
        client_factory=lambda: client,
        max_photo_bytes=max_photo_bytes,
    )


def _png_with_metadata() -> bytes:
    image = Image.new("RGBA", (2, 2), (20, 40, 60, 255))
    info = PngImagePlugin.PngInfo()
    info.add_text("secret", "private metadata")
    output = io.BytesIO()
    image.save(output, format="PNG", pnginfo=info)
    return output.getvalue()


def _image(format_name: str) -> bytes:
    image = Image.new("RGB", (3, 3), (20, 40, 60))
    output = io.BytesIO()
    image.save(output, format=format_name)
    return output.getvalue()


@pytest.mark.anyio
async def test_signed_upload_is_one_object_and_size_bounded() -> None:
    client = _S3()
    store = _store(client)
    account_id = uuid4()
    upload_id = uuid4()

    upload = await store.create_staging_upload(
        account_id=account_id,
        upload_id=upload_id,
        content_type="image/png",
        size=1024,
    )

    assert upload.object_key == f"{STAGING_PREFIX}{account_id.hex}/{upload_id.hex}"
    assert upload.upload_url == "http://minio:9000/upload"
    assert upload.expires_in == 300
    assert client.calls == [("presigned", upload.object_key)]
    assert client.presigned_kwargs is not None
    assert client.presigned_kwargs["ExpiresIn"] == 300
    assert client.presigned_kwargs["Conditions"] == [
        {"Content-Type": "image/png"},
        ["content-length-range", 1, 1024],
        {"key": upload.object_key},
    ]

    with pytest.raises(ObjectValidationError):
        await store.create_staging_upload(
            account_id=account_id,
            upload_id=uuid4(),
            content_type="text/plain",
            size=10,
        )

    assert client.calls == [("presigned", upload.object_key)]
    with pytest.raises(ObjectValidationError):
        await store.create_staging_upload(
            account_id=account_id,
            upload_id=uuid4(),
            content_type="image/png",
            size=5 * 1024 * 1024 + 1,
        )


@pytest.mark.anyio
async def test_signed_upload_uses_browser_reachable_public_endpoint() -> None:
    client = _S3()
    store = _store(client, public_endpoint_url="http://localhost:9000")

    upload = await store.create_staging_upload(
        account_id=uuid4(),
        upload_id=uuid4(),
        content_type="image/png",
        size=1024,
    )

    assert upload.upload_url == "http://localhost:9000/upload"

@pytest.mark.anyio
async def test_finalize_reencodes_image_and_removes_metadata() -> None:
    client = _S3(_png_with_metadata())
    store = _store(client)
    account_id = uuid4()
    upload_id = uuid4()

    clean = await store.finalize_staging(
        account_id=account_id,
        upload_id=upload_id,
        declared_content_type="image/png",
    )

    assert clean.object_key == f"{CLEAN_PREFIX}{account_id.hex}/{upload_id.hex}"
    assert clean.media_type == "image/png"
    assert ("put", clean.object_key) in client.calls
    assert ("delete", f"{STAGING_PREFIX}{account_id.hex}/{upload_id.hex}") in client.calls
    with Image.open(io.BytesIO(client.puts[clean.object_key])) as image:
        assert image.info == {}
    assert client.last_body is not None and client.last_body.closed


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("format_name", "media_type"), [("JPEG", "image/jpeg"), ("WEBP", "image/webp")]
)
async def test_finalize_accepts_supported_formats(format_name: str, media_type: str) -> None:
    client = _S3(_image(format_name))
    clean = await _store(client).finalize_staging(
        account_id=uuid4(), upload_id=uuid4(), declared_content_type=media_type
    )
    assert clean.media_type == media_type


@pytest.mark.anyio
async def test_finalize_rejects_oversized_body_and_canonical_key_is_required() -> None:
    client = _S3(b"x" * (MAX_PHOTO_BYTES + 1))
    store = _store(client)
    with pytest.raises(ObjectValidationError):
        await store.finalize_staging(account_id=uuid4(), upload_id=uuid4())
    with pytest.raises(ObjectValidationError):
        await store.get_private(object_key=f"{CLEAN_PREFIX}{uuid4().hex}/not-a-uuid")


@pytest.mark.anyio
async def test_finalize_interrupted_store_does_not_delete_staging() -> None:
    client = _S3(_png_with_metadata())
    client.fail_put = True
    with pytest.raises(ObjectOperationError, match="could not be stored"):
        await _store(client).finalize_staging(account_id=uuid4(), upload_id=uuid4())
    assert not any(action == "delete" for action, _ in client.calls)


@pytest.mark.anyio
async def test_finalize_normalizes_decompression_bomb(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_bomb(*args: object, **kwargs: object) -> None:
        raise Image.DecompressionBombError("dimensions are unsafe")

    monkeypatch.setattr(Image, "open", raise_bomb)
    with pytest.raises(ObjectValidationError):
        await _store(_S3(b"valid-looking"), max_photo_bytes=1024).finalize_staging(
            account_id=uuid4(), upload_id=uuid4()
        )


@pytest.mark.anyio
async def test_delete_failures_are_safe_typed_errors() -> None:
    client = _S3()
    client.fail_delete = True
    store = _store(client)
    with pytest.raises(ObjectOperationError, match="could not be deleted"):
        await store.delete_staging(account_id=uuid4(), upload_id=uuid4())


@pytest.mark.anyio
async def test_finalize_rejects_malformed_or_mismatched_bytes() -> None:
    client = _S3(b"not an image")
    store = _store(client)

    with pytest.raises(ObjectValidationError):
        await store.finalize_staging(account_id=uuid4(), upload_id=uuid4())

    client.body = _png_with_metadata()
    with pytest.raises(ObjectValidationError):
        await store.finalize_staging(
            account_id=uuid4(), upload_id=uuid4(), declared_content_type="image/jpeg"
        )


@pytest.mark.anyio
async def test_cleanup_only_deletes_owned_bounded_staging_keys() -> None:
    client = _S3()
    store = _store(client)
    account_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    owned = f"{STAGING_PREFIX}{account_id.hex}/{uuid4().hex}"
    foreign = f"{STAGING_PREFIX}{uuid4().hex}/{uuid4().hex}"

    deleted = await store.cleanup_staging(
        account_id=account_id,
        object_keys=[owned, foreign, f"{CLEAN_PREFIX}{account_id.hex}/{uuid4().hex}"],
    )

    assert deleted == 1
    assert ("delete", owned) in client.calls
    assert ("delete", foreign) not in client.calls
