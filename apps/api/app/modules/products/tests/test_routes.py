"""Transport checks for owner-only product asset commands."""

from __future__ import annotations

import base64
from types import SimpleNamespace

from app.modules.products.routes import router
from app.shared.config.settings import Settings
from app.shared.db.database import Database
from app.shared.storage.objects import PrivateObjectStore
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import SecretStr
from redis import Redis


def _app(origins: tuple[str, ...] = ()) -> tuple[FastAPI, APIRouter]:
    settings = Settings(
        trusted_web_origins=origins,
        outbox_key_id="test",
        outbox_key=SecretStr(base64.b64encode(b"x" * 32).decode("ascii")),
    )
    storage = PrivateObjectStore(
        endpoint_url="http://minio:9000",
        bucket_name="private",
        access_key_id="key",
        secret_access_key="secret",
        client_factory=lambda: SimpleNamespace(),
    )
    routes = router(
        settings=settings,
        database=Database.connect(str(settings.database_url)),
        redis=Redis.from_url(str(settings.redis_url)),
        storage=storage,
    )
    app = FastAPI()
    app.include_router(routes)
    return app, routes


def test_asset_routes_are_explicit_and_require_trusted_origin() -> None:
    app, routes = _app(("http://localhost:8080",))
    paths = {route.path for route in routes.routes if isinstance(route, APIRoute)}

    assert paths == {
        "/api/v1/me/products/{product_id}/assets",
        "/api/v1/me/products/{product_id}/assets/{asset_id}/complete",
    }
    response = TestClient(app).post(
        "/api/v1/me/products/00000000-0000-0000-0000-000000000001/assets",
        json={"kind": "logo", "content_type": "image/png", "size": 100},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "request rejected"}


def test_asset_intent_contract_rejects_untrusted_upload_types() -> None:
    app, _ = _app(("http://localhost:8080",))
    response = TestClient(app).post(
        "/api/v1/me/products/00000000-0000-0000-0000-000000000001/assets",
        json={"kind": "logo", "content_type": "image/svg+xml", "size": 100},
        headers={"Origin": "http://localhost:8080"},
    )

    assert response.status_code == 422


def test_asset_mutations_accept_only_exact_configured_origins_before_auth() -> None:
    app, _ = _app(("http://localhost:8080", "http://127.0.0.1:8080"))
    client = TestClient(app)

    for origin in ("http://localhost:8080", "http://127.0.0.1:8080"):
        response = client.post(
            "/api/v1/me/products/00000000-0000-0000-0000-000000000001/assets",
            json={"kind": "logo", "content_type": "image/png", "size": 100},
            headers={"Origin": origin},
        )
        assert response.status_code == 401
