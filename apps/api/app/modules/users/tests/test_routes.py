from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import APIRouter, FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from redis import Redis

from app.modules.users.routes import router
from app.shared.config.settings import Settings
from app.shared.db.database import Database
from app.shared.storage.objects import PrivateObjectStore


def _router(
    trusted_origins: tuple[str, ...] = (),
) -> tuple[FastAPI, APIRouter, APIRouter]:
    settings = Settings(trusted_web_origins=trusted_origins)
    database = Database.connect(str(settings.database_url))
    storage = PrivateObjectStore(
        endpoint_url=str(settings.storage_endpoint_url),
        bucket_name=settings.storage_bucket,
        access_key_id="key",
        secret_access_key="secret",
        client_factory=lambda: SimpleNamespace(),
    )
    routes, graphql = router(
        settings=settings,
        database=database,
        redis=Redis.from_url(str(settings.redis_url)),
        storage=storage,
    )
    app = FastAPI()
    app.include_router(routes)
    app.include_router(graphql, prefix="/api/v1")
    return app, routes, graphql


def test_profile_routes_are_explicit_and_unsafe_calls_require_origin() -> None:
    app, routes, _ = _router()
    paths = {route.path for route in routes.routes if isinstance(route, APIRoute)}
    assert {
        "/api/v1/me/profile",
        "/api/v1/me/profile/publish",
        "/api/v1/me/profile/unpublish",
        "/api/v1/me/profile/photo-uploads",
        "/api/v1/me/profile/photo-uploads/{upload_id}/complete",
        "/api/v1/profiles/{account_id}/photo",
    } == paths
    response = TestClient(app).patch(
        "/api/v1/me/profile",
        json={"version": 0, "bio": "private"},
    )
    assert response.status_code == 403
    assert "traceback" not in response.text.lower()


def test_profile_mutation_accepts_each_configured_origin_before_authentication() -> None:
    app, _, _ = _router(("http://localhost:8080", "http://127.0.0.1:8080"))
    client = TestClient(app)

    for origin in ("http://localhost:8080", "http://127.0.0.1:8080"):
        response = client.patch(
            "/api/v1/me/profile",
            json={"version": 0, "bio": "private"},
            headers={"Origin": origin},
        )
        assert response.status_code == 401


def test_graphql_is_read_only_and_maps_public_profile_fields() -> None:
    app, _, graphql = _router()
    account_id = uuid4()
    profile = SimpleNamespace(
        account_id=account_id,
        display_name="Ada",
        bio="Builder",
        photo_key="profile-clean/a/b",
        visibility="public",
        published_at=None,
        version=1,
    )

    class SessionContext:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *args: object) -> None:
            return None

    class FakeSessionFactory:
        def __call__(self) -> SessionContext:
            return SessionContext()

    class FakeService:
        async def get_public(self, session: object, *, account_id: UUID) -> object:
            from app.modules.users.service import ProfileResult, ProfileView

            return ProfileResult(
                ProfileView(
                    account_id=account_id,
                    display_name=profile.display_name,
                    bio=profile.bio,
                    photo_key=profile.photo_key,
                    visibility=profile.visibility,
                    published_at=profile.published_at,
                    version=profile.version,
                ),
                ["https://example.com"],
            )

    async def context_getter(request: Request) -> dict[str, object]:
        return {
            "member": None,
            "session_factory": FakeSessionFactory(),
            "service_factory": lambda member: FakeService(),
        }

    # Replace the generated router's context getter only for this isolated schema test.
    del graphql
    from app.modules.users.graphql import build_router

    test_graphql = build_router(context_getter)
    app = FastAPI()
    app.include_router(test_graphql, prefix="/api/v1")
    response = TestClient(app).post(
        "/api/v1/graphql",
        json={
            "query": (
                "query($id: UUID!){ publicProfile(accountId: $id) "
                "{ displayName bio links photoUrl } }"
            ),
            "variables": {"id": str(account_id)},
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["publicProfile"]["displayName"] == "Ada"
    mutation = TestClient(app).post("/api/v1/graphql", json={"query": "mutation { nope }"})
    assert mutation.status_code == 200
    assert mutation.json()["data"] is None
    assert mutation.json()["errors"]
