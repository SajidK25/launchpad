"""Bounded raw upload intake with finite process-local resource limits."""

from __future__ import annotations

import asyncio
import math
import tempfile
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import BinaryIO, cast

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


class UploadReceiveError(RuntimeError):
    """The upload body could not be received safely."""


class UploadTooLarge(UploadReceiveError):
    """Actual bytes exceeded the request or application limit."""


class UploadTimedOut(UploadReceiveError):
    """The request body did not finish before its deadline."""


class UploadOverloaded(UploadReceiveError):
    """All bounded upload slots are currently occupied."""


@dataclass(frozen=True, slots=True)
class ReceivedUpload:
    """A rewound temporary body and its actual byte count."""

    file: BinaryIO
    byte_count: int


class BoundedUploadReceiver:
    """Receive bodies into bounded memory while limiting work per process.

    Spool capacity is bounded to ``max_concurrent * max_bytes`` per receiver.
    Defaults cap spooled bodies at 20 MiB total (four 5 MiB bodies) and apply a
    30-second deadline to each body.
    ``content_length`` is accepted as metadata for callers but never trusted as
    the byte-count limit; actual yielded chunks are always counted.
    """

    def __init__(
        self,
        *,
        max_concurrent: int = 4,
        max_bytes: int = MAX_UPLOAD_BYTES,
        deadline_seconds: float = 30.0,
    ) -> None:
        if max_concurrent <= 0:
            raise ValueError("upload concurrency must be positive")
        if max_bytes <= 0 or max_bytes > MAX_UPLOAD_BYTES:
            raise ValueError("upload byte limit is outside the supported range")
        if not math.isfinite(deadline_seconds) or deadline_seconds <= 0:
            raise ValueError("upload deadline must be finite and positive")
        self.max_bytes = max_bytes
        self.deadline_seconds = deadline_seconds
        self._slots = asyncio.BoundedSemaphore(max_concurrent)

    @asynccontextmanager
    async def receive(
        self,
        stream: AsyncIterable[bytes],
        *,
        byte_limit: int | None = None,
        content_length: int | None = None,
    ) -> AsyncIterator[ReceivedUpload]:
        """Bound, spool and yield a rewound body; always release its file and slot."""

        del content_length  # The header is not authoritative; count the stream itself.
        limit = self.max_bytes if byte_limit is None else min(byte_limit, self.max_bytes)
        if limit <= 0:
            raise ValueError("upload byte limit must be positive")
        if self._slots.locked():
            raise UploadOverloaded("upload capacity is busy")

        await self._slots.acquire()
        temporary: BinaryIO | None = None
        try:
            temporary = cast(
                BinaryIO,
                tempfile.SpooledTemporaryFile(max_size=limit, mode="w+b"),
            )
            byte_count = 0
            try:
                async with asyncio.timeout(self.deadline_seconds):
                    async for chunk in stream:
                        if not isinstance(chunk, bytes):
                            raise UploadReceiveError("upload stream returned invalid data")
                        byte_count += len(chunk)
                        if byte_count > limit:
                            raise UploadTooLarge("upload exceeds its byte limit")
                        temporary.write(chunk)
            except TimeoutError:
                raise UploadTimedOut("upload body exceeded its deadline") from None
            except UploadReceiveError:
                raise
            except Exception:
                raise UploadReceiveError("upload body could not be received") from None

            temporary.seek(0)
            yield ReceivedUpload(temporary, byte_count)
        finally:
            try:
                if temporary is not None:
                    temporary.close()
            finally:
                self._slots.release()


DEFAULT_UPLOAD_RECEIVER = BoundedUploadReceiver()
