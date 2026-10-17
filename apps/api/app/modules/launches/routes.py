"""Cookie-authenticated REST commands for founder launch bookings."""

import base64
from collections.abc import AsyncIterator, Callable
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.sessions import MemberContext, SessionService, UnauthenticatedError
from app.modules.auth.staff import AuthAccessService
from app.modules.launches.models import LaunchBooking
from app.modules.launches.schemas import LaunchBookingInput, LaunchBookingResponse
from app.modules.launches.service import LaunchBookingService
from app.modules.products.service import ProductService
from app.shared.config.settings import Settings
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.outbox import OutboxRepository
from app.shared.security.csrf import RequestSecurityError, require_csrf, validate_origin
from app.shared.security.rate_limit import RateLimiter, RateLimitExceeded, RateLimitUnavailable


def router(
    *,
    settings: Settings,
    database: Database,
    redis: Redis,
    service_factory: Callable[[], LaunchBookingService] | None = None,
) -> APIRouter:
    """Build owner-only launch commands with origin-bound CSRF and rate limits."""

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

    async def current_member(request: Request, session: AsyncSession) -> MemberContext:
        secret = request.cookies.get(settings.session_cookie_name)
        if not secret:
            raise HTTPException(status_code=401, detail="authentication required")
        try:
            return await session_service.resolve(session, session_secret=secret)
        except UnauthenticatedError as error:
            raise HTTPException(status_code=401, detail="authentication required") from error

    def service() -> LaunchBookingService:
        if service_factory is not None:
            return service_factory()
        member_access = AuthAccessService()
        products = ProductService(
            member_access=member_access,
            outbox_repository=OutboxRepository(),
            payload_codec=codec,
        )
        return LaunchBookingService(
            member_access=member_access,
            product_access=products,
            outbox_repository=OutboxRepository(),
            payload_codec=codec,
        )

    async def bound_action(request: Request, member: MemberContext, action: str) -> None:
        source = request.client.host if request.client else "unknown"
        await limiter.check(
            address_key=f"launch:{action}:account:{member.account_id.hex}",
            source_key=f"launch:{action}:source:{source}",
        )

    def map_error(error: Exception) -> HTTPException:
        from app.modules.launches.policies import (
            LaunchConflictError,
            LaunchForbiddenError,
            LaunchNotFoundError,
        )

        if isinstance(error, LaunchForbiddenError):
            return HTTPException(status_code=403, detail="launch access is forbidden")
        if isinstance(error, LaunchNotFoundError):
            return HTTPException(status_code=404, detail="launch product unavailable")
        if isinstance(error, (LaunchConflictError, ValueError)):
            return HTTPException(
                status_code=409, detail="launch request conflicts with current state"
            )
        if isinstance(error, RateLimitExceeded):
            return HTTPException(status_code=429, detail="try again later")
        if isinstance(
            error, (SQLAlchemyError, RedisError, RateLimitUnavailable, UnauthenticatedError)
        ):
            return HTTPException(status_code=503, detail="service unavailable")
        return HTTPException(status_code=400, detail="request could not be completed")

    async def authorize_write(
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

    def response(
        booking: LaunchBooking,
        *,
        product_status: Literal["scheduled", "approved"],
        product_version: int,
    ) -> LaunchBookingResponse:
        return LaunchBookingResponse(
            booking_id=booking.id,
            product_id=booking.product_id,
            state=cast(Literal["scheduled", "cancelled", "replaced"], booking.state),
            launch_date=booking.launch_date,
            launch_at=booking.launch_at,
            product_status=product_status,
            product_version=product_version,
        )

    @routes.post("/me/products/{product_id}/launch-booking", response_model=LaunchBookingResponse)
    async def create_booking(
        product_id: UUID,
        payload: LaunchBookingInput,
        request: Request,
        session: DbSession,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=255)
        ],
        x_csrf_token: str | None = Header(default=None),
    ) -> LaunchBookingResponse:
        async with session.begin():
            member = await authorize_write(request, session, x_csrf_token)
            try:
                await bound_action(request, member, "book")
                booking = await service().book(
                    session,
                    actor_id=member.account_id,
                    product_id=product_id,
                    launch_date=payload.launch_date,
                    expected_version=payload.expected_version,
                    idempotency_key=idempotency_key,
                )
            except Exception as error:
                raise map_error(error) from error
        return response(
            booking,
            product_status="scheduled",
            product_version=payload.expected_version + 1,
        )

    @routes.put("/me/products/{product_id}/launch-booking", response_model=LaunchBookingResponse)
    async def reschedule_booking(
        product_id: UUID,
        payload: LaunchBookingInput,
        request: Request,
        session: DbSession,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=255)
        ],
        x_csrf_token: str | None = Header(default=None),
    ) -> LaunchBookingResponse:
        async with session.begin():
            member = await authorize_write(request, session, x_csrf_token)
            try:
                await bound_action(request, member, "reschedule")
                booking = await service().reschedule(
                    session,
                    actor_id=member.account_id,
                    product_id=product_id,
                    launch_date=payload.launch_date,
                    expected_version=payload.expected_version,
                    idempotency_key=idempotency_key,
                )
            except Exception as error:
                raise map_error(error) from error
        return response(
            booking,
            product_status="scheduled",
            product_version=payload.expected_version + 1,
        )

    @routes.delete("/me/products/{product_id}/launch-booking", response_model=LaunchBookingResponse)
    async def cancel_booking(
        product_id: UUID,
        request: Request,
        session: DbSession,
        expected_version: Annotated[int, Query(ge=0)],
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=255)
        ],
        x_csrf_token: str | None = Header(default=None),
    ) -> LaunchBookingResponse:
        async with session.begin():
            member = await authorize_write(request, session, x_csrf_token)
            try:
                await bound_action(request, member, "cancel")
                booking = await service().cancel(
                    session,
                    actor_id=member.account_id,
                    product_id=product_id,
                    expected_version=expected_version,
                    idempotency_key=idempotency_key,
                )
            except Exception as error:
                raise map_error(error) from error
        return response(
            booking,
            product_status="approved",
            product_version=expected_version + 1,
        )

    return routes
