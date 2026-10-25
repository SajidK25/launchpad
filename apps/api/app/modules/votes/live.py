"""Short-lived tickets and anonymous-safe invalidations for daily rankings."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.exceptions import RedisError

from app.shared.config.settings import Settings
from app.shared.security.csrf import RequestSecurityError, validate_origin

_TICKET_TTL_SECONDS = 120
_CHANNEL_PREFIX = "launchpad:votes:ranking:"


class InvalidVoteLiveTicket(ValueError):
    """Ticket is malformed, expired, or scoped to another UTC day."""


@dataclass(frozen=True, slots=True)
class VoteLiveTicket:
    token: str
    issued_at: datetime
    expires_at: datetime


class VoteLivePubSub(Protocol):
    async def subscribe(self, *channels: str) -> object: ...

    async def unsubscribe(self, *channels: str) -> object: ...

    async def get_message(
        self, *, ignore_subscribe_messages: bool = False, timeout: float = 0.0
    ) -> Mapping[str, object] | None: ...

    async def aclose(self) -> None: ...


class VoteLiveRedis(Protocol):
    def pubsub(self) -> VoteLivePubSub: ...


class VoteLiveTicketService:
    """Sign identity-free, current-UTC-day tickets with a purpose-specific key."""

    def __init__(
        self,
        *,
        signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
        ttl_seconds: int = _TICKET_TTL_SECONDS,
    ) -> None:
        if len(signing_key) < 32 or not 1 <= ttl_seconds <= _TICKET_TTL_SECONDS:
            raise ValueError("invalid vote live ticket configuration")
        self.signing_key = signing_key
        self.clock = clock or (lambda: datetime.now(UTC))
        self.ttl_seconds = ttl_seconds

    def issue(self) -> VoteLiveTicket:
        issued_at = _utc(self.clock())
        expires_at = issued_at + timedelta(seconds=self.ttl_seconds)
        claims = {
            "date": issued_at.date().isoformat(),
            "exp": int(expires_at.timestamp()),
            "iat": int(issued_at.timestamp()),
            "nonce": secrets.token_urlsafe(12),
            "version": 1,
        }
        payload = _b64encode(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
        signature = _b64encode(
            hmac.new(self.signing_key, payload.encode(), hashlib.sha256).digest()
        )
        return VoteLiveTicket(f"{payload}.{signature}", issued_at, expires_at)

    def verify(self, token: str) -> date:
        try:
            payload, signature = token.split(".", maxsplit=1)
            supplied_signature = _b64decode(signature)
            expected_signature = hmac.new(
                self.signing_key, payload.encode(), hashlib.sha256
            ).digest()
            if not hmac.compare_digest(supplied_signature, expected_signature):
                raise ValueError
            claims = json.loads(_b64decode(payload))
            if not isinstance(claims, dict) or claims.get("version") != 1:
                raise ValueError
            issued_at = int(claims["iat"])
            expires_at = int(claims["exp"])
            ticket_date = date.fromisoformat(str(claims["date"]))
            nonce = claims["nonce"]
            if (
                not isinstance(nonce, str)
                or not nonce
                or expires_at <= issued_at
                or expires_at - issued_at > self.ttl_seconds
                or expires_at <= int(_utc(self.clock()).timestamp())
                or ticket_date != _utc(self.clock()).date()
            ):
                raise ValueError
        except (AttributeError, KeyError, TypeError, ValueError, UnicodeDecodeError) as error:
            raise InvalidVoteLiveTicket("invalid or expired vote live ticket") from error
        return ticket_date


def ticket_service_for_settings(
    settings: Settings, *, clock: Callable[[], datetime] | None = None
) -> VoteLiveTicketService:
    """Derive a vote-live signing key with domain separation from the key ring."""

    if settings.outbox_key is None:
        raise RuntimeError("Vote live ticket signing is unavailable")
    key_material = base64.b64decode(settings.outbox_key.get_secret_value(), validate=True)
    key = hmac.new(key_material, b"launchpad-vote-live-ticket-signing-v1", hashlib.sha256).digest()
    return VoteLiveTicketService(signing_key=key, clock=clock)


def vote_ranking_channel(launch_date: date) -> str:
    return f"{_CHANNEL_PREFIX}{launch_date.isoformat()}"


def vote_live_router(
    *, settings: Settings, redis: VoteLiveRedis, tickets: VoteLiveTicketService
) -> APIRouter:
    """Expose an origin-checked public stream containing invalidation hints only."""

    routes = APIRouter()

    @routes.websocket("/api/v1/votes/live")
    async def ranking_live(websocket: WebSocket) -> None:
        try:
            validate_origin(websocket.headers.get("origin"), settings.trusted_web_origins)
            launch_date = tickets.verify(websocket.query_params.get("ticket", ""))
        except (InvalidVoteLiveTicket, RequestSecurityError):
            await websocket.close(code=1008)
            return

        channel = vote_ranking_channel(launch_date)
        pubsub: VoteLivePubSub | None = None
        try:
            pubsub = redis.pubsub()
            await pubsub.subscribe(channel)
            await websocket.accept()
            while True:
                message_task = asyncio.create_task(
                    pubsub.get_message(ignore_subscribe_messages=True, timeout=30.0)
                )
                receive_task = asyncio.create_task(websocket.receive())
                tasks = (message_task, receive_task)
                try:
                    done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)

                if receive_task in done:
                    incoming = receive_task.result()
                    if incoming.get("type") == "websocket.disconnect":
                        return
                if message_task in done:
                    message = message_task.result()
                else:
                    continue
                if message is not None and message.get("type") == "message":
                    await websocket.send_json(
                        {"type": "ranking.invalidated", "date": launch_date.isoformat()}
                    )
        except WebSocketDisconnect:
            return
        except RedisError:
            await websocket.close(code=1013)
        except asyncio.CancelledError:
            raise
        except Exception:
            await websocket.close(code=1013)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(channel)
                except Exception:
                    pass
                try:
                    await pubsub.aclose()
                except Exception:
                    pass

    return routes


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("ticket clock must be timezone-aware")
    return value.astimezone(UTC)
