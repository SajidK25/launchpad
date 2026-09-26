import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from redis import Redis

import app.main as main
from app.main import create_app
from app.modules.auth.routes import router as auth_router
from app.modules.health.service import HealthService, ProbeResult
from app.shared.config.settings import Settings
from app.shared.db.database import Database


def test_auth_router_exposes_only_safe_auth_actions() -> None:
    settings = Settings()
    database = Database.connect(str(settings.database_url))
    routes = auth_router(
        settings=settings,
        database=database,
        redis=Redis.from_url(str(settings.redis_url)),
    )

    assert {route.path for route in routes.routes if isinstance(route, APIRoute)} == {
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/session",
        "/api/v1/auth/logout",
        "/api/v1/auth/verification-requests",
        "/api/v1/auth/verify",
        "/api/v1/auth/password-reset-requests",
        "/api/v1/auth/password-resets",
    }
    app = FastAPI()
    app.include_router(routes)
    paths = app.openapi()["paths"]
    assert paths["/api/v1/auth/register"]["post"]["responses"]["202"]
    assert paths["/api/v1/auth/login"]["post"]["responses"]["200"]
    assert paths["/api/v1/auth/session"]["get"]["responses"]["200"]
    assert paths["/api/v1/auth/logout"]["post"]["responses"]["204"]
    assert paths["/api/v1/auth/verification-requests"]["post"]["responses"]["202"]
    assert paths["/api/v1/auth/verify"]["post"]["responses"]["200"]
    assert paths["/api/v1/auth/password-reset-requests"]["post"]["responses"]["202"]
    assert paths["/api/v1/auth/password-resets"]["post"]["responses"]["204"]


def test_injected_health_app_does_not_mount_auth_routes() -> None:
    async def healthy() -> ProbeResult:
        return ProbeResult(True)

    client = TestClient(create_app(HealthService([healthy])))

    assert client.get("/api/v1/health/live").status_code == 200
    assert client.post("/api/v1/auth/login").status_code == 404


def test_unexpected_errors_have_safe_response() -> None:
    async def healthy() -> ProbeResult:
        return ProbeResult(True)

    app = create_app(HealthService([healthy]))

    @app.get("/test-error")
    async def test_error() -> None:
        raise RuntimeError("secret details")

    response = TestClient(app, raise_server_exceptions=False).get("/test-error")
    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    assert "secret details" not in response.text


def test_auth_boundary_rejects_missing_origin_and_session_without_db_queries() -> None:
    settings = Settings()
    database = Database.connect(str(settings.database_url))
    app = FastAPI()
    app.include_router(
        auth_router(
            settings=settings,
            database=database,
            redis=Redis.from_url(str(settings.redis_url)),
        )
    )

    client = TestClient(app)
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "a@b.test", "password": "safe password"}
        ).status_code
        == 403
    )
    assert client.get("/api/v1/auth/session").status_code == 401


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/auth/register", {"email": "a@b.test", "password": "safe password"}),
        ("/api/v1/auth/verify", {"token": "token"}),
        ("/api/v1/auth/password-reset-requests", {"email": "a@b.test"}),
        (
            "/api/v1/auth/password-resets",
            {"token": "token", "new_password": "safe password"},
        ),
        ("/api/v1/auth/logout", None),
        ("/api/v1/auth/verification-requests", None),
    ],
)
def test_unsafe_anonymous_actions_require_trusted_origin(
    path: str, payload: dict[str, str] | None
) -> None:
    settings = Settings()
    app = FastAPI()
    app.include_router(
        auth_router(
            settings=settings,
            database=Database.connect(str(settings.database_url)),
            redis=Redis.from_url(str(settings.redis_url)),
        )
    )

    response = TestClient(app).post(path, json=payload)
    assert response.status_code == 403
    assert "traceback" not in response.text.lower()


def test_configured_app_mounts_auth_routes(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = Settings()
    database = Database.connect(str(settings.database_url))

    async def healthy() -> ProbeResult:
        return ProbeResult(True)

    monkeypatch.setattr(main, "load_settings", lambda: settings)
    monkeypatch.setattr(
        main, "Database", type("DatabaseFactory", (), {"connect": staticmethod(lambda _: database)})
    )
    monkeypatch.setattr(main, "database_probe", lambda _: healthy)
    monkeypatch.setattr(main, "redis_probe", lambda _: healthy)
    monkeypatch.setattr(main, "storage_probe", lambda *_: healthy)

    app = create_app()
    paths = set(app.openapi()["paths"])
    assert "/api/v1/auth/login" in paths
