"""Authenticated REST commands for private product drafts and asset uploads."""

import base64
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from app.modules.auth.sessions import MemberContext, SessionService, UnauthenticatedError
from app.modules.auth.staff import AuthAccessService
from app.modules.products.policies import (
    ProductConflictError,
    ProductForbiddenError,
    ProductInfrastructureError,
    ProductNotFoundError,
    ProductQuotaError,
)
from app.modules.products.schemas import (
    ProductAssetCompleteResponse,
    ProductAssetIntentInput,
    ProductAssetIntentResponse,
)
from app.modules.products.service import ProductService
from app.shared.config.settings import Settings
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.outbox import OutboxRepository
from app.shared.security.csrf import RequestSecurityError, require_csrf, validate_origin
from app.shared.storage.objects import (
    ObjectNotFound,
    ObjectOperationError,
    ObjectValidationError,
    PrivateObjectStore,
)
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def router(
    *, settings: Settings, database: Database, redis: Redis, storage: PrivateObjectStore
) -> APIRouter:
    """Build owner-only product routes with cookie auth and origin-bound CSRF checks."""

    del redis  # Reserved for the product mutation rate-limit integration.
    if settings.outbox_key is None or settings.outbox_key_id is None:
        raise RuntimeError("Outbox encryption configuration is required.")
    codec = EmailPayloadCodec(
        {settings.outbox_key_id: base64.b64decode(settings.outbox_key.get_secret_value())},
        settings.outbox_key_id,
    )
    session_factory = async_sessionmaker(database.engine, expire_on_commit=False)
    session_service = SessionService()
    routes = APIRouter(prefix="/api/v1")

    async def db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    DbSession = Annotated[AsyncSession, Depends(db_session)]

    async def current_member(request: Request, session: AsyncSession) -> MemberContext:
        secret = request.cookies.get(settings.session_cookie_name)
        if not secret:
            raise HTTPException(status_code=401, detail="authentication required")
        try:
            return await session_service.resolve(session, session_secret=secret)
        except UnauthenticatedError as error:
            raise HTTPException(status_code=401, detail="authentication required") from error

    def require_origin(request: Request) -> None:
        try:
            validate_origin(request.headers.get("origin"), settings.trusted_web_origins)
        except RequestSecurityError as error:
            raise HTTPException(status_code=403, detail="request rejected") from error

    def require_member_csrf(request: Request, member: MemberContext, token: str | None) -> None:
        try:
            require_csrf(
                origin=request.headers.get("origin"),
                trusted_origin=settings.trusted_web_origins,
                token=token,
                expected_digest=member.csrf_digest,
            )
        except RequestSecurityError as error:
            raise HTTPException(status_code=403, detail="request rejected") from error

    def service() -> ProductService:
        return ProductService(
            member_access=AuthAccessService(),
            outbox_repository=OutboxRepository(),
            payload_codec=codec,
        )

    def map_error(error: Exception) -> HTTPException:
        if isinstance(error, ProductForbiddenError):
            return HTTPException(status_code=403, detail="product access is forbidden")
        if isinstance(error, ProductNotFoundError):
            return HTTPException(status_code=404, detail="product unavailable")
        if isinstance(error, ProductConflictError):
            return HTTPException(status_code=409, detail="product changed; reload and retry")
        if isinstance(error, ProductQuotaError):
            return HTTPException(status_code=429, detail="upload limit reached")
        if isinstance(error, (ObjectValidationError,)):
            return HTTPException(status_code=422, detail="invalid asset upload")
        if isinstance(
            error,
            (
                ProductInfrastructureError,
                ObjectOperationError,
                ObjectNotFound,
                SQLAlchemyError,
                RedisError,
            ),
        ):
            return HTTPException(status_code=503, detail="service unavailable")
        return HTTPException(status_code=400, detail="request could not be completed")

    @routes.delete("/me/products/{product_id}", status_code=204)
    async def delete_draft(
        product_id: UUID,
        request: Request,
        session: DbSession,
        expected_version: int,
        x_csrf_token: str | None = Header(default=None),
    ) -> Response:
        require_origin(request)
        async with session.begin():
            member = await current_member(request, session)
            require_member_csrf(request, member, x_csrf_token)
            try:
                await service().delete_draft(
                    session,
                    actor_id=member.account_id,
                    product_id=product_id,
                    expected_version=expected_version,
                    storage=storage,
                )
            except (
                ProductForbiddenError,
                ProductNotFoundError,
                ProductConflictError,
                ProductInfrastructureError,
                ObjectOperationError,
                SQLAlchemyError,
                RedisError,
            ) as error:
                raise map_error(error) from error
        return Response(status_code=204)

    @routes.post(
        "/me/products/{product_id}/assets",
        response_model=ProductAssetIntentResponse,
        status_code=201,
    )
    async def create_asset_intent(
        product_id: UUID,
        payload: ProductAssetIntentInput,
        request: Request,
        session: DbSession,
        x_csrf_token: str | None = Header(default=None),
    ) -> ProductAssetIntentResponse:
        require_origin(request)
        async with session.begin():
            member = await current_member(request, session)
            require_member_csrf(request, member, x_csrf_token)
            try:
                result = await service().create_asset_intent(
                    session,
                    actor_id=member.account_id,
                    product_id=product_id,
                    intent=payload,
                    storage=storage,
                )
            except (
                ProductForbiddenError,
                ProductNotFoundError,
                ProductConflictError,
                ProductQuotaError,
                ProductInfrastructureError,
                ObjectOperationError,
                SQLAlchemyError,
                RedisError,
            ) as error:
                raise map_error(error) from error
        return ProductAssetIntentResponse(
            asset_id=result.asset.id,
            upload_url=result.upload.upload_url,
            fields=result.upload.fields,
            expires_in=result.upload.expires_in,
        )

    @routes.post(
        "/me/products/{product_id}/assets/{asset_id}/complete",
        response_model=ProductAssetCompleteResponse,
    )
    async def complete_asset(
        product_id: UUID,
        asset_id: UUID,
        request: Request,
        session: DbSession,
        x_csrf_token: str | None = Header(default=None),
    ) -> ProductAssetCompleteResponse:
        require_origin(request)
        async with session.begin():
            member = await current_member(request, session)
            require_member_csrf(request, member, x_csrf_token)
            try:
                result = await service().complete_asset(
                    session,
                    actor_id=member.account_id,
                    product_id=product_id,
                    asset_id=asset_id,
                    storage=storage,
                )
            except (
                ProductForbiddenError,
                ProductNotFoundError,
                ProductConflictError,
                ProductInfrastructureError,
                ObjectOperationError,
                SQLAlchemyError,
                RedisError,
            ) as error:
                raise map_error(error) from error
        if result.state == "failed":
            raise HTTPException(status_code=422, detail="asset bytes are invalid or unavailable")
        return ProductAssetCompleteResponse(
            asset_id=result.id,
            kind=result.kind,
            media_type=result.media_type,
            byte_count=result.byte_count,
            state="clean",
        )

    return routes
