"""Transport checks for authenticated REST launch booking commands."""

from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from redis import Redis

from app.modules.launches.policies import LaunchConflictError, LaunchValidationError
from app.modules.launches.routes import map_launch_error, router
from app.modules.launches.schemas import LaunchBookingInput
from app.shared.config.settings import Settings
from app.shared.db.database import Database


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


def test_launch_commands_are_rest_only_and_use_expected_methods() -> None:
    app, routes, _calls = _app(("http://localhost:8080",))
    operations = {
        (route.path, method)
        for route in routes.routes
        if isinstance(route, APIRoute)
        for method in route.methods or ()
    }
    path = "/api/v1/me/products/{product_id}/launch-booking"
    assert operations == {(path, "POST"), (path, "PUT"), (path, "DELETE")}
    assert "Mutation" not in app.openapi()["components"]["schemas"]


def test_launch_mutations_reject_bad_origin_before_auth_or_service() -> None:
    app, _routes, calls = _app(("http://localhost:8080",))
    response = TestClient(app).post(
        "/api/v1/me/products/00000000-0000-0000-0000-000000000001/launch-booking",
        json={"launch_date": "2026-10-20", "expected_version": 4},
        headers={"Idempotency-Key": "book-1"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "request rejected"}
    assert calls == []


def test_launch_mutations_require_valid_origin_and_authenticated_cookie() -> None:
    app, _routes, calls = _app(("http://localhost:8080",))
    response = TestClient(app).post(
        "/api/v1/me/products/00000000-0000-0000-0000-000000000001/launch-booking",
        json={"launch_date": "2026-10-20", "expected_version": 4},
        headers={"Origin": "http://localhost:8080", "Idempotency-Key": "book-1"},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "authentication required"}
    assert calls == []


def test_launch_mutation_validates_body_and_required_idempotency_header() -> None:
    app, _routes, calls = _app(("http://localhost:8080",))
    path = "/api/v1/me/products/00000000-0000-0000-0000-000000000001/launch-booking"
    client = TestClient(app)
    headers = {"Origin": "http://localhost:8080"}
    invalid = client.post(
        path,
        json={"launch_date": "not-a-date", "expected_version": 4},
        headers={**headers, "Idempotency-Key": "book-2"},
    )
    missing_key = client.post(
        path,
        json={"launch_date": "2026-10-20", "expected_version": 4},
        headers=headers,
    )
    assert invalid.status_code == 422
    assert missing_key.status_code == 422
    assert calls == []
    try:
        LaunchBookingInput.model_validate(
            {"launch_date": "2026-10-20", "expected_version": 4, "founder_id": "private"}
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("extra launch request fields must be rejected")


def test_date_window_errors_are_unprocessable_but_state_conflicts_remain_conflicts() -> None:
    assert map_launch_error(LaunchValidationError("outside window")).status_code == 422
    assert map_launch_error(LaunchConflictError("full day")).status_code == 409
