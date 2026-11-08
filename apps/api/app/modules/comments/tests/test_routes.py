"""REST transport contracts for discussion commands, tickets, and avatars."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.sessions import MemberContext
from app.modules.comments.live import CommentLiveTicketService
from app.modules.comments.policies import (
    CommentConflictError,
    CommentForbiddenError,
    CommentInfrastructureError,
    CommentNotFoundError,
    CommentRateLimitError,
    CommentValidationError,
)
from app.modules.comments.routes import map_comment_error, router
from app.modules.comments.service import CommentCommandResult, CommentEntry
from app.modules.users.comment_attribution import CommentAuthorPhoto
from app.shared.config.settings import Settings
from app.shared.security.tokens import digest_token

ORIGIN = "https://launchpad.example"
CSRF = "comments-csrf-token"
NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)


class _Session:
    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield


class _Sessions:
    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, _Session())


class _Resolver:
    def __init__(self) -> None:
        self.member = MemberContext(
            uuid4(), True, uuid4(), csrf_digest=digest_token(CSRF), role="member"
        )

    async def resolve(self, _session: AsyncSession, *, session_secret: str) -> MemberContext:
        return self.member


class _Redis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.available = True

    def incr(self, key: str) -> int:
        if not self.available:
            raise RuntimeError("redis secret outage")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, _key: str, _seconds: int) -> bool:
        return True


class _Products:
    def __init__(self, product_id: UUID) -> None:
        self.product_id = product_id
        self.visible = True

    async def discussion_context(
        self, _session: AsyncSession, *, product_id: UUID, lock: bool = False
    ) -> object | None:
        if self.visible and product_id == self.product_id:
            return SimpleNamespace(product_id=product_id)
        return None


class _Photos:
    def __init__(self) -> None:
        self.available = True

    async def read_photo(
        self, _session: AsyncSession, _account_id: UUID
    ) -> CommentAuthorPhoto | None:
        if not self.available:
            return None
        return CommentAuthorPhoto(body=b"safe-image", media_type="image/png")


class _Comments:
    def __init__(self, product_id: UUID) -> None:
        self.product_id = product_id
        self.error: Exception | None = None
        self.visible_author = True
        self.calls: list[tuple[str, UUID | None, str, str]] = []

    async def create_root(self, _session: AsyncSession, **values: Any) -> CommentCommandResult:
        return await self._create("root", None, values)

    async def create_reply(self, _session: AsyncSession, **values: Any) -> CommentCommandResult:
        return await self._create("reply", cast(UUID, values["parent_id"]), values)

    async def _create(
        self, operation: str, parent_id: UUID | None, values: dict[str, Any]
    ) -> CommentCommandResult:
        if self.error is not None:
            raise self.error
        body = cast(str, values["body"]).strip()
        key = cast(str, values["idempotency_key"])
        if not key:
            raise CommentValidationError("invalid idempotency key")
        self.calls.append((operation, parent_id, body, key))
        return CommentCommandResult(
            CommentEntry(
                uuid4(),
                self.product_id,
                cast(UUID, values["author_id"]),
                parent_id,
                body,
                NOW,
            ),
            replayed=key == "replay-key",
        )

    async def has_visible_entry_on_product(
        self, _session: AsyncSession, *, product_id: UUID, account_id: UUID
    ) -> bool:
        return self.visible_author and product_id == self.product_id


def _fixture() -> tuple[
    FastAPI,
    Settings,
    UUID,
    _Comments,
    _Products,
    _Photos,
    _Redis,
]:
    settings = Settings(trusted_web_origins=(ORIGIN,))
    product_id = uuid4()
    comments = _Comments(product_id)
    products = _Products(product_id)
    photos = _Photos()
    redis = _Redis()
    routes = router(
        settings=settings,
        session_factory=cast(Any, _Sessions()),
        redis=redis,
        comment_service_factory=cast(Any, lambda: comments),
        ticket_service=CommentLiveTicketService(
            signing_key=b"route-comment-live-key-material" * 2,
            clock=lambda: NOW,
        ),
        photo_access=photos,
        product_access=cast(Any, products),
        session_service=_Resolver(),
    )
    app = FastAPI()
    app.include_router(routes)
    return app, settings, product_id, comments, products, photos, redis


def _headers(key: str = "comment-key") -> dict[str, str]:
    return {"Origin": ORIGIN, "X-CSRF-Token": CSRF, "Idempotency-Key": key}


def test_routes_expose_only_approved_rest_surface_and_schemas() -> None:
    app, *_rest = _fixture()
    operations = {
        (path, method.upper())
        for path, definition in app.openapi()["paths"].items()
        for method in definition
        if path.startswith("/api/v1/products")
    }
    assert operations == {
        ("/api/v1/products/{product_id}/comments", "POST"),
        ("/api/v1/products/{product_id}/comments/{parent_id}/replies", "POST"),
        ("/api/v1/products/{product_id}/comments/live-ticket", "POST"),
        ("/api/v1/products/{product_id}/comment-authors/{account_id}/photo", "GET"),
    }
    assert "CommentCreateInput" in app.openapi()["components"]["schemas"]


def test_commands_return_confirmed_root_reply_and_exact_replay_status() -> None:
    app, settings, product_id, comments, *_rest = _fixture()
    parent_id = uuid4()
    with TestClient(app) as client:
        client.cookies.set(settings.session_cookie_name, "session")
        root = client.post(
            f"/api/v1/products/{product_id}/comments",
            json={"body": "  Confirmed root  "},
            headers=_headers(),
        )
        reply = client.post(
            f"/api/v1/products/{product_id}/comments/{parent_id}/replies",
            json={"body": "Confirmed reply"},
            headers=_headers("reply-key"),
        )
        replay = client.post(
            f"/api/v1/products/{product_id}/comments",
            json={"body": "Confirmed root"},
            headers=_headers("replay-key"),
        )

    assert root.status_code == reply.status_code == 201
    assert root.json()["body"] == "Confirmed root"
    assert reply.json()["parent_id"] == str(parent_id)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    assert root.headers["cache-control"] == "no-store"
    assert [call[0] for call in comments.calls] == ["root", "reply", "root"]


def test_commands_require_origin_authentication_csrf_and_key() -> None:
    app, settings, product_id, comments, *_rest = _fixture()
    client = TestClient(app)
    path = f"/api/v1/products/{product_id}/comments"

    assert client.post(path, json={"body": "Hello"}).status_code == 403
    assert client.post(path, json={"body": "Hello"}, headers={"Origin": ORIGIN}).status_code == 401
    client.cookies.set(settings.session_cookie_name, "session")
    assert client.post(path, json={"body": "Hello"}, headers={"Origin": ORIGIN}).status_code == 403
    assert client.post(path, json={"body": "Hello"}, headers=_headers("")).status_code == 400
    assert comments.calls == []


@pytest.mark.parametrize(
    ("error", "status", "detail"),
    [
        (CommentValidationError("body secret"), 400, "invalid discussion request"),
        (CommentForbiddenError("account secret"), 403, "discussion posting is unavailable"),
        (CommentNotFoundError("product secret"), 404, "discussion unavailable"),
        (CommentConflictError("key secret"), 409, "discussion request conflicts"),
        (CommentInfrastructureError("database secret"), 503, "service temporarily unavailable"),
    ],
)
def test_command_failures_map_to_safe_stable_contracts(
    error: Exception, status: int, detail: str
) -> None:
    app, settings, product_id, comments, *_rest = _fixture()
    comments.error = error
    with TestClient(app) as client:
        client.cookies.set(settings.session_cookie_name, "session")
        response = client.post(
            f"/api/v1/products/{product_id}/comments",
            json={"body": "Keep my draft"},
            headers=_headers(),
        )
    assert response.status_code == status
    assert response.json() == {"detail": detail}
    assert "secret" not in response.text
    assert "Keep my draft" not in response.text


def test_rate_limit_mapping_returns_retry_after_without_sensitive_detail() -> None:
    error = CommentRateLimitError(
        "activity secret", retry_at=datetime.now(UTC) + timedelta(seconds=5)
    )
    mapped = map_comment_error(error)
    assert mapped.status_code == 429
    assert mapped.headers is not None
    assert 1 <= int(mapped.headers["Retry-After"]) <= 5
    assert "secret" not in str(mapped.detail)


def test_public_ticket_and_contextual_avatar_hide_unavailable_context() -> None:
    app, _settings, product_id, comments, products, photos, _redis = _fixture()
    account_id = uuid4()
    with TestClient(app) as client:
        ticket = client.post(
            f"/api/v1/products/{product_id}/comments/live-ticket",
            headers={"Origin": ORIGIN},
        )
        photo = client.get(f"/api/v1/products/{product_id}/comment-authors/{account_id}/photo")
        assert ticket.status_code == 200
        assert set(ticket.json()) == {"ticket", "expires_at"}
        assert photo.status_code == 200 and photo.content == b"safe-image"
        assert photo.headers["cache-control"] == "no-store"
        assert photo.headers["x-content-type-options"] == "nosniff"

        comments.visible_author = False
        assert (
            client.get(
                f"/api/v1/products/{product_id}/comment-authors/{account_id}/photo"
            ).status_code
            == 404
        )
        comments.visible_author = True
        photos.available = False
        assert (
            client.get(
                f"/api/v1/products/{product_id}/comment-authors/{account_id}/photo"
            ).status_code
            == 404
        )
        products.visible = False
        unavailable_ticket = client.post(
            f"/api/v1/products/{product_id}/comments/live-ticket",
            headers={"Origin": ORIGIN},
        )
        assert unavailable_ticket.status_code == 404
        assert unavailable_ticket.json() == {"detail": "discussion unavailable"}
