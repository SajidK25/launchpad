"""Authenticated one-notification read command."""

import base64
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.sessions import SessionService, UnauthenticatedError
from app.modules.auth.staff import AuthAccessService
from app.modules.notifications.live import NotificationRedis, notification_live_router
from app.modules.notifications.schemas import NotificationKind
from app.modules.notifications.service import (
    NotificationForbiddenError,
    NotificationNotFoundError,
    NotificationService,
    NotificationValidationError,
)
from app.shared.config.settings import Settings
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.outbox import OutboxRepository
from app.shared.security.csrf import RequestSecurityError, require_csrf, validate_origin
from app.shared.security.rate_limit import (
    RateLimiter,
    RateLimitExceeded,
    RateLimitUnavailable,
    RedisLike,
)


class NotificationReadResponse(BaseModel):
    """Safe result of marking one notification read."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: NotificationKind
    created_at: datetime
    read_at: datetime | None


def router(
    *,
    settings: Settings,
    database: Database,
    redis: RedisLike,
    live_redis: NotificationRedis,
) -> APIRouter:
    """Register the inbox read command and authenticated notification socket."""

    if settings.outbox_key is None or settings.outbox_key_id is None:
        raise RuntimeError("Outbox encryption configuration is required.")
    codec = EmailPayloadCodec(
        {settings.outbox_key_id: base64.b64decode(settings.outbox_key.get_secret_value())},
        settings.outbox_key_id,
    )
    limiter = RateLimiter(redis, limit=60, window_seconds=60)
    session_factory = async_sessionmaker(database.engine, expire_on_commit=False)
    session_service = SessionService()
    routes = APIRouter(prefix="/api/v1")

    async def db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    DbSession = Annotated[AsyncSession, Depends(db_session)]

    def service() -> NotificationService:
        return NotificationService(
            member_access=AuthAccessService(),
            outbox_repository=OutboxRepository(),
            payload_codec=codec,
        )

    def map_error(error: Exception) -> HTTPException:
        if isinstance(error, NotificationForbiddenError):
            return HTTPException(status_code=403, detail="notification access is forbidden")
        if isinstance(error, NotificationNotFoundError):
            return HTTPException(status_code=404, detail="notification unavailable")
        if isinstance(error, NotificationValidationError):
            return HTTPException(status_code=422, detail="invalid notification request")
        if isinstance(error, UnauthenticatedError):
            return HTTPException(status_code=401, detail="authentication required")
        if isinstance(error, RateLimitExceeded):
            return HTTPException(status_code=429, detail="try again later")
        if isinstance(error, (SQLAlchemyError, RedisError, RateLimitUnavailable)):
            return HTTPException(status_code=503, detail="service unavailable")
        return HTTPException(status_code=400, detail="request could not be completed")

    @routes.put(
        "/me/notifications/{notification_id}/read",
        response_model=NotificationReadResponse,
    )
    async def mark_notification_read(
        notification_id: UUID,
        request: Request,
        session: DbSession,
        x_csrf_token: str | None = Header(default=None),
    ) -> NotificationReadResponse:
        try:
            validate_origin(request.headers.get("origin"), settings.trusted_web_origins)
            async with session.begin():
                secret = request.cookies.get(settings.session_cookie_name)
                if not secret:
                    raise HTTPException(status_code=401, detail="authentication required")
                member = await session_service.resolve(session, session_secret=secret)
                require_csrf(
                    origin=request.headers.get("origin"),
                    trusted_origin=settings.trusted_web_origins,
                    token=x_csrf_token,
                    expected_digest=member.csrf_digest,
                )
                source = request.client.host if request.client else "unknown"
                await limiter.check(
                    address_key=f"notification:read:account:{member.account_id.hex}",
                    source_key=f"notification:read:source:{source}",
                )
                result = await service().mark_read(
                    session, actor_id=member.account_id, notification_id=notification_id
                )
            return NotificationReadResponse.model_validate(result)
        except RequestSecurityError as error:
            raise HTTPException(status_code=403, detail="request rejected") from error
        except HTTPException:
            raise
        except Exception as error:
            raise map_error(error) from error

    routes.include_router(
        notification_live_router(
            settings=settings,
            session_factory=session_factory,
            session_service=session_service,
            redis=live_redis,
        )
    )
    return routes
