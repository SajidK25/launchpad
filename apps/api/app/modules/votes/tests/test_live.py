"""Public vote live ticket and WebSocket security contracts."""

from __future__ import annotations

import asyncio
import threading
import time
from base64 import b64encode
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

from app.modules.votes.live import (
    InvalidVoteLiveTicket,
    VoteLiveTicketService,
    ticket_service_for_settings,
    vote_live_router,
    vote_ranking_channel,
)
from app.modules.votes.routes import router as vote_commands_router
from app.shared.config.settings import Settings
from app.shared.db.database import Database

_ORIGIN = "https://launchpad.example"


class _PubSub:
    def __init__(self, channels: list[str]) -> None:
        self.channels = channels

    async def subscribe(self, *_channels: str) -> None:
        self.channels.extend(_channels)
        return None

    async def unsubscribe(self, *_channels: str) -> None:
        return None

    async def get_message(
        self, *, ignore_subscribe_messages: bool = False, timeout: float = 0.0
    ) -> dict[str, object] | None:
        await asyncio.sleep(0)
        return {"type": "message", "data": b'{"voter":"private","ip":"private"}'}

    async def aclose(self) -> None:
        return None


class _Redis:
    def __init__(self) -> None:
        self.channels: list[str] = []

    def pubsub(self) -> _PubSub:
        return _PubSub(self.channels)

    def eval(self, _script: str, _numkeys: int, _key: str, _seconds: int) -> int:
        return 1


def _service(now: datetime | None = None) -> VoteLiveTicketService:
    current = now or datetime(2026, 10, 25, 12, tzinfo=UTC)
    return VoteLiveTicketService(signing_key=b"vote-live-test-key" * 2, clock=lambda: current)


def _settings() -> Settings:
    return Settings(trusted_web_origins=(_ORIGIN,))


def test_ticket_is_short_lived_and_scoped_to_current_utc_date() -> None:
    service = _service()
    ticket = service.issue()

    assert ticket.expires_at - ticket.issued_at == timedelta(seconds=120)
    assert service.verify(ticket.token) == date(2026, 10, 25)

    next_day = _service(datetime(2026, 10, 26, 0, tzinfo=UTC))
    with pytest.raises(InvalidVoteLiveTicket):
        next_day.verify(ticket.token)


def test_ticket_rejects_tampering_expiry_and_malformed_tokens() -> None:
    service = _service()
    token = service.issue().token
    with pytest.raises(InvalidVoteLiveTicket):
        service.verify(token + "x")
    expired = _service(datetime(2026, 10, 25, 12, 2, tzinfo=UTC))
    with pytest.raises(InvalidVoteLiveTicket):
        expired.verify(token)
    with pytest.raises(InvalidVoteLiveTicket):
        service.verify("not-a-ticket")


def test_websocket_subscribes_to_date_channel_and_sends_only_invalidation() -> None:
    redis = _Redis()
    app = FastAPI()
    app.include_router(vote_live_router(settings=_settings(), redis=redis, tickets=_service()))
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/votes/live?ticket={_service().issue().token}",
            headers={"origin": _ORIGIN},
        ) as websocket:
            assert websocket.receive_json() == {
                "type": "ranking.invalidated",
                "date": "2026-10-25",
            }

    assert redis.channels == [vote_ranking_channel(date(2026, 10, 25))]


def test_idle_websocket_disconnect_closes_redis_pubsub() -> None:
    closed = threading.Event()

    class IdlePubSub(_PubSub):
        async def get_message(
            self, *, ignore_subscribe_messages: bool = False, timeout: float = 0.0
        ) -> dict[str, object] | None:
            await asyncio.sleep(30)
            return None

        async def aclose(self) -> None:
            closed.set()

    class IdleRedis(_Redis):
        def pubsub(self) -> IdlePubSub:
            return IdlePubSub(self.channels)

    service = _service()
    app = FastAPI()
    app.include_router(vote_live_router(settings=_settings(), redis=IdleRedis(), tickets=service))
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/votes/live?ticket={service.issue().token}",
            headers={"origin": _ORIGIN},
        ):
            pass

    deadline = time.monotonic() + 1
    while not closed.is_set() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert closed.is_set(), "idle WebSocket disconnect left its Redis pub/sub open"


@pytest.mark.parametrize("origin", ["https://evil.example", None])
def test_websocket_rejects_wrong_or_missing_origin(origin: str | None) -> None:
    app = FastAPI()
    app.include_router(vote_live_router(settings=_settings(), redis=_Redis(), tickets=_service()))
    headers = {} if origin is None else {"origin": origin}
    with TestClient(app) as client, pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/api/v1/votes/live?ticket={_service().issue().token}", headers=headers
        ):
            pytest.fail("disallowed origin opened a vote ranking socket")


def test_websocket_rejects_invalid_ticket_without_opening() -> None:
    app = FastAPI()
    app.include_router(vote_live_router(settings=_settings(), redis=_Redis(), tickets=_service()))
    with TestClient(app) as client, pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/api/v1/votes/live?ticket=invalid", headers={"origin": _ORIGIN}
        ):
            pytest.fail("invalid ticket opened a vote ranking socket")


def test_ticket_endpoint_requires_origin_and_returns_no_identity() -> None:
    settings = Settings(
        trusted_web_origins=(_ORIGIN,),
        outbox_key_id="test",
        outbox_key=SecretStr(b64encode(b"test-outbox-key-material-32bytes").decode()),
    )
    app = FastAPI()
    app.include_router(
        vote_commands_router(
            settings=settings,
            database=Database.connect(str(settings.database_url)),
            redis=cast(Any, _Redis()),
        )
    )
    client = TestClient(app)
    denied = client.post("/api/v1/votes/live-ticket")
    issued = client.post("/api/v1/votes/live-ticket", headers={"Origin": _ORIGIN})

    assert denied.status_code == 403
    assert issued.status_code == 200
    response = issued.json()
    assert set(response) == {"ticket", "expires_at"}
    assert (
        ticket_service_for_settings(settings).verify(response["ticket"]) == datetime.now(UTC).date()
    )
