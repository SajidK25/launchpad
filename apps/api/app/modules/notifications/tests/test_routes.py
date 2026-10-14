"""HTTP transport coverage for the private one-item notification read command."""

from __future__ import annotations

import base64
import threading
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.modules.auth.sessions import MemberContext, SessionService
from app.modules.notifications.live import NotificationPubSub
from app.modules.notifications.routes import router
from app.modules.notifications.schemas import NotificationItem
from app.modules.notifications.service import NotificationNotFoundError, NotificationService
from app.shared.config.settings import Settings
from app.shared.db.database import Database
from app.shared.security.csrf import derive_csrf_token
from app.shared.security.tokens import digest_token

_SECRET = "read-route-session-secret"
_ORIGIN = "http://localhost:8080"


class _RedisCounter:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.lock = threading.Lock()

    def incr(self, key: str) -> int:
        with self.lock:
            self.values[key] = self.values.get(key, 0) + 1
            return self.values[key]

    def expire(self, key: str, seconds: int) -> bool:
        return key in self.values and seconds > 0


class _PubSubClient:
    def pubsub(self) -> NotificationPubSub:
        return cast(NotificationPubSub, SimpleNamespace())

    async def eval(self, script: str, numkeys: int, *values: object) -> object:
        raise AssertionError("notification websocket is not used in this HTTP test")


def _client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, UUID, UUID]:
    owner_id = uuid4()
    owned_id, foreign_id = uuid4(), uuid4()
    now = datetime(2026, 10, 5, tzinfo=UTC)
    read_states: dict[UUID, datetime | None] = {owned_id: None}
    settings = Settings(
        trusted_web_origins=(_ORIGIN,),
        outbox_key_id="read-route-test",
        outbox_key=SecretStr(base64.b64encode(b"r" * 32).decode("ascii")),
        review_writes_enabled=False,
    )
    member = MemberContext(
        account_id=owner_id,
        verified=True,
        session_id=uuid4(),
        csrf_digest=digest_token(derive_csrf_token(_SECRET)),
    )

    async def resolve(
        self: SessionService, session: object, *, session_secret: str
    ) -> MemberContext:
        if session_secret != _SECRET:
            from app.modules.auth.sessions import UnauthenticatedError

            raise UnauthenticatedError("authentication required")
        return member

    async def mark_read(
        self: NotificationService,
        session: object,
        *,
        actor_id: UUID,
        notification_id: UUID,
    ) -> NotificationItem:
        if actor_id != owner_id or notification_id not in read_states:
            raise NotificationNotFoundError("notification unavailable")
        if read_states[notification_id] is None:
            read_states[notification_id] = now
        return NotificationItem(
            id=notification_id,
            product_id=uuid4(),
            kind="review_approved",
            created_at=now,
            read_at=read_states[notification_id],
        )

    monkeypatch.setattr(SessionService, "resolve", resolve)
    monkeypatch.setattr(NotificationService, "mark_read", mark_read)
    database = Database.connect(str(settings.database_url))
    routes = router(
        settings=settings,
        database=database,
        redis=_RedisCounter(),
        live_redis=_PubSubClient(),
    )
    app = FastAPI()
    app.include_router(routes)
    client = TestClient(app)
    return client, owned_id, foreign_id


def _headers(*, authenticated: bool = True, csrf: str | None = None) -> dict[str, str]:
    headers = {"Origin": _ORIGIN}
    if authenticated:
        headers["Cookie"] = f"__Host-launchpad_session={_SECRET}"
    if csrf is not None:
        headers["X-CSRF-Token"] = csrf
    return headers


def test_read_route_is_mounted_even_when_review_writes_are_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, owned_id, _ = _client(monkeypatch)
    response = client.put(
        f"/api/v1/me/notifications/{owned_id}/read",
        headers=_headers(csrf=derive_csrf_token(_SECRET)),
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(owned_id)
    assert response.json()["read_at"] == "2026-10-05T00:00:00Z"


def test_read_route_enforces_origin_cookie_csrf_and_hides_foreign_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, owned_id, foreign_id = _client(monkeypatch)

    no_origin = client.put(
        f"/api/v1/me/notifications/{owned_id}/read",
        headers={"Cookie": f"__Host-launchpad_session={_SECRET}"},
    )
    no_cookie = client.put(
        f"/api/v1/me/notifications/{owned_id}/read",
        headers={"Origin": _ORIGIN},
    )
    bad_csrf = client.put(
        f"/api/v1/me/notifications/{owned_id}/read",
        headers=_headers(csrf="wrong"),
    )
    foreign = client.put(
        f"/api/v1/me/notifications/{foreign_id}/read",
        headers=_headers(csrf=derive_csrf_token(_SECRET)),
    )

    assert no_origin.status_code == 403, no_origin.text
    assert no_cookie.status_code == 401
    assert bad_csrf.status_code == 403
    assert foreign.status_code == 404
