from fastapi import FastAPI
from redis import Redis

from app.modules.health.probes import database_probe, redis_probe, storage_probe
from app.modules.health.routes import router
from app.modules.health.service import HealthService
from app.shared.config.settings import Settings
from app.shared.db.database import Database
from app.shared.storage.client import StorageClient


def create_app(service: HealthService | None = None) -> FastAPI:
    settings = Settings() if service is None else None
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
    app.include_router(router(service))
    return app


app = create_app()
