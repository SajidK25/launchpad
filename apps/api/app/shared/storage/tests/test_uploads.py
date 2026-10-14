from __future__ import annotations

import asyncio
import io
from collections.abc import AsyncIterator

import pytest

from app.shared.storage.uploads import (
    BoundedUploadReceiver,
    UploadOverloaded,
    UploadReceiveError,
    UploadTimedOut,
    UploadTooLarge,
)


async def _body(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


@pytest.mark.anyio
async def test_receiver_preserves_exact_bytes_within_declared_limit() -> None:
    receiver = BoundedUploadReceiver(max_concurrent=2, max_bytes=1024, deadline_seconds=1)

    async with receiver.receive(
        _body(b"first ", b"second"), byte_limit=12, content_length=1
    ) as upload:
        assert upload.byte_count == 12
        assert upload.file.read() == b"first second"


@pytest.mark.anyio
async def test_actual_bytes_over_declared_limit_are_rejected_despite_short_content_length() -> None:
    receiver = BoundedUploadReceiver(max_concurrent=1, max_bytes=1024, deadline_seconds=1)

    with pytest.raises(UploadTooLarge):
        async with receiver.receive(_body(b"123", b"45"), byte_limit=4, content_length=1):
            pytest.fail("an oversized body must not be handed to a storage caller")


@pytest.mark.anyio
async def test_application_limit_is_enforced_when_content_length_is_missing() -> None:
    receiver = BoundedUploadReceiver(max_concurrent=1, max_bytes=4, deadline_seconds=1)

    with pytest.raises(UploadTooLarge):
        async with receiver.receive(_body(b"12345"), content_length=None):
            pytest.fail("the actual body must be counted without Content-Length")


@pytest.mark.anyio
async def test_slow_body_times_out_closes_temporary_file_and_releases_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary_files: list[io.BytesIO] = []

    def make_temporary_file(*, max_size: int, mode: str) -> io.BytesIO:
        file = io.BytesIO()
        temporary_files.append(file)
        return file

    monkeypatch.setattr(
        "app.shared.storage.uploads.tempfile.SpooledTemporaryFile", make_temporary_file
    )
    receiver = BoundedUploadReceiver(max_concurrent=1, max_bytes=1024, deadline_seconds=0.01)

    async def slow_body() -> AsyncIterator[bytes]:
        yield b"partial"
        await asyncio.sleep(0.05)

    with pytest.raises(UploadTimedOut):
        async with receiver.receive(slow_body()):
            pytest.fail("a timed-out body must not be handed to a storage caller")

    assert temporary_files and temporary_files[0].closed
    async with receiver.receive(_body(b"retry")) as upload:
        assert upload.file.read() == b"retry"


@pytest.mark.anyio
async def test_disconnected_body_closes_temporary_file_and_releases_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary_files: list[io.BytesIO] = []

    def make_temporary_file(*, max_size: int, mode: str) -> io.BytesIO:
        file = io.BytesIO()
        temporary_files.append(file)
        return file

    monkeypatch.setattr(
        "app.shared.storage.uploads.tempfile.SpooledTemporaryFile", make_temporary_file
    )
    receiver = BoundedUploadReceiver(max_concurrent=1, max_bytes=1024, deadline_seconds=1)

    async def disconnected_body() -> AsyncIterator[bytes]:
        yield b"partial"
        raise OSError("connection closed")

    with pytest.raises(UploadReceiveError):
        async with receiver.receive(disconnected_body()):
            pytest.fail("a disconnected body must not be handed to a storage caller")

    assert temporary_files and temporary_files[0].closed
    async with receiver.receive(_body(b"retry")) as upload:
        assert upload.file.read() == b"retry"


@pytest.mark.anyio
async def test_concurrent_limit_rejects_overload_and_releases_slot_after_success() -> None:
    receiver = BoundedUploadReceiver(max_concurrent=1, max_bytes=1024, deadline_seconds=1)
    started = asyncio.Event()
    release = asyncio.Event()

    async def held_body() -> AsyncIterator[bytes]:
        started.set()
        await release.wait()
        yield b"first"

    async def consume_held_body() -> None:
        async with receiver.receive(held_body()):
            pass

    first_upload = asyncio.create_task(consume_held_body())
    await started.wait()
    with pytest.raises(UploadOverloaded):
        async with receiver.receive(_body(b"overloaded")):
            pytest.fail("a full receiver must reject new work immediately")

    release.set()
    await first_upload
    async with receiver.receive(_body(b"after success")) as upload:
        assert upload.file.read() == b"after success"


@pytest.mark.anyio
async def test_cancellation_closes_temporary_file_and_releases_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary_files: list[io.BytesIO] = []

    def make_temporary_file(*, max_size: int, mode: str) -> io.BytesIO:
        file = io.BytesIO()
        temporary_files.append(file)
        return file

    monkeypatch.setattr(
        "app.shared.storage.uploads.tempfile.SpooledTemporaryFile", make_temporary_file
    )
    receiver = BoundedUploadReceiver(max_concurrent=1, max_bytes=1024, deadline_seconds=1)
    started = asyncio.Event()

    async def blocked_body() -> AsyncIterator[bytes]:
        yield b"partial"
        started.set()
        await asyncio.Event().wait()

    async def consume_blocked_body() -> None:
        async with receiver.receive(blocked_body()):
            pass

    task = asyncio.create_task(consume_blocked_body())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert temporary_files and temporary_files[0].closed
    async with receiver.receive(_body(b"after cancellation")) as upload:
        assert upload.file.read() == b"after cancellation"
