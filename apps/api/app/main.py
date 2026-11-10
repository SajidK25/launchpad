import base64
import logging
from typing import cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.auth.routes import router as auth_router
from app.modules.auth.staff import AuthAccessService
from app.modules.comments.live import (
    CommentLiveRedis,
    comment_live_router,
)
from app.modules.comments.live import (
    ticket_service_for_settings as comment_ticket_service_for_settings,
)
from app.modules.comments.routes import router as comments_router
from app.modules.comments.service import (
    CommentAttributionAccess,
    CommentService,
    ProductDiscussionAccess,
)
from app.modules.health.probes import database_probe, redis_probe, storage_probe
from app.modules.health.routes import router
from app.modules.health.service import HealthService
from app.modules.launches.routes import router as launches_router
from app.modules.notifications.live import NotificationRedis
from app.modules.notifications.routes import router as notifications_router
from app.modules.products.routes import router as products_router
from app.modules.products.service import ProductService
from app.modules.users.comment_attribution import CommentAttributionService
from app.modules.users.routes import router as users_router
from app.modules.votes.live import (
    VoteLiveRedis,
    vote_live_router,
)
from app.modules.votes.live import (
    ticket_service_for_settings as vote_ticket_service_for_settings,
)
from app.modules.votes.routes import router as votes_router
from app.modules.votes.service import RankingRedis
from app.shared.config.settings import load_settings
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
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
            provider=settings.storage_provider,
            region_name=settings.storage_region,
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
        private_store = PrivateObjectStore(
            endpoint_url=str(settings.storage_endpoint_url),
            public_endpoint_url=str(settings.public_upload_endpoint_url),
            region_name=settings.storage_region,
            bucket_name=settings.storage_bucket,
            access_key_id=settings.storage_access_key_id.get_secret_value(),
            secret_access_key=settings.storage_secret_access_key.get_secret_value(),
            client_factory=storage._client,
        )
        live_redis = cast(NotificationRedis, AsyncRedis.from_url(str(settings.redis_url)))
        if settings.outbox_key is None or settings.outbox_key_id is None:
            raise RuntimeError("Outbox encryption configuration is required.")
        codec = EmailPayloadCodec(
            {
                settings.outbox_key_id: base64.b64decode(
                    settings.outbox_key.get_secret_value(), validate=True
                )
            },
            settings.outbox_key_id,
        )
        comment_session_factory = async_sessionmaker(database.engine, expire_on_commit=False)
        comment_product_access = cast(
            ProductDiscussionAccess,
            ProductService(member_access=AuthAccessService(), payload_codec=codec),
        )
        comment_attribution = CommentAttributionService(storage=private_store)

        def comment_service_factory() -> CommentService:
            return CommentService(
                account_access=AuthAccessService(),
                attribution_access=cast(CommentAttributionAccess, comment_attribution),
                product_access=comment_product_access,
                codec=codec,
                writes_enabled=lambda: settings.comment_writes_enabled,
            )

        profile_routes, profile_graphql = users_router(
            settings=settings,
            database=database,
            redis=Redis.from_url(str(settings.redis_url)),
            storage=private_store,
            ranking_redis=cast(RankingRedis, live_redis),
            comment_activity=(comment_service_factory() if settings.comments_enabled else None),
            comment_service_factory=(
                comment_service_factory if settings.comments_enabled else None
            ),
        )
        app.include_router(profile_routes)
        app.include_router(profile_graphql, prefix="/api/v1")
        app.include_router(
            notifications_router(
                settings=settings,
                database=database,
                redis=Redis.from_url(str(settings.redis_url)),
                live_redis=live_redis,
            )
        )
        if settings.products_enabled:
            app.include_router(
                products_router(
                    settings=settings,
                    database=database,
                    redis=Redis.from_url(str(settings.redis_url)),
                    storage=private_store,
                )
            )
        if settings.launches_enabled:
            app.include_router(
                launches_router(
                    settings=settings,
                    database=database,
                    redis=Redis.from_url(str(settings.redis_url)),
                )
            )
        if settings.products_enabled and settings.launches_enabled:
            app.include_router(
                votes_router(
                    settings=settings,
                    database=database,
                    redis=Redis.from_url(str(settings.redis_url)),
                )
            )
            app.include_router(
                vote_live_router(
                    settings=settings,
                    redis=cast(VoteLiveRedis, AsyncRedis.from_url(str(settings.redis_url))),
                    tickets=vote_ticket_service_for_settings(settings),
                )
            )
        if settings.comments_enabled:
            comment_sync_redis = Redis.from_url(str(settings.redis_url))
            comment_tickets = comment_ticket_service_for_settings(settings)
            app.include_router(
                comments_router(
                    settings=settings,
                    session_factory=comment_session_factory,
                    redis=comment_sync_redis,
                    comment_service_factory=comment_service_factory,
                    ticket_service=comment_tickets,
                    photo_access=comment_attribution,
                    product_access=comment_product_access,
                )
            )
            app.include_router(
                comment_live_router(
                    settings=settings,
                    redis=cast(CommentLiveRedis, AsyncRedis.from_url(str(settings.redis_url))),
                    tickets=comment_tickets,
                    session_factory=comment_session_factory,
                    product_access=comment_product_access,
                )
            )
    return app


app = create_app()
