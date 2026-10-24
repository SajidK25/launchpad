"""REST authorization and validation for explicit vote review actions."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.modules.auth.sessions import MemberContext, SessionService
from app.modules.votes.routes import router
from app.shared.config.settings import Settings
from app.shared.db.database import Database
from app.shared.security.tokens import digest_token


def test_non_reviewer_cannot_call_vote_review_decision(monkeypatch: Any) -> None:
    csrf = "review-csrf"
    member = MemberContext(uuid4(), True, uuid4(), csrf_digest=digest_token(csrf), role="member")

    async def resolve(*_args: Any, **_kwargs: Any) -> MemberContext:
        return member

    monkeypatch.setattr(SessionService, "resolve", resolve)
    settings = Settings(
        trusted_web_origins=("https://testserver",),
        outbox_key_id="test",
        outbox_key=SecretStr(base64.b64encode(b"x" * 32).decode("ascii")),
    )
    app = FastAPI()
    app.include_router(
        router(
            settings=settings,
            database=Database.connect(str(settings.database_url)),
            redis=cast(Any, object()),
            review_service_factory=lambda: pytest.fail("non-reviewer reached service"),
        )
    )
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set(settings.session_cookie_name, "session-secret")
    response = client.post(
        f"/api/v1/votes/reviews/{uuid4()}/decision",
        json={"outcome": "invalidated", "reason": "Confirmed abuse."},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )

    assert response.status_code == 403


def test_reviewer_decision_route_returns_attributed_result(monkeypatch: Any) -> None:
    csrf = "review-csrf"
    reviewer_id, flag_id, decision_id = uuid4(), uuid4(), uuid4()
    member = MemberContext(
        reviewer_id, True, uuid4(), csrf_digest=digest_token(csrf), role="reviewer"
    )

    async def resolve(*_args: Any, **_kwargs: Any) -> MemberContext:
        return member

    monkeypatch.setattr(SessionService, "resolve", resolve)
    service_calls: list[dict[str, Any]] = []

    class _ReviewService:
        async def decide(self, _session: Any, **values: Any) -> Any:
            service_calls.append(values)
            return SimpleNamespace(
                id=decision_id,
                flag_id=flag_id,
                reviewer_account_id=reviewer_id,
                outcome="cleared",
                reason="Reviewed and valid.",
                created_at=datetime(2026, 10, 24, 12, tzinfo=UTC),
            )

    settings = Settings(
        trusted_web_origins=("https://testserver",),
        outbox_key_id="test",
        outbox_key=SecretStr(base64.b64encode(b"x" * 32).decode("ascii")),
    )
    app = FastAPI()
    app.include_router(
        router(
            settings=settings,
            database=Database.connect(str(settings.database_url)),
            redis=cast(Any, object()),
            review_service_factory=lambda: cast(Any, _ReviewService()),
        )
    )
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set(settings.session_cookie_name, "session-secret")
    response = client.post(
        f"/api/v1/votes/reviews/{flag_id}/decision",
        json={"outcome": "cleared", "reason": "  Reviewed and valid.  "},
        headers={"Origin": "https://testserver", "X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(decision_id),
        "flag_id": str(flag_id),
        "reviewer_account_id": str(reviewer_id),
        "outcome": "cleared",
        "reason": "Reviewed and valid.",
        "created_at": "2026-10-24T12:00:00Z",
    }
    assert service_calls == [
        {
            "reviewer_id": reviewer_id,
            "flag_id": flag_id,
            "outcome": "cleared",
            "reason": "Reviewed and valid.",
        }
    ]
