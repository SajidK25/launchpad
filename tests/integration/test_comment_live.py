"""Redis-backed discussion socket lifecycle and outage isolation."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from app.modules.comments.live import (
    CommentLiveTicketService,
    comment_created_message,
    comment_live_router,
    comment_product_channel,
)
from app.modules.comments.service import ProductDiscussionContext
from app.shared.config.settings import Settings
from conftest import IntegrationSettings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketDisconnect

ORIGIN = "https://launchpad.example"


class _Products:
    def __init__(self, product_id: UUID) -> None:
        self.product_id = product_id
        self.visible = True

    async def discussion_context(
        self, _session: AsyncSession, *, product_id: UUID, lock: bool = False
    ) -> ProductDiscussionContext | None:
        if self.visible and product_id == self.product_id:
            return cast(ProductDiscussionContext, SimpleNamespace(product_id=product_id))
        return None


@asynccontextmanager
async def _sessions() -> AsyncIterator[AsyncSession]:
    yield cast(AsyncSession, object())


def _tickets() -> CommentLiveTicketService:
    return CommentLiveTicketService(signing_key=b"integration-comment-live-key" * 2)


def test_real_redis_socket_forwards_one_product_and_releases_bounded_leases(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    product_id, comment_id = uuid4(), uuid4()
    sync_redis = Redis.from_url(integration_settings_fixture.redis_url)
    async_redis = AsyncRedis.from_url(integration_settings_fixture.redis_url)
    sync_redis.flushdb()
    products = _Products(product_id)
    tickets = _tickets()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await async_redis.aclose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(
        comment_live_router(
            settings=Settings(trusted_web_origins=(ORIGIN,)),
            redis=async_redis,
            tickets=tickets,
            session_factory=_sessions,
            product_access=products,
            poll_seconds=0.05,
            revalidate_seconds=0.05,
        )
    )
    try:
        with TestClient(app) as client:
            with client.websocket_connect(
                f"/api/v1/comments/live?ticket={tickets.issue(product_id).token}",
                headers={"origin": ORIGIN},
            ) as websocket:
                assert (
                    sync_redis.publish(
                        comment_product_channel(product_id),
                        comment_created_message(
                            product_id=product_id, comment_id=comment_id, parent_id=None
                        ),
                    )
                    == 1
                )
                assert websocket.receive_json() == {
                    "type": "comment.created",
                    "product_id": str(product_id),
                    "comment_id": str(comment_id),
                    "parent_id": None,
                }
                products.visible = False
                assert websocket.receive_json() == {
                    "type": "discussion.closed",
                    "product_id": str(product_id),
                }
                with pytest.raises(WebSocketDisconnect):
                    websocket.receive_json()

        deadline = time.monotonic() + 1
        while sync_redis.keys("launchpad:comments:*:connections") and time.monotonic() < deadline:
            time.sleep(0.01)
        assert sync_redis.keys("launchpad:comments:*:connections") == []
    finally:
        sync_redis.flushdb()
        sync_redis.close()


def test_redis_subscribe_outage_closes_retryably_without_changing_visibility() -> None:
    product_id = uuid4()
    products = _Products(product_id)
    tickets = _tickets()

    class _OutageRedis:
        async def eval(self, _script: str, _numkeys: int, *_values: object) -> int:
            return 1

        def pubsub(self) -> object:
            raise RedisError("redis unavailable")

    app = FastAPI()
    app.include_router(
        comment_live_router(
            settings=Settings(trusted_web_origins=(ORIGIN,)),
            redis=cast(object, _OutageRedis()),  # type: ignore[arg-type]
            tickets=tickets,
            session_factory=_sessions,
            product_access=products,
        )
    )
    with TestClient(app) as client, pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(
            f"/api/v1/comments/live?ticket={tickets.issue(product_id).token}",
            headers={"origin": ORIGIN},
        ):
            pytest.fail("Redis outage accepted a discussion socket")
    assert closed.value.code == 1013
    assert products.visible
