"""Authenticated account-scoped WebSocket invalidation hints."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from typing import Protocol
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.sessions import MemberContext, UnauthenticatedError
from app.shared.config.settings import Settings
from app.shared.security.csrf import RequestSecurityError, validate_origin

_REVALIDATE_SECONDS = 30.0
_POLL_SECONDS = 1.0


class NotificationSessionFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]: ...


class NotificationSessionResolver(Protocol):
    async def resolve(self, session: AsyncSession, *, session_secret: str) -> MemberContext: ...


class NotificationPubSub(Protocol):
    async def subscribe(self, *channels: str) -> object: ...

    async def unsubscribe(self, *channels: str) -> object: ...

    async def get_message(
        self, *, ignore_subscribe_messages: bool = False, timeout: float = 0.0
    ) -> Mapping[str, object] | None: ...

    async def aclose(self) -> None: ...


class NotificationRedis(Protocol):
    def pubsub(self) -> NotificationPubSub: ...


def notification_channel(account_id: UUID) -> str:
    """Return the private channel shared with the outbox notification publisher."""

    return f"launchpad:notifications:account:{account_id.hex}"


def notification_live_router(
    *,
    settings: Settings,
    session_factory: NotificationSessionFactory,
    session_service: NotificationSessionResolver,
    redis: NotificationRedis,
    revalidate_seconds: float = _REVALIDATE_SECONDS,
    poll_seconds: float = _POLL_SECONDS,
) -> APIRouter:
    """Reject unsafe handshakes, then bind each socket to its live account session."""

    routes = APIRouter()

    @routes.websocket("/me/notifications/live")
    async def notifications_live(websocket: WebSocket) -> None:
        try:
            validate_origin(websocket.headers.get("origin"), settings.trusted_web_origins)
        except RequestSecurityError:
            await websocket.close(code=1008)
            return

        secret = websocket.cookies.get(settings.session_cookie_name)
        if not secret:
            await websocket.close(code=1008)
            return

        try:
            member = await _resolve_member(session_factory, session_service, secret)
        except Exception:
            await websocket.close(code=1013)
            return
        if member is None or member.suspended_at is not None:
            await websocket.close(code=1008)
            return

        channel = notification_channel(member.account_id)
        pubsub = redis.pubsub()
        try:
            # Origin, cookie, and live session were checked before opening a Redis subscription.
            await pubsub.subscribe(channel)
            await websocket.accept()
            last_revalidated = time.monotonic()
            while True:
                now = time.monotonic()
                if now - last_revalidated >= revalidate_seconds:
                    try:
                        current = await _resolve_member(session_factory, session_service, secret)
                    except Exception:
                        await websocket.close(code=1013)
                        return
                    if current is None or current.suspended_at is not None:
                        await websocket.close(code=1008)
                        return
                    last_revalidated = now
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=max(0.01, min(poll_seconds, revalidate_seconds)),
                )
                if message is not None and message.get("type") == "message":
                    await websocket.send_json({"type": "notifications_changed"})
        except WebSocketDisconnect:
            return
        except RedisError:
            await websocket.close(code=1013)
        except asyncio.CancelledError:
            raise
        except Exception:
            await websocket.close(code=1013)
        finally:
            try:
                await pubsub.unsubscribe(channel)
            except Exception:
                pass
            try:
                await pubsub.aclose()
            except Exception:
                pass

    return routes


async def _resolve_member(
    session_factory: NotificationSessionFactory,
    session_service: NotificationSessionResolver,
    secret: str,
) -> MemberContext | None:
    try:
        async with session_factory() as session:
            async with session.begin():
                return await session_service.resolve(session, session_secret=secret)
    except UnauthenticatedError:
        return None
