"""Product-scoped tickets and identifier-only discussion invalidations."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.comments.service import ProductDiscussionAccess
from app.shared.config.settings import Settings
from app.shared.security.csrf import RequestSecurityError, validate_origin

_TICKET_TTL_SECONDS = 120
_REVALIDATE_SECONDS = 30.0
_POLL_SECONDS = 1.0
_CONNECTION_LEASE_SECONDS = 90
_CONNECTION_REFRESH_SECONDS = 30.0
_MAX_CONNECTIONS_PER_PRODUCT = 100
_MAX_CONNECTIONS_PER_SOURCE = 10
_CHANNEL_PREFIX = "launchpad:comments:product:"

_CLAIM_CONNECTION = """
-- launchpad:comment-connection-claim
local now = tonumber(ARGV[2])
local lease_ms = tonumber(ARGV[5]) * 1000
for index = 1, 2 do
  redis.call('ZREMRANGEBYSCORE', KEYS[index], '-inf', now - lease_ms)
end
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then return 0 end
if redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[4]) then return 0 end
for index = 1, 2 do
  redis.call('ZADD', KEYS[index], now, ARGV[1])
  redis.call('EXPIRE', KEYS[index], tonumber(ARGV[5]) * 2)
end
return 1
"""
_REFRESH_CONNECTION = """
-- launchpad:comment-connection-refresh
for index = 1, 2 do
  if not redis.call('ZSCORE', KEYS[index], ARGV[1]) then return 0 end
end
for index = 1, 2 do
  redis.call('ZADD', KEYS[index], tonumber(ARGV[2]), ARGV[1])
  redis.call('EXPIRE', KEYS[index], tonumber(ARGV[3]) * 2)
end
return 1
"""
_RELEASE_CONNECTION = """
-- launchpad:comment-connection-release
for index = 1, 2 do
  redis.call('ZREM', KEYS[index], ARGV[1])
  if redis.call('ZCARD', KEYS[index]) == 0 then redis.call('DEL', KEYS[index]) end
end
return 1
"""


class InvalidCommentLiveTicket(ValueError):
    """Ticket material is malformed, expired, or scoped to another product."""


@dataclass(frozen=True, slots=True)
class CommentLiveTicket:
    token: str
    issued_at: datetime
    expires_at: datetime


class CommentLiveSessionFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]: ...


class CommentLivePubSub(Protocol):
    async def subscribe(self, *channels: str) -> object: ...

    async def unsubscribe(self, *channels: str) -> object: ...

    async def get_message(
        self, *, ignore_subscribe_messages: bool = False, timeout: float = 0.0
    ) -> Mapping[str, object] | None: ...

    async def aclose(self) -> None: ...


class CommentLiveRedis(Protocol):
    def pubsub(self) -> CommentLivePubSub: ...

    async def eval(self, script: str, numkeys: int, *values: object) -> object: ...


class CommentLiveTicketService:
    """Sign short-lived, identity-free tickets for exactly one public product."""

    def __init__(
        self,
        *,
        signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
        ttl_seconds: int = _TICKET_TTL_SECONDS,
    ) -> None:
        if len(signing_key) < 32 or not 1 <= ttl_seconds <= _TICKET_TTL_SECONDS:
            raise ValueError("invalid comment live ticket configuration")
        self.signing_key = signing_key
        self.clock = clock or (lambda: datetime.now(UTC))
        self.ttl_seconds = ttl_seconds

    def issue(self, product_id: UUID) -> CommentLiveTicket:
        issued_at = _utc(self.clock())
        expires_at = issued_at + timedelta(seconds=self.ttl_seconds)
        claims = {
            "exp": int(expires_at.timestamp()),
            "iat": int(issued_at.timestamp()),
            "nonce": secrets.token_urlsafe(12),
            "product_id": str(product_id),
            "version": 1,
        }
        payload = _b64encode(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
        signature = _b64encode(
            hmac.new(self.signing_key, payload.encode(), hashlib.sha256).digest()
        )
        return CommentLiveTicket(f"{payload}.{signature}", issued_at, expires_at)

    def verify(self, token: str, *, expected_product_id: UUID | None = None) -> UUID:
        try:
            payload, signature = token.split(".", maxsplit=1)
            supplied = _b64decode(signature)
            expected = hmac.new(self.signing_key, payload.encode(), hashlib.sha256).digest()
            if not hmac.compare_digest(supplied, expected):
                raise ValueError
            claims = json.loads(_b64decode(payload))
            if not isinstance(claims, dict) or claims.get("version") != 1:
                raise ValueError
            issued_at = int(claims["iat"])
            expires_at = int(claims["exp"])
            nonce = claims["nonce"]
            product_id = UUID(str(claims["product_id"]))
            now = int(_utc(self.clock()).timestamp())
            if (
                not isinstance(nonce, str)
                or not nonce
                or issued_at > now + 5
                or expires_at <= issued_at
                or expires_at - issued_at > self.ttl_seconds
                or expires_at <= now
                or (expected_product_id is not None and product_id != expected_product_id)
            ):
                raise ValueError
        except (AttributeError, KeyError, TypeError, ValueError, UnicodeDecodeError) as error:
            raise InvalidCommentLiveTicket("invalid or expired comment live ticket") from error
        return product_id


def ticket_service_for_settings(
    settings: Settings, *, clock: Callable[[], datetime] | None = None
) -> CommentLiveTicketService:
    """Derive a purpose-specific signing key from the encrypted-outbox key ring."""

    if settings.outbox_key is None:
        raise RuntimeError("Comment live ticket signing is unavailable")
    key_material = base64.b64decode(settings.outbox_key.get_secret_value(), validate=True)
    key = hmac.new(
        key_material, b"launchpad-comment-live-ticket-signing-v1", hashlib.sha256
    ).digest()
    return CommentLiveTicketService(signing_key=key, clock=clock)


def comment_product_channel(product_id: UUID) -> str:
    """Return the only Redis channel a product-scoped ticket may open."""

    return f"{_CHANNEL_PREFIX}{product_id.hex}"


def comment_created_message(*, product_id: UUID, comment_id: UUID, parent_id: UUID | None) -> str:
    """Encode the canonical invalidation payload without member content or identity."""

    return json.dumps(
        {
            "type": "comment.created",
            "product_id": str(product_id),
            "comment_id": str(comment_id),
            "parent_id": str(parent_id) if parent_id is not None else None,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def discussion_closed_message(*, product_id: UUID) -> str:
    """Encode a canonical product closure invalidation."""

    return json.dumps(
        {"type": "discussion.closed", "product_id": str(product_id)},
        separators=(",", ":"),
        sort_keys=True,
    )


def comment_live_router(
    *,
    settings: Settings,
    redis: CommentLiveRedis,
    tickets: CommentLiveTicketService,
    session_factory: CommentLiveSessionFactory,
    product_access: ProductDiscussionAccess,
    revalidate_seconds: float = _REVALIDATE_SECONDS,
    poll_seconds: float = _POLL_SECONDS,
    max_connections_per_product: int = _MAX_CONNECTIONS_PER_PRODUCT,
    max_connections_per_source: int = _MAX_CONNECTIONS_PER_SOURCE,
) -> APIRouter:
    """Open one bounded public socket only while its product remains public."""

    routes = APIRouter()

    @routes.websocket("/api/v1/comments/live")
    async def comments_live(websocket: WebSocket) -> None:
        try:
            validate_origin(websocket.headers.get("origin"), settings.trusted_web_origins)
            product_id = tickets.verify(websocket.query_params.get("ticket", ""))
        except (InvalidCommentLiveTicket, RequestSecurityError):
            await websocket.close(code=1008)
            return

        try:
            if not await _product_is_public(session_factory, product_access, product_id):
                await websocket.close(code=1008)
                return
        except Exception:
            await websocket.close(code=1013)
            return

        channel = comment_product_channel(product_id)
        product_key = f"{channel}:connections"
        source_key = f"{_CHANNEL_PREFIX}source:{_source_digest(websocket)}:connections"
        connection_id = uuid4().hex
        keys = (product_key, source_key)
        try:
            reserved = await _claim_connection(
                redis,
                keys=keys,
                connection_id=connection_id,
                product_limit=max_connections_per_product,
                source_limit=max_connections_per_source,
            )
        except Exception:
            await websocket.close(code=1013)
            return
        if not reserved:
            await websocket.close(code=1013)
            return

        pubsub: CommentLivePubSub | None = None
        try:
            pubsub = redis.pubsub()
            await pubsub.subscribe(channel)
            await websocket.accept()
            last_revalidated = time.monotonic()
            last_refreshed = last_revalidated
            while True:
                now = time.monotonic()
                if now - last_revalidated >= revalidate_seconds:
                    try:
                        visible = await _product_is_public(
                            session_factory, product_access, product_id
                        )
                    except Exception:
                        await websocket.close(code=1013)
                        return
                    if not visible:
                        try:
                            await _release_connection(redis, keys=keys, connection_id=connection_id)
                        except Exception:
                            # The bounded lease expires even if Redis disappears during closure.
                            pass
                        await websocket.send_json(
                            {"type": "discussion.closed", "product_id": str(product_id)}
                        )
                        await websocket.close(code=1000)
                        return
                    last_revalidated = now
                if now - last_refreshed >= _CONNECTION_REFRESH_SECONDS:
                    if not await _refresh_connection(redis, keys=keys, connection_id=connection_id):
                        await websocket.close(code=1013)
                        return
                    last_refreshed = now

                message_task = asyncio.create_task(
                    pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=max(0.01, min(poll_seconds, max(revalidate_seconds, 0.01))),
                    )
                )
                receive_task = asyncio.create_task(websocket.receive())
                tasks = (message_task, receive_task)
                try:
                    done, _pending = await asyncio.wait(
                        tasks,
                        timeout=max(0.01, min(poll_seconds, max(revalidate_seconds, 0.01))),
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)

                if receive_task in done:
                    incoming = receive_task.result()
                    if incoming.get("type") == "websocket.disconnect":
                        return
                if message_task not in done:
                    continue
                message = message_task.result()
                frame = _validated_frame(message, product_id=product_id)
                if frame is not None:
                    await websocket.send_json(frame)
        except WebSocketDisconnect:
            return
        except RedisError:
            await websocket.close(code=1013)
        except asyncio.CancelledError:
            raise
        except Exception:
            await websocket.close(code=1013)
        finally:
            cleanup = asyncio.create_task(
                _cleanup_connection(
                    redis,
                    pubsub=pubsub,
                    channel=channel,
                    keys=keys,
                    connection_id=connection_id,
                )
            )
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise

    return routes


async def _product_is_public(
    session_factory: CommentLiveSessionFactory,
    product_access: ProductDiscussionAccess,
    product_id: UUID,
) -> bool:
    async with session_factory() as session:
        return (
            await product_access.discussion_context(session, product_id=product_id, lock=False)
            is not None
        )


def _validated_frame(
    message: Mapping[str, object] | None, *, product_id: UUID
) -> dict[str, object] | None:
    if message is None or message.get("type") != "message":
        return None
    raw = message.get("data")
    try:
        if isinstance(raw, bytes):
            raw = raw.decode()
        if not isinstance(raw, str):
            return None
        payload = json.loads(raw)
        if not isinstance(payload, dict) or UUID(str(payload.get("product_id"))) != product_id:
            return None
        event_type = payload.get("type")
        if event_type == "comment.created":
            comment_id = UUID(str(payload.get("comment_id")))
            parent_raw = payload.get("parent_id")
            parent_id = None if parent_raw is None else UUID(str(parent_raw))
            return {
                "type": "comment.created",
                "product_id": str(product_id),
                "comment_id": str(comment_id),
                "parent_id": str(parent_id) if parent_id is not None else None,
            }
        if event_type == "discussion.closed":
            return {"type": "discussion.closed", "product_id": str(product_id)}
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return None


async def _claim_connection(
    redis: CommentLiveRedis,
    *,
    keys: tuple[str, str],
    connection_id: str,
    product_limit: int,
    source_limit: int,
) -> bool:
    result = await redis.eval(
        _CLAIM_CONNECTION,
        2,
        *keys,
        connection_id,
        int(time.time() * 1000),
        product_limit,
        source_limit,
        _CONNECTION_LEASE_SECONDS,
    )
    return result == 1 or result == b"1"


async def _refresh_connection(
    redis: CommentLiveRedis, *, keys: tuple[str, str], connection_id: str
) -> bool:
    result = await redis.eval(
        _REFRESH_CONNECTION,
        2,
        *keys,
        connection_id,
        int(time.time() * 1000),
        _CONNECTION_LEASE_SECONDS,
    )
    return result == 1 or result == b"1"


async def _release_connection(
    redis: CommentLiveRedis, *, keys: tuple[str, str], connection_id: str
) -> None:
    await redis.eval(_RELEASE_CONNECTION, 2, *keys, connection_id)


async def _cleanup_connection(
    redis: CommentLiveRedis,
    *,
    pubsub: CommentLivePubSub | None,
    channel: str,
    keys: tuple[str, str],
    connection_id: str,
) -> None:
    if pubsub is not None:
        try:
            await pubsub.unsubscribe(channel)
        except (Exception, asyncio.CancelledError):
            pass
        try:
            await pubsub.aclose()
        except (Exception, asyncio.CancelledError):
            pass
    try:
        await _release_connection(redis, keys=keys, connection_id=connection_id)
    except (Exception, asyncio.CancelledError):
        pass


def _source_digest(websocket: WebSocket) -> str:
    source = websocket.client.host if websocket.client is not None else "unknown"
    return hashlib.sha256(source.encode()).hexdigest()[:32]


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("ticket clock must be timezone-aware")
    return value.astimezone(UTC)
