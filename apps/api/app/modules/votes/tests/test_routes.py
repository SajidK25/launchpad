"""Transport contracts and safe error handling for vote commands."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import SecretStr
from redis import Redis

from app.modules.auth.sessions import MemberContext, SessionService
from app.modules.votes.policies import VoteChallengeError, VoteConflictError, VoteForbiddenError
from app.modules.votes.routes import map_vote_error, router
from app.modules.votes.service import VoteCommandResult
from app.shared.config.settings import Settings
from app.shared.db.database import Database
from app.shared.security.tokens import digest_token


def _app(origins: tuple[str, ...] = ()) -> tuple[FastAPI, APIRouter, list[str]]:
    settings = Settings(
        trusted_web_origins=origins,
        outbox_key_id="test",
        outbox_key=SecretStr(base64.b64encode(b"x" * 32).decode("ascii")),
    )
    calls: list[str] = []

    def service_factory() -> Any:
        calls.append("created")
        return SimpleNamespace()

    routes = router(
        settings=settings,
        database=Database.connect(str(settings.database_url)),
        redis=Redis.from_url(str(settings.redis_url)),
        service_factory=service_factory,
    )
    app = FastAPI()
    app.include_router(routes)
    return app, routes, calls


def test_vote_commands_are_rest_only_and_use_expected_methods() -> None:
    app, routes, _calls = _app(("http://localhost:8080",))
    operations = {
        (route.path, method)
        for route in routes.routes
        if isinstance(route, APIRoute)
        for method in route.methods or ()
    }
    assert operations == {
        ("/api/v1/votes", "POST"),
        ("/api/v1/votes/{product_id}", "DELETE"),
    }
    assert "VoteInput" in app.openapi()["components"]["schemas"]


def test_vote_commands_reject_bad_origin_before_auth_or_service() -> None:
    app, _routes, calls = _app(("http://localhost:8080",))
    response = TestClient(app).post(
        "/api/v1/votes",
        json={"product_id": "00000000-0000-0000-0000-000000000001"},
        headers={"Idempotency-Key": "vote-1"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "request rejected"}
    assert calls == []


def test_vote_commands_require_authentication_csrf_and_idempotency_key() -> None:
    app, _routes, calls = _app(("http://localhost:8080",))
    client = TestClient(app)
    path = "/api/v1/votes"
    headers = {"Origin": "http://localhost:8080"}
    missing_key = client.post(
        path,
        json={"product_id": "00000000-0000-0000-0000-000000000001"},
        headers=headers,
    )
    unauthenticated = client.post(
        path,
        json={"product_id": "00000000-0000-0000-0000-000000000001"},
        headers={**headers, "Idempotency-Key": "vote-1"},
    )
    assert missing_key.status_code == 422
    assert unauthenticated.status_code == 401
    assert calls == []


def test_vote_error_mapping_is_safe_and_uses_documented_statuses() -> None:
    assert map_vote_error(VoteForbiddenError("sensitive")).status_code == 403
    assert map_vote_error(VoteConflictError("state")).status_code == 409
    assert map_vote_error(VoteChallengeError("token")).status_code == 422
    forbidden = map_vote_error(VoteForbiddenError("account private detail"))
    assert forbidden.detail == "voting is unavailable for this account"


def test_vote_write_switch_defaults_off_and_turnstile_secret_is_secret_str() -> None:
    settings = Settings()
    assert settings.vote_writes_enabled is False
    secret_value = "turnstile-server-secret-value"
    configured = Settings(turnstile_secret_key=SecretStr(secret_value))
    assert isinstance(configured.turnstile_secret_key, SecretStr)
    assert secret_value not in repr(configured)


def test_only_high_risk_vote_actions_require_verified_turnstile(
    monkeypatch: Any,
) -> None:
    account_id = uuid4()
    csrf = "bound-csrf-token"

    async def resolve(_service: Any, _session: Any, *, session_secret: str) -> MemberContext:
        assert session_secret == "session-secret"
        return MemberContext(
            account_id,
            True,
            uuid4(),
            csrf_digest=digest_token(csrf),
        )

    monkeypatch.setattr(SessionService, "resolve", resolve)
    counts = {"count": 0}

    class _Redis:
        def incr(self, key: str) -> int:
            counts["count"] += 1
            return counts["count"]

        def expire(self, key: str, seconds: int) -> bool:
            return True

    product_id = uuid4()
    command_calls: list[dict[str, Any]] = []

    class _Service:
        async def cast(self, _session: Any, **values: Any) -> VoteCommandResult:
            command_calls.append(values)
            return VoteCommandResult(uuid4(), product_id, True, datetime.now(UTC))

    verified_tokens: list[str] = []

    async def verifier(token: str, remote_ip: str | None) -> bool:
        verified_tokens.append(token)
        return token == "valid-token"

    settings = Settings(
        trusted_web_origins=("https://testserver",),
        outbox_key_id="test",
        outbox_key=SecretStr(base64.b64encode(b"x" * 32).decode("ascii")),
        vote_account_velocity_limit=1,
    )
    app = FastAPI()
    app.include_router(
        router(
            settings=settings,
            database=Database.connect(str(settings.database_url)),
            redis=_Redis(),  # type: ignore[arg-type]
            service_factory=lambda: _Service(),  # type: ignore[arg-type]
            challenge_verifier=verifier,
        )
    )
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set(settings.session_cookie_name, "session-secret")
    headers = {
        "Origin": "https://testserver",
        "X-CSRF-Token": csrf,
        "Idempotency-Key": "vote-risk",
    }
    body = {"product_id": str(product_id)}
    low_risk = client.post("/api/v1/votes", json=body, headers=headers)
    challenged = client.post(
        "/api/v1/votes",
        json=body,
        headers={**headers, "Idempotency-Key": "vote-risk-2", "X-Turnstile-Token": "valid-token"},
    )
    missing_challenge = client.post(
        "/api/v1/votes",
        json=body,
        headers={**headers, "Idempotency-Key": "vote-risk-3"},
    )
    invalid_challenge = client.post(
        "/api/v1/votes",
        json=body,
        headers={
            **headers,
            "Idempotency-Key": "vote-risk-4",
            "X-Turnstile-Token": "invalid-token",
        },
    )
    assert low_risk.status_code == 200, low_risk.text
    assert low_risk.json()["active"] is True
    assert challenged.status_code == 200
    assert missing_challenge.status_code == 422
    assert invalid_challenge.status_code == 422
    assert verified_tokens == ["valid-token", "invalid-token"]
    assert command_calls[0]["risk_signal"] is None
    assert command_calls[1]["risk_signal"] == "account_velocity"
    assert len(command_calls) == 2
