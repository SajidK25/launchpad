"""WebSocket handshake, account binding, and session revalidation contracts."""

from __future__ import annotations

import asyncio
import queue
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketDisconnect

from app.modules.auth.sessions import MemberContext, UnauthenticatedError
from app.modules.notifications.live import (
    NotificationPubSub,
    notification_channel,
    notification_live_router,
)
from app.shared.config.settings import Settings

_ORIGIN = "https://launchpad.example"
_PATH = "/me/notifications/live"


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_: object) -> None:
        return None


class _Session:
    def begin(self) -> _Transaction:
        return _Transaction()


class _SessionContext:
    async def __aenter__(self) -> AsyncSession:
        return cast(AsyncSession, _Session())

    async def __aexit__(self, *_: object) -> None:
        return None


class _SessionFactory:
    def __call__(self) -> _SessionContext:
        return _SessionContext()


class _Resolver:
    def __init__(self, members: dict[str, MemberContext | None]) -> None:
        self.members = members
        self.calls: dict[str, int] = {}

    async def resolve(self, session: AsyncSession, *, session_secret: str) -> MemberContext:
        self.calls[session_secret] = self.calls.get(session_secret, 0) + 1
        member = self.members.get(session_secret)
        if member is None:
            raise UnauthenticatedError("authentication required")
        return member


class _PubSub:
    def __init__(self) -> None:
        self.channels: list[str] = []
        self.messages: queue.Queue[Mapping[str, object]] = queue.Queue()
        self.closed = False

    async def subscribe(self, *channels: str) -> None:
        self.channels.extend(channels)

    async def unsubscribe(self, *channels: str) -> None:
        self.channels = [channel for channel in self.channels if channel not in channels]

    async def get_message(
        self, *, ignore_subscribe_messages: bool = False, timeout: float = 0.0
    ) -> Mapping[str, object] | None:
        await asyncio.sleep(min(timeout, 0.01))
        try:
            return self.messages.get_nowait()
        except queue.Empty:
            return None

    async def aclose(self) -> None:
        self.closed = True


class _Redis:
    def __init__(self) -> None:
        self.pubsubs: list[_PubSub] = []
        self.connections: dict[str, dict[str, int]] = {}

    def pubsub(self) -> NotificationPubSub:
        pubsub = _PubSub()
        self.pubsubs.append(pubsub)
        return pubsub

    def publish(self, channel: str, message: bytes = b"internal payload") -> int:
        subscribers = 0
        for pubsub in self.pubsubs:
            if channel in pubsub.channels:
                pubsub.messages.put({"type": "message", "data": message})
                subscribers += 1
        return subscribers

    async def eval(self, script: str, numkeys: int, *values: object) -> int:
        assert numkeys == 1
        key, token = str(values[0]), str(values[1])
        now = int(values[2]) if len(values) > 2 else 0
        members = self.connections.setdefault(key, {})
        if "connection-claim" in script:
            limit = int(values[3])
            lease_ms = int(values[4]) * 1000
            for expired in [
                item for item, updated in members.items() if updated <= now - lease_ms
            ]:
                del members[expired]
            if len(members) >= limit:
                return 0
            members[token] = now
            return 1
        if "connection-refresh" in script:
            if token not in members:
                return 0
            members[token] = now
            return 1
        if "connection-release" in script:
            members.pop(token, None)
            if not members:
                self.connections.pop(key, None)
            return 1
        raise AssertionError("unknown connection lease script")


def _member(account_id: UUID, *, suspended: bool = False) -> MemberContext:
    return MemberContext(
        account_id=account_id,
        verified=True,
        session_id=uuid4(),
        suspended_at=datetime.now(UTC) if suspended else None,
    )


def _app(
    resolver: _Resolver,
    redis: _Redis,
    *,
    revalidate_seconds: float = 30.0,
    poll_seconds: float = 0.01,
    max_connections_per_account: int = 5,
) -> FastAPI:
    settings = Settings(trusted_web_origins=(_ORIGIN,))
    app = FastAPI()
    app.include_router(
        notification_live_router(
            settings=settings,
            session_factory=_SessionFactory(),
            session_service=resolver,
            redis=redis,
            revalidate_seconds=revalidate_seconds,
            poll_seconds=poll_seconds,
            max_connections_per_account=max_connections_per_account,
        )
    )
    return app


def _headers(secret: str = "founder-session", origin: str = _ORIGIN) -> dict[str, str]:
    return {
        "Origin": origin,
        "Cookie": f"__Host-launchpad_session={secret}",
    }


def test_websocket_subscribes_to_only_the_cookie_account_and_sends_a_generic_hint() -> None:
    first_id, second_id = uuid4(), uuid4()
    redis = _Redis()
    resolver = _Resolver({"first-session": _member(first_id), "second-session": _member(second_id)})
    app = _app(resolver, redis)

    with TestClient(app) as client:
        with client.websocket_connect(_PATH, headers=_headers("first-session")) as first_socket:
            with client.websocket_connect(_PATH, headers=_headers("second-session")):
                assert [item.channels for item in redis.pubsubs] == [
                    [notification_channel(first_id)],
                    [notification_channel(second_id)],
                ]
                assert redis.publish(notification_channel(first_id), b"secret feedback") == 1
                assert first_socket.receive_json() == {"type": "notifications_changed"}
                assert redis.pubsubs[1].messages.empty()


def test_websocket_enforces_account_connection_limit_and_releases_lease() -> None:
    account_id = uuid4()
    redis = _Redis()
    resolver = _Resolver({"founder-session": _member(account_id)})
    app = _app(resolver, redis, max_connections_per_account=1)

    with TestClient(app) as client:
        with client.websocket_connect(_PATH, headers=_headers("founder-session")):
            assert len(redis.pubsubs) == 1
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(_PATH, headers=_headers("founder-session")):
                    raise AssertionError("the account limit should reject a second socket")
            assert len(redis.pubsubs) == 1

        assert redis.connections == {}
        with client.websocket_connect(_PATH, headers=_headers("founder-session")):
            assert len(redis.pubsubs) == 2


@pytest.mark.parametrize(
    ("cookie", "origin", "expected_resolves"),
    [
        (None, _ORIGIN, 0),
        ("invalid-session", _ORIGIN, 1),
        ("founder-session", "https://attacker.example", 0),
    ],
)
def test_websocket_rejects_bad_handshakes_before_subscribing(
    cookie: str | None,
    origin: str,
    expected_resolves: int,
) -> None:
    account_id = uuid4()
    redis = _Redis()
    resolver = _Resolver({"founder-session": _member(account_id)})
    app = _app(resolver, redis)
    headers = {"Origin": origin}
    if cookie is not None:
        headers["Cookie"] = f"__Host-launchpad_session={cookie}"

    with TestClient(app) as client, pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(_PATH, headers=headers):
            pytest.fail("invalid handshake unexpectedly connected")

    assert resolver.calls.get("invalid-session", 0) == expected_resolves
    assert redis.pubsubs == []


def test_websocket_closes_when_session_is_revoked_during_revalidation() -> None:
    account_id = uuid4()
    redis = _Redis()

    class RevokingResolver(_Resolver):
        async def resolve(self, session: AsyncSession, *, session_secret: str) -> MemberContext:
            self.calls[session_secret] = self.calls.get(session_secret, 0) + 1
            if self.calls[session_secret] == 1:
                return _member(account_id)
            raise UnauthenticatedError("authentication required")

    revoking = RevokingResolver({})
    app = _app(revoking, redis, revalidate_seconds=0.03)

    with TestClient(app) as client:
        with client.websocket_connect(_PATH, headers=_headers()) as socket:
            with pytest.raises(WebSocketDisconnect) as closed:
                socket.receive_json()

    assert closed.value.code == 1008
    assert revoking.calls["founder-session"] >= 2
    assert redis.pubsubs[0].closed
