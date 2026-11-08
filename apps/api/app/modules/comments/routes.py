"""Thin secured REST transport for discussion commands and auxiliary reads."""

import hashlib
import math
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.sessions import MemberContext, SessionService, UnauthenticatedError
from app.modules.comments.live import CommentLiveTicketService
from app.modules.comments.policies import (
    CommentConflictError,
    CommentForbiddenError,
    CommentInfrastructureError,
    CommentNotFoundError,
    CommentRateLimitError,
    CommentValidationError,
)
from app.modules.comments.schemas import (
    CommentCreateInput,
    CommentLiveTicketResponse,
    CommentResponse,
)
from app.modules.comments.service import (
    CommentCommandResult,
    CommentService,
    ProductDiscussionAccess,
)
from app.modules.users.comment_attribution import CommentAuthorPhoto
from app.shared.config.settings import Settings
from app.shared.security.csrf import RequestSecurityError, require_csrf, validate_origin
from app.shared.security.rate_limit import RateLimiter, RateLimitExceeded, RateLimitUnavailable


class CommentRouteSessionFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]: ...


class CommentSessionResolver(Protocol):
    async def resolve(self, session: AsyncSession, *, session_secret: str) -> MemberContext: ...


class CommentPhotoAccess(Protocol):
    async def read_photo(
        self, session: AsyncSession, account_id: UUID
    ) -> CommentAuthorPhoto | None: ...


class CommentRateLimitRedis(Protocol):
    def incr(self, key: str) -> int: ...

    def expire(self, key: str, seconds: int) -> bool: ...


def map_comment_error(error: Exception) -> HTTPException:
    """Map domain failures to stable responses without content or private facts."""

    if isinstance(error, CommentValidationError):
        return HTTPException(status_code=400, detail="invalid discussion request")
    if isinstance(error, CommentForbiddenError):
        return HTTPException(status_code=403, detail="discussion posting is unavailable")
    if isinstance(error, CommentNotFoundError):
        return HTTPException(status_code=404, detail="discussion unavailable")
    if isinstance(error, CommentConflictError):
        return HTTPException(status_code=409, detail="discussion request conflicts")
    if isinstance(error, CommentRateLimitError):
        retry_after = max(
            1,
            math.ceil((error.retry_at - datetime.now(UTC)).total_seconds()),
        )
        return HTTPException(
            status_code=429,
            detail="try again later",
            headers={"Retry-After": str(retry_after)},
        )
    if isinstance(error, (CommentInfrastructureError, SQLAlchemyError)):
        return HTTPException(status_code=503, detail="service temporarily unavailable")
    return HTTPException(status_code=400, detail="discussion request could not be completed")


def router(
    *,
    settings: Settings,
    session_factory: CommentRouteSessionFactory,
    redis: CommentRateLimitRedis,
    comment_service_factory: Callable[[], CommentService],
    ticket_service: CommentLiveTicketService,
    photo_access: CommentPhotoAccess,
    product_access: ProductDiscussionAccess,
    session_service: CommentSessionResolver | None = None,
) -> APIRouter:
    """Build the comments-owned REST surface from named feature boundaries."""

    routes = APIRouter(prefix="/api/v1")
    sessions = session_service or SessionService()
    ticket_limiter = RateLimiter(redis, limit=60, window_seconds=60)

    async def db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    DbSession = Annotated[AsyncSession, Depends(db_session)]

    async def current_member(request: Request, session: AsyncSession) -> MemberContext:
        secret = request.cookies.get(settings.session_cookie_name)
        if not secret:
            raise HTTPException(status_code=401, detail="authentication required")
        try:
            return await sessions.resolve(session, session_secret=secret)
        except UnauthenticatedError as error:
            raise HTTPException(status_code=401, detail="authentication required") from error

    async def authorize_command(
        request: Request, session: AsyncSession, csrf_token: str | None
    ) -> MemberContext:
        try:
            validate_origin(request.headers.get("origin"), settings.trusted_web_origins)
        except RequestSecurityError as error:
            raise HTTPException(status_code=403, detail="request rejected") from error
        member = await current_member(request, session)
        try:
            require_csrf(
                origin=request.headers.get("origin"),
                trusted_origin=settings.trusted_web_origins,
                token=csrf_token,
                expected_digest=member.csrf_digest,
            )
        except RequestSecurityError as error:
            raise HTTPException(status_code=403, detail="request rejected") from error
        return member

    async def execute_command(
        *,
        payload: CommentCreateInput,
        request: Request,
        response: Response,
        session: AsyncSession,
        product_id: UUID,
        parent_id: UUID | None,
        idempotency_key: str | None,
        csrf_token: str | None,
    ) -> CommentResponse:
        try:
            async with session.begin():
                member = await authorize_command(request, session, csrf_token)
                service = comment_service_factory()
                if parent_id is None:
                    result = await service.create_root(
                        session,
                        author_id=member.account_id,
                        product_id=product_id,
                        body=payload.body,
                        idempotency_key=idempotency_key or "",
                    )
                else:
                    result = await service.create_reply(
                        session,
                        author_id=member.account_id,
                        product_id=product_id,
                        parent_id=parent_id,
                        body=payload.body,
                        idempotency_key=idempotency_key or "",
                    )
        except HTTPException:
            raise
        except Exception as error:
            raise map_comment_error(error) from error
        response.status_code = 200 if result.replayed else 201
        response.headers["Cache-Control"] = "no-store"
        return _comment_response(result)

    @routes.post(
        "/products/{product_id}/comments",
        response_model=CommentResponse,
        status_code=201,
    )
    async def create_comment(
        product_id: UUID,
        payload: CommentCreateInput,
        request: Request,
        response: Response,
        session: DbSession,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        x_csrf_token: str | None = Header(default=None),
    ) -> CommentResponse:
        return await execute_command(
            payload=payload,
            request=request,
            response=response,
            session=session,
            product_id=product_id,
            parent_id=None,
            idempotency_key=idempotency_key,
            csrf_token=x_csrf_token,
        )

    @routes.post(
        "/products/{product_id}/comments/{parent_id}/replies",
        response_model=CommentResponse,
        status_code=201,
    )
    async def create_reply(
        product_id: UUID,
        parent_id: UUID,
        payload: CommentCreateInput,
        request: Request,
        response: Response,
        session: DbSession,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        x_csrf_token: str | None = Header(default=None),
    ) -> CommentResponse:
        return await execute_command(
            payload=payload,
            request=request,
            response=response,
            session=session,
            product_id=product_id,
            parent_id=parent_id,
            idempotency_key=idempotency_key,
            csrf_token=x_csrf_token,
        )

    @routes.post(
        "/products/{product_id}/comments/live-ticket",
        response_model=CommentLiveTicketResponse,
    )
    async def issue_live_ticket(
        product_id: UUID, request: Request, response: Response, session: DbSession
    ) -> CommentLiveTicketResponse:
        try:
            validate_origin(request.headers.get("origin"), settings.trusted_web_origins)
            source = request.client.host if request.client is not None else "unknown"
            await ticket_limiter.check(
                address_key=f"comment-live:product:{product_id.hex}",
                source_key=(f"comment-live:source:{hashlib.sha256(source.encode()).hexdigest()}"),
            )
            if (
                await product_access.discussion_context(session, product_id=product_id, lock=False)
                is None
            ):
                raise CommentNotFoundError("discussion unavailable")
            ticket = ticket_service.issue(product_id)
            response.headers["Cache-Control"] = "no-store"
            return CommentLiveTicketResponse(ticket=ticket.token, expires_at=ticket.expires_at)
        except RequestSecurityError as error:
            raise HTTPException(status_code=403, detail="request rejected") from error
        except RateLimitExceeded as error:
            raise HTTPException(
                status_code=429,
                detail="try again later",
                headers={"Retry-After": "60"},
            ) from error
        except RateLimitUnavailable as error:
            raise HTTPException(
                status_code=503, detail="service temporarily unavailable"
            ) from error
        except CommentNotFoundError as error:
            raise map_comment_error(error) from error
        except SQLAlchemyError as error:
            raise map_comment_error(error) from error
        except Exception as error:
            raise HTTPException(
                status_code=503, detail="service temporarily unavailable"
            ) from error

    @routes.get("/products/{product_id}/comment-authors/{account_id}/photo")
    async def comment_author_photo(
        product_id: UUID, account_id: UUID, session: DbSession
    ) -> StreamingResponse:
        service = comment_service_factory()
        try:
            if await product_access.discussion_context(
                session, product_id=product_id, lock=False
            ) is None or not await service.has_visible_entry_on_product(
                session, product_id=product_id, account_id=account_id
            ):
                raise CommentNotFoundError("discussion attribution unavailable")
            photo = await photo_access.read_photo(session, account_id)
            if photo is None:
                raise CommentNotFoundError("discussion attribution unavailable")
        except CommentNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="discussion attribution unavailable"
            ) from error
        except SQLAlchemyError as error:
            raise HTTPException(
                status_code=503, detail="service temporarily unavailable"
            ) from error
        except Exception as error:
            raise HTTPException(
                status_code=503, detail="service temporarily unavailable"
            ) from error
        image = StreamingResponse(iter((photo.body,)), media_type=photo.media_type)
        image.headers["Cache-Control"] = "no-store"
        image.headers["X-Content-Type-Options"] = "nosniff"
        return image

    return routes


def _comment_response(result: CommentCommandResult) -> CommentResponse:
    entry = result.entry
    return CommentResponse(
        id=entry.id,
        product_id=entry.product_id,
        parent_id=entry.parent_id,
        body=entry.body,
        created_at=entry.created_at,
        replayed=result.replayed,
    )
