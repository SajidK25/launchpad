import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis import Redis

from app.modules.auth.routes import router as auth_router
from app.modules.health.probes import database_probe, redis_probe, storage_probe
from app.modules.health.routes import router
from app.modules.health.service import HealthService
from app.modules.users.routes import router as users_router
from app.shared.config.settings import load_settings
from app.shared.db.database import Database
from app.shared.storage.client import StorageClient
from app.shared.storage.objects import PrivateObjectStore

logger = logging.getLogger(__name__)


def create_app(service: HealthService | None = None) -> FastAPI:
    settings = load_settings() if service is None else None
    database: Database | None = None
    storage: StorageClient | None = None
    if service is None and settings is not None:
        if settings.storage_access_key_id is None or settings.storage_secret_access_key is None:
            raise RuntimeError("Storage runtime credentials are required.")
        database = Database.connect(str(settings.database_url))
        storage = StorageClient(
            str(settings.storage_endpoint_url),
            settings.storage_access_key_id.get_secret_value(),
            settings.storage_secret_access_key.get_secret_value(),
        )
        service = HealthService(
            [
                database_probe(database),
                redis_probe(Redis.from_url(str(settings.redis_url))),
                storage_probe(storage, settings.storage_bucket),
            ]
        )
    assert service is not None
    app = FastAPI()

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        logger.error(
            "Unhandled request failure",
            extra={"method": request.method, "path": request.url.path},
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "internal server error"},
        )

    app.include_router(router(service))
    if settings is not None and database is not None:
        app.include_router(
            auth_router(
                settings=settings,
                database=database,
                redis=Redis.from_url(str(settings.redis_url)),
            )
        )
        assert storage is not None
        assert settings.storage_access_key_id is not None
        assert settings.storage_secret_access_key is not None
        profile_routes, profile_graphql = users_router(
            settings=settings,
            database=database,
            redis=Redis.from_url(str(settings.redis_url)),
            storage=PrivateObjectStore(
                endpoint_url=str(settings.storage_endpoint_url),
                public_endpoint_url=str(settings.public_upload_endpoint_url),
                bucket_name=settings.storage_bucket,
                access_key_id=settings.storage_access_key_id.get_secret_value(),
                secret_access_key=settings.storage_secret_access_key.get_secret_value(),
                client_factory=storage._client,
            ),
        )
        app.include_router(profile_routes)
        app.include_router(profile_graphql, prefix="/api/v1")
    return app


app = create_app()
