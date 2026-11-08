"""Product-scoped discussion ticket and WebSocket security contracts."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketDisconnect

from app.modules.comments.live import (
    CommentLiveTicketService,
    InvalidCommentLiveTicket,
    comment_live_router,
    comment_product_channel,
)
from app.modules.comments.service import ProductDiscussionContext
from app.shared.config.settings import Settings

ORIGIN = "https://launchpad.example"
NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)


class _Products:
    def __init__(self, product_id: UUID) -> None:
        self.product_id = product_id
        self.visible = True
        self.calls = 0

    async def discussion_context(
        self, _session: AsyncSession, *, product_id: UUID, lock: bool = False
    ) -> ProductDiscussionContext | None:
        self.calls += 1
        if product_id != self.product_id or not self.visible:
            return None
        return cast(ProductDiscussionContext, SimpleNamespace(product_id=product_id))


class _PubSub:
    def __init__(self) -> None:
        self.channels: list[str] = []
        self.messages: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self.closed = False

    async def subscribe(self, *channels: str) -> None:
        self.channels.extend(channels)

    async def unsubscribe(self, *channels: str) -> None:
        for channel in channels:
            if channel in self.channels:
                self.channels.remove(channel)

    async def get_message(
        self, *, ignore_subscribe_messages: bool = False, timeout: float = 0.0
    ) -> dict[str, object] | None:
        try:
            return await asyncio.wait_for(self.messages.get(), timeout=timeout)
        except TimeoutError:
            return None

    async def aclose(self) -> None:
        self.closed = True


class _Redis:
    def __init__(self, *, admit: bool = True, fail_subscribe: bool = False) -> None:
        self.admit = admit
        self.fail_subscribe = fail_subscribe
        self.pubsubs: list[_PubSub] = []
        self.eval_calls: list[tuple[str, int, tuple[object, ...]]] = []

    def pubsub(self) -> _PubSub:
        pubsub = _PubSub()
        if self.fail_subscribe:

            async def fail(*_channels: str) -> None:
                raise RedisError("unavailable")

            pubsub.subscribe = fail  # type: ignore[method-assign]
        self.pubsubs.append(pubsub)
        return pubsub

    async def eval(self, script: str, numkeys: int, *values: object) -> int:
        self.eval_calls.append((script, numkeys, values))
        if "connection-claim" in script:
            return 1 if self.admit else 0
        return 1


def _service(product_id: UUID, now: datetime = NOW) -> CommentLiveTicketService:
    return CommentLiveTicketService(
        signing_key=b"comment-live-test-key-material" * 2,
        clock=lambda: now,
    )


def _app(
    product_id: UUID,
    *,
    redis: _Redis | None = None,
    products: _Products | None = None,
    revalidate_seconds: float = 30.0,
) -> tuple[FastAPI, _Redis, _Products, CommentLiveTicketService]:
    live_redis = redis or _Redis()
    product_access = products or _Products(product_id)
    tickets = _service(product_id)

    @asynccontextmanager
    async def sessions() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, object())

    app = FastAPI()
    app.include_router(
        comment_live_router(
            settings=Settings(trusted_web_origins=(ORIGIN,)),
            redis=live_redis,
            tickets=tickets,
            session_factory=sessions,
            product_access=product_access,
            revalidate_seconds=revalidate_seconds,
            poll_seconds=0.01,
        )
    )
    return app, live_redis, product_access, tickets


def test_ticket_is_short_lived_versioned_and_product_scoped() -> None:
    product_id, other_id = uuid4(), uuid4()
    service = _service(product_id)
    ticket = service.issue(product_id)

    assert ticket.expires_at - ticket.issued_at == timedelta(seconds=120)
    assert service.verify(ticket.token) == product_id
    assert service.verify(ticket.token, expected_product_id=product_id) == product_id
    with pytest.raises(InvalidCommentLiveTicket):
        service.verify(ticket.token, expected_product_id=other_id)


def test_ticket_rejects_tampering_expiry_and_malformed_material() -> None:
    product_id = uuid4()
    token = _service(product_id).issue(product_id).token

    for service, candidate in (
        (_service(product_id), token + "x"),
        (_service(product_id, NOW + timedelta(minutes=3)), token),
        (_service(product_id), "not-a-ticket"),
    ):
        with pytest.raises(InvalidCommentLiveTicket):
            service.verify(candidate)


def test_socket_subscribes_to_one_product_and_forwards_identifier_only_frames() -> None:
    product_id, comment_id, parent_id = uuid4(), uuid4(), uuid4()
    app, redis, _products, tickets = _app(product_id)
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/comments/live?ticket={tickets.issue(product_id).token}",
            headers={"origin": ORIGIN},
        ) as websocket:
            pubsub = redis.pubsubs[0]
            pubsub.messages.put_nowait(
                {
                    "type": "message",
                    "data": json.dumps(
                        {
                            "type": "comment.created",
                            "product_id": str(product_id),
                            "comment_id": str(comment_id),
                            "parent_id": str(parent_id),
                            "body": "must not escape",
                            "author": "must not escape",
                        }
                    ).encode(),
                }
            )
            assert websocket.receive_json() == {
                "type": "comment.created",
                "product_id": str(product_id),
                "comment_id": str(comment_id),
                "parent_id": str(parent_id),
            }

    assert redis.pubsubs[0].channels == []
    assert redis.pubsubs[0].closed
    claim = redis.eval_calls[0]
    assert claim[1] == 2
    assert f"{comment_product_channel(product_id)}:connections" in claim[2]


def test_socket_closes_after_periodic_visibility_recheck() -> None:
    product_id = uuid4()
    products = _Products(product_id)
    app, _redis, _products, tickets = _app(product_id, products=products, revalidate_seconds=0.0)
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/comments/live?ticket={tickets.issue(product_id).token}",
            headers={"origin": ORIGIN},
        ) as websocket:
            products.visible = False
            assert websocket.receive_json() == {
                "type": "discussion.closed",
                "product_id": str(product_id),
            }
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()


@pytest.mark.parametrize("origin", [None, "https://evil.example"])
def test_socket_rejects_untrusted_origin_without_subscribing(origin: str | None) -> None:
    product_id = uuid4()
    app, redis, _products, tickets = _app(product_id)
    headers = {} if origin is None else {"origin": origin}
    with TestClient(app) as client, pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/api/v1/comments/live?ticket={tickets.issue(product_id).token}", headers=headers
        ):
            pytest.fail("untrusted origin opened a discussion socket")
    assert redis.pubsubs == []


def test_socket_rejects_connection_flood_and_redis_failure_safely() -> None:
    product_id = uuid4()
    for redis in (_Redis(admit=False), _Redis(fail_subscribe=True)):
        app, live_redis, _products, tickets = _app(product_id, redis=redis)
        with TestClient(app) as client, pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect(
                f"/api/v1/comments/live?ticket={tickets.issue(product_id).token}",
                headers={"origin": ORIGIN},
            ):
                pytest.fail("unsafe discussion socket was accepted")
        assert closed.value.code == 1013
        if live_redis.pubsubs:
            assert live_redis.pubsubs[0].closed
