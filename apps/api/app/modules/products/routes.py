"""Authenticated REST commands for private product drafts and asset uploads."""

import base64
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.sessions import MemberContext, SessionService, UnauthenticatedError
from app.modules.auth.staff import AuthAccessService
from app.modules.products.policies import (
    ProductConflictError,
    ProductForbiddenError,
    ProductInfrastructureError,
    ProductNotFoundError,
    ProductQuotaError,
    require_active_founder,
    require_editable_status,
)
from app.modules.products.schemas import (
    ProductAssetAttachmentInput,
    ProductAssetCompleteResponse,
    ProductAssetIntentInput,
    ProductAssetIntentResponse,
    ProductSaveInput,
    ProductStateResponse,
    ProductSubmitResponse,
    ProductVersionInput,
    ProductWithdrawInput,
    ReviewDecisionInput,
    ReviewDecisionResponse,
)
from app.modules.products.service import (
    ProductDraft,
    ProductService,
    ProductValidationError,
    SubmittedProduct,
)
from app.shared.config.settings import Settings
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.outbox import OutboxRepository
from app.shared.security.csrf import RequestSecurityError, require_csrf, validate_origin
from app.shared.security.rate_limit import RateLimiter, RateLimitExceeded, RateLimitUnavailable
from app.shared.storage.objects import (
    ObjectNotFound,
    ObjectOperationError,
    ObjectValidationError,
    PrivateObjectStore,
)
from app.shared.storage.uploads import (
    DEFAULT_UPLOAD_RECEIVER,
    UploadOverloaded,
    UploadReceiveError,
    UploadTimedOut,
    UploadTooLarge,
)


def router(
    *, settings: Settings, database: Database, redis: Redis, storage: PrivateObjectStore
) -> APIRouter:
    """Build owner-only product routes with cookie auth and origin-bound CSRF checks."""

    limiter = RateLimiter(redis, limit=60, window_seconds=60)
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

    async def bound_action(request: Request, member: MemberContext, action: str) -> None:
        """Bound product writes per account and source without limiting withdrawal."""

        source = request.client.host if request.client else "unknown"
        await limiter.check(
            address_key=f"product:{action}:account:{member.account_id.hex}",
            source_key=f"product:{action}:source:{source}",
        )

    def map_error(error: Exception) -> HTTPException:
        if isinstance(error, ProductForbiddenError):
            return HTTPException(status_code=403, detail="product access is forbidden")
        if isinstance(error, ProductNotFoundError):
            return HTTPException(status_code=404, detail="product unavailable")
        if isinstance(error, ProductConflictError):
            return HTTPException(status_code=409, detail="product changed; reload and retry")
        if isinstance(error, ProductValidationError):
            return HTTPException(
                status_code=422,
                detail={
                    "message": "product fields are invalid or incomplete",
                    "fields": error.fields,
                },
            )
        if isinstance(error, ProductQuotaError):
            return HTTPException(status_code=409, detail="product limit reached")
        if isinstance(error, RateLimitExceeded):
            return HTTPException(status_code=429, detail="try again later")
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
                RateLimitUnavailable,
            ),
        ):
            return HTTPException(status_code=503, detail="service unavailable")
        return HTTPException(status_code=400, detail="request could not be completed")

    @routes.post(
        "/staff/products/{product_id}/review-decisions",
        response_model=ReviewDecisionResponse,
        status_code=201,
    )
    async def create_review_decision(
        product_id: UUID,
        payload: ReviewDecisionInput,
        request: Request,
        session: DbSession,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=255)
        ],
        x_csrf_token: str | None = Header(default=None),
    ) -> ReviewDecisionResponse:
        require_origin(request)
        if not settings.review_writes_enabled:
            raise HTTPException(status_code=503, detail="service unavailable")
        async with session.begin():
            member = await current_member(request, session)
            require_member_csrf(request, member, x_csrf_token)
            try:
                await bound_action(request, member, "review")
                result = await service().decide_review(
                    session,
                    actor_id=member.account_id,
                    product_id=product_id,
                    submission_id=payload.submission_id,
                    expected_version=payload.expected_version,
                    outcome=payload.outcome,
                    feedback=payload.feedback,
                    idempotency_key=idempotency_key,
                )
            except (
                ProductForbiddenError,
                ProductNotFoundError,
                ProductConflictError,
                ProductValidationError,
                ProductInfrastructureError,
                RateLimitExceeded,
                RateLimitUnavailable,
                SQLAlchemyError,
                RedisError,
            ) as error:
                raise map_error(error) from error
        return ReviewDecisionResponse(
            decision_id=result.decision.id,
            product_id=result.product_id,
            submission_id=result.decision.submission_id,
            status=cast(Literal["approved", "rejected", "changes_requested"], result.status),
            version=result.version,
        )

    @routes.post("/me/products", response_model=ProductStateResponse, status_code=201)
    async def create_draft(
        request: Request,
        session: DbSession,
        x_csrf_token: str | None = Header(default=None),
    ) -> ProductStateResponse:
        require_origin(request)
        async with session.begin():
            member = await current_member(request, session)
            require_member_csrf(request, member, x_csrf_token)
            try:
                await bound_action(request, member, "create")
                created = await service().create_draft(session, actor_id=member.account_id)
            except (
                ProductForbiddenError,
                ProductQuotaError,
                ProductInfrastructureError,
                RateLimitExceeded,
                RateLimitUnavailable,
                SQLAlchemyError,
                RedisError,
            ) as error:
                raise map_error(error) from error
        return ProductStateResponse(id=created.id, status="draft", version=created.version)

    @routes.patch("/me/products/{product_id}", response_model=ProductStateResponse)
    async def save_product(
        product_id: UUID,
        payload: ProductSaveInput,
        request: Request,
        session: DbSession,
        x_csrf_token: str | None = Header(default=None),
    ) -> ProductStateResponse:
        require_origin(request)
        async with session.begin():
            member = await current_member(request, session)
            require_member_csrf(request, member, x_csrf_token)
            try:
                await bound_action(request, member, "save")
                products = service()
                saved: ProductDraft | SubmittedProduct
                try:
                    saved = await products.save_draft(
                        session,
                        actor_id=member.account_id,
                        product_id=product_id,
                        expected_version=payload.version,
                        content=payload.changed_content(),
                        topic_names=payload.topic_names,
                    )
                except ProductNotFoundError:
                    saved = await products.save_pending(
                        session,
                        actor_id=member.account_id,
                        product_id=product_id,
                        expected_version=payload.version,
                        content=payload.changed_content(),
                        topic_names=payload.topic_names,
                    )
            except (
                ProductForbiddenError,
                ProductNotFoundError,
                ProductConflictError,
                ProductValidationError,
                ProductQuotaError,
                ProductInfrastructureError,
                RateLimitExceeded,
                RateLimitUnavailable,
                SQLAlchemyError,
                RedisError,
            ) as error:
                raise map_error(error) from error
        return ProductStateResponse(
            id=saved.id,
            status="draft" if isinstance(saved, ProductDraft) else "submitted",
            version=saved.version,
        )

    @routes.post("/me/products/{product_id}/submit", response_model=ProductSubmitResponse)
    async def submit_draft(
        product_id: UUID,
        payload: ProductVersionInput,
        request: Request,
        session: DbSession,
        x_csrf_token: str | None = Header(default=None),
    ) -> ProductSubmitResponse:
        require_origin(request)
        async with session.begin():
            member = await current_member(request, session)
            require_member_csrf(request, member, x_csrf_token)
            try:
                await bound_action(request, member, "submit")
                period = await service().submit_draft(
                    session,
                    actor_id=member.account_id,
                    product_id=product_id,
                    expected_version=payload.version,
                )
            except (
                ProductForbiddenError,
                ProductNotFoundError,
                ProductConflictError,
                ProductValidationError,
                ProductQuotaError,
                ProductInfrastructureError,
                RateLimitExceeded,
                RateLimitUnavailable,
                SQLAlchemyError,
                RedisError,
            ) as error:
                raise map_error(error) from error
        return ProductSubmitResponse(
            submission_id=period.id,
            product_id=period.product_id,
            product_version=period.product_version,
        )

    @routes.post("/me/products/{product_id}/withdraw", response_model=ProductStateResponse)
    async def withdraw_submission(
        product_id: UUID,
        payload: ProductWithdrawInput,
        request: Request,
        session: DbSession,
        x_csrf_token: str | None = Header(default=None),
    ) -> ProductStateResponse:
        require_origin(request)
        async with session.begin():
            member = await current_member(request, session)
            require_member_csrf(request, member, x_csrf_token)
            try:
                draft = await service().withdraw_submission(
                    session,
                    actor_id=member.account_id,
                    product_id=product_id,
                    submission_id=payload.submission_id,
                    expected_version=payload.version,
                )
            except (
                ProductForbiddenError,
                ProductNotFoundError,
                ProductConflictError,
                ProductInfrastructureError,
                SQLAlchemyError,
            ) as error:
                raise map_error(error) from error
        return ProductStateResponse(id=draft.id, status="draft", version=draft.version)

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
                await bound_action(request, member, "delete")
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
                RateLimitExceeded,
                RateLimitUnavailable,
                SQLAlchemyError,
                RedisError,
            ) as error:
                raise map_error(error) from error
        return Response(status_code=204)

    @routes.get("/products/{product_id}/assets/{asset_id}")
    async def get_private_product_asset(
        product_id: UUID,
        asset_id: UUID,
        request: Request,
        session: DbSession,
        expires: Annotated[int, Query(ge=0)],
        signature: Annotated[str, Query(min_length=64, max_length=64)],
    ) -> Response:
        session_secret = request.cookies.get(settings.session_cookie_name)
        if not session_secret:
            raise HTTPException(status_code=404, detail="product media unavailable")
        try:
            async with session.begin():
                member = await session_service.resolve(session, session_secret=session_secret)
                media = await service().read_private_asset(
                    session,
                    actor_id=member.account_id,
                    session_secret=session_secret,
                    product_id=product_id,
                    asset_id=asset_id,
                    expires_at=expires,
                    signature=signature,
                    storage=storage,
                )
        except UnauthenticatedError as error:
            raise HTTPException(status_code=404, detail="product media unavailable") from error
        except ProductNotFoundError as error:
            raise HTTPException(status_code=404, detail="product media unavailable") from error
        except (
            ProductInfrastructureError,
            ObjectOperationError,
            SQLAlchemyError,
            RedisError,
        ) as error:
            raise HTTPException(status_code=503, detail="service unavailable") from error
        return StreamingResponse(
            iter((media.body,)),
            media_type=media.media_type,
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @routes.get("/products/{product_id}/assets/{asset_id}/public")
    async def get_public_product_asset(
        product_id: UUID,
        asset_id: UUID,
        session: DbSession,
    ) -> Response:
        try:
            async with session.begin():
                media = await service().read_public_asset(
                    session,
                    product_id=product_id,
                    asset_id=asset_id,
                    storage=storage,
                )
        except ProductNotFoundError as error:
            raise HTTPException(status_code=404, detail="product media unavailable") from error
        except (ProductInfrastructureError, ObjectOperationError, SQLAlchemyError) as error:
            raise HTTPException(status_code=503, detail="service unavailable") from error
        return StreamingResponse(
            iter((media.body,)),
            media_type=media.media_type,
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

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
                await bound_action(request, member, "asset-intent")
                result = await service().create_asset_intent(
                    session,
                    actor_id=member.account_id,
                    product_id=product_id,
                    intent=payload,
                    storage=storage,
                )
            except ProductQuotaError as error:
                raise HTTPException(status_code=429, detail="upload limit reached") from error
            except (
                ProductForbiddenError,
                ProductNotFoundError,
                ProductConflictError,
                ProductInfrastructureError,
                ObjectOperationError,
                RateLimitExceeded,
                RateLimitUnavailable,
                SQLAlchemyError,
                RedisError,
            ) as error:
                raise map_error(error) from error
        authenticated_api = settings.storage_provider == "r2"
        return ProductAssetIntentResponse(
            asset_id=result.asset.id,
            upload_url=(
                f"/api/v1/me/products/{product_id}/assets/{result.asset.id}/content"
                if authenticated_api
                else result.upload.upload_url
            ),
            fields={} if authenticated_api else result.upload.fields,
            expires_in=result.upload.expires_in,
            upload_method="PUT" if authenticated_api else "POST",
            upload_transport=("authenticated_api" if authenticated_api else "storage_form"),
            upload_headers={"Content-Type": payload.content_type} if authenticated_api else {},
        )

    @routes.put(
        "/me/products/{product_id}/assets/{asset_id}/content",
        status_code=204,
    )
    async def transfer_asset(
        product_id: UUID,
        asset_id: UUID,
        request: Request,
        session: DbSession,
        x_csrf_token: str | None = Header(default=None),
    ) -> Response:
        require_origin(request)
        async with session.begin():
            member = await current_member(request, session)
            require_member_csrf(request, member, x_csrf_token)
            try:
                await bound_action(request, member, "asset-transfer")
                product_service = service()
                require_active_founder(
                    await product_service.member_access.current_account(
                        session, member.account_id, lock=False
                    )
                )
                product = await product_service.repository.get_owned_product(
                    session,
                    product_id=product_id,
                    founder_id=member.account_id,
                )
                if product is None:
                    raise ProductNotFoundError("product unavailable")
                require_editable_status(product.status)
                asset = await product_service.repository.get_asset(
                    session, product_id=product_id, asset_id=asset_id
                )
                if asset is None:
                    raise ProductNotFoundError("asset unavailable")
                if asset.state != "pending" or asset.expires_at is None:
                    raise ProductConflictError("asset upload is no longer pending")
                if asset.expires_at <= datetime.now(UTC):
                    raise ProductConflictError("asset upload is no longer pending")
                if not 1 <= asset.byte_count <= 5 * 1024 * 1024 or asset.media_type not in {
                    "image/jpeg",
                    "image/png",
                    "image/webp",
                }:
                    raise ProductConflictError("asset intent must be recreated")
                if request.headers.get("content-type") != asset.media_type:
                    raise HTTPException(status_code=415, detail="unsupported media type")
                byte_limit = asset.byte_count
            except ProductQuotaError as error:
                raise HTTPException(status_code=429, detail="upload limit reached") from error
            except (
                ProductForbiddenError,
                ProductNotFoundError,
                ProductConflictError,
                ProductInfrastructureError,
                RateLimitExceeded,
                RateLimitUnavailable,
                SQLAlchemyError,
                RedisError,
            ) as error:
                raise map_error(error) from error

        try:
            async with DEFAULT_UPLOAD_RECEIVER.receive(
                request.stream(), byte_limit=byte_limit
            ) as received:
                body = received.file.read()
        except UploadTooLarge as error:
            raise HTTPException(
                status_code=413, detail="upload exceeds its declared limit"
            ) from error
        except UploadOverloaded as error:
            raise HTTPException(status_code=429, detail="upload capacity is busy") from error
        except UploadTimedOut as error:
            raise HTTPException(status_code=408, detail="upload body timed out") from error
        except UploadReceiveError as error:
            raise HTTPException(
                status_code=400, detail="upload body could not be received"
            ) from error

        async with session.begin():
            member = await current_member(request, session)
            require_member_csrf(request, member, x_csrf_token)
            try:
                await service().transfer_asset(
                    session,
                    actor_id=member.account_id,
                    product_id=product_id,
                    asset_id=asset_id,
                    body=body,
                    content_type=request.headers.get("content-type", ""),
                    storage=storage,
                )
            except (
                ProductForbiddenError,
                ProductNotFoundError,
                ProductConflictError,
                ProductInfrastructureError,
                ProductValidationError,
                ObjectOperationError,
                RateLimitExceeded,
                RateLimitUnavailable,
                SQLAlchemyError,
                RedisError,
            ) as error:
                raise map_error(error) from error
        return Response(status_code=204)

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
                await bound_action(request, member, "asset-complete")
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
                RateLimitExceeded,
                RateLimitUnavailable,
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

    @routes.put(
        "/me/products/{product_id}/assets",
        response_model=ProductStateResponse,
    )
    async def attach_product_assets(
        product_id: UUID,
        payload: ProductAssetAttachmentInput,
        request: Request,
        session: DbSession,
        x_csrf_token: str | None = Header(default=None),
    ) -> ProductStateResponse:
        require_origin(request)
        async with session.begin():
            member = await current_member(request, session)
            require_member_csrf(request, member, x_csrf_token)
            try:
                await bound_action(request, member, "asset-attach")
                saved = await service().attach_assets(
                    session,
                    actor_id=member.account_id,
                    product_id=product_id,
                    expected_version=payload.version,
                    logo_asset_id=payload.logo_asset_id,
                    screenshot_asset_ids=tuple(payload.screenshot_asset_ids),
                )
            except (
                ProductForbiddenError,
                ProductNotFoundError,
                ProductConflictError,
                ProductInfrastructureError,
                RateLimitExceeded,
                RateLimitUnavailable,
                SQLAlchemyError,
                RedisError,
            ) as error:
                raise map_error(error) from error
        return ProductStateResponse(id=saved.id, status="draft", version=saved.version)

    return routes
