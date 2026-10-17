"""Owner-scoped REST contract for launch notification preferences."""

from __future__ import annotations

import base64
import threading
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.modules.auth.sessions import MemberContext, SessionService
from app.modules.notifications.live import NotificationPubSub
from app.modules.notifications.routes import router
from app.modules.notifications.service import NotificationService
from app.shared.config.settings import Settings
from app.shared.db.database import Database
from app.shared.security.csrf import derive_csrf_token
from app.shared.security.tokens import digest_token

_SECRET = "preference-route-session-secret"
_ORIGIN = "http://localhost:8080"
_PATH = "/api/v1/me/launch-notification-preferences"
_VALUES = {
    "reminder_email": True,
    "reminder_in_site": False,
    "live_email": True,
    "live_in_site": False,
    "failure_email": True,
    "failure_in_site": False,
}


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


def _client(monkeypatch: object) -> tuple[TestClient, UUID]:
    owner_id = uuid4()
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

    async def save(
        self: NotificationService, session: object, *, actor_id: UUID, values: dict[str, bool]
    ) -> dict[str, bool]:
        assert actor_id == owner_id
        assert values == _VALUES
        return values

    cast(Any, monkeypatch).setattr(SessionService, "resolve", resolve)
    cast(Any, monkeypatch).setattr(NotificationService, "update_launch_preferences", save)
    settings = Settings(
        trusted_web_origins=(_ORIGIN,),
        outbox_key_id="preference-route-test",
        outbox_key=SecretStr(base64.b64encode(b"p" * 32).decode("ascii")),
        review_writes_enabled=False,
    )
    app = FastAPI()
    app.include_router(
        router(
            settings=settings,
            database=Database.connect(str(settings.database_url)),
            redis=_RedisCounter(),
            live_redis=_PubSubClient(),
        )
    )
    return TestClient(app), owner_id


def _headers(*, authenticated: bool = True, csrf: str | None = None) -> dict[str, str]:
    headers = {"Origin": _ORIGIN}
    if authenticated:
        headers["Cookie"] = f"__Host-launchpad_session={_SECRET}"
    if csrf is not None:
        headers["X-CSRF-Token"] = csrf
    return headers


def test_preference_update_requires_owner_session_and_csrf(monkeypatch: object) -> None:
    client, _ = _client(monkeypatch)
    anonymous = client.put(_PATH, json=_VALUES, headers=_headers(authenticated=False))
    bad_csrf = client.put(_PATH, json=_VALUES, headers=_headers(csrf="wrong"))
    saved = client.put(
        _PATH,
        json=_VALUES,
        headers=_headers(csrf=derive_csrf_token(_SECRET)),
    )

    assert anonymous.status_code == 401
    assert bad_csrf.status_code == 403
    assert saved.status_code == 200, saved.text
    assert saved.json() == _VALUES


def test_preference_update_rejects_missing_extra_and_non_boolean_values(
    monkeypatch: object,
) -> None:
    client, _ = _client(monkeypatch)
    headers = _headers(csrf=derive_csrf_token(_SECRET))

    missing = client.put(
        _PATH,
        json={key: value for key, value in _VALUES.items() if key != "live_email"},
        headers=headers,
    )
    extra = client.put(_PATH, json={**_VALUES, "review_email": True}, headers=headers)
    non_boolean = client.put(_PATH, json={**_VALUES, "live_email": "false"}, headers=headers)

    assert missing.status_code == 422
    assert extra.status_code == 422
    assert non_boolean.status_code == 422
