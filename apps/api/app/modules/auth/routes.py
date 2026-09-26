"""Thin REST transport for the authentication domain services."""

import base64
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.schemas import (
    AcceptedResponse,
    EmailPasswordRequest,
    EmailRequest,
    LoginResponse,
    PasswordResetRequest,
    SessionResponse,
    TokenRequest,
)
from app.modules.auth.service import (
    PasswordResetService,
    RegistrationService,
    VerificationService,
)
from app.modules.auth.sessions import (
    AuthenticationError,
    MemberContext,
    SessionService,
    UnauthenticatedError,
)
from app.shared.config.settings import Settings
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.security.csrf import (
    RequestSecurityError,
    derive_csrf_token,
    require_csrf,
    validate_origin,
)
from app.shared.security.rate_limit import RateLimiter, RateLimitExceeded, RateLimitUnavailable


def router(
    *,
    settings: Settings,
    database: Database,
    redis: Redis,
) -> APIRouter:
    """Build auth routes with resources owned by the application factory."""

    if settings.outbox_key is None or settings.outbox_key_id is None:
        raise RuntimeError("Outbox encryption configuration is required.")
    if settings.mail_web_origin is None:
        raise RuntimeError("Mail web origin configuration is required.")
    codec = EmailPayloadCodec(
        {settings.outbox_key_id: base64.b64decode(settings.outbox_key.get_secret_value())},
        settings.outbox_key_id,
    )
    limiter = RateLimiter(redis)
    registration = RegistrationService(
        payload_codec=codec,
        mail_web_origin=str(settings.mail_web_origin),
        rate_limiter=limiter,
    )
    sessions = SessionService(
        idle_seconds=settings.session_idle_seconds,
        absolute_seconds=settings.session_absolute_seconds,
        rate_limiter=limiter,
    )
    recovery = PasswordResetService(
        payload_codec=codec,
        mail_web_origin=str(settings.mail_web_origin),
        rate_limiter=limiter,
    )
    verification = VerificationService(registration)
    session_factory = async_sessionmaker(database.engine, expire_on_commit=False)
    routes = APIRouter(prefix="/api/v1/auth")

    async def db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    DbSession = Annotated[AsyncSession, Depends(db_session)]

    def origin(request: Request) -> None:
        try:
            validate_origin(request.headers.get("origin"), settings.trusted_web_origins)
        except RequestSecurityError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="request rejected"
            ) from exc

    async def current_member(request: Request, session: AsyncSession) -> tuple[str, MemberContext]:
        secret = request.cookies.get(settings.session_cookie_name)
        if not secret:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required"
            )
        try:
            return secret, await sessions.resolve(session, session_secret=secret)
        except UnauthenticatedError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required"
            ) from exc

    def map_error(error: Exception) -> HTTPException:
        if isinstance(error, RateLimitExceeded):
            return HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="try again later"
            )
        if isinstance(error, RateLimitUnavailable):
            return HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="service unavailable"
            )
        if isinstance(error, AuthenticationError):
            return HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
            )
        if isinstance(error, (SQLAlchemyError, RedisError)):
            return HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="service unavailable",
            )
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="request could not be completed"
        )

    @routes.post("/register", response_model=AcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
    async def register(
        payload: EmailPasswordRequest, request: Request, session: DbSession
    ) -> AcceptedResponse:
        origin(request)
        try:
            async with session.begin():
                await registration.register(
                    session,
                    email=payload.email,
                    password=payload.password,
                    source_key=request.client.host if request.client else "unknown",
                )
        except (RateLimitExceeded, RateLimitUnavailable, SQLAlchemyError, RedisError) as exc:
            raise map_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="invalid registration",
            ) from exc
        return AcceptedResponse()

    @routes.post("/login", response_model=LoginResponse)
    async def login(
        payload: EmailPasswordRequest, request: Request, response: Response, session: DbSession
    ) -> LoginResponse:
        origin(request)
        try:
            async with session.begin():
                result = await sessions.sign_in(
                    session,
                    email=payload.email,
                    password=payload.password,
                    source_key=request.client.host if request.client else "unknown",
                )
        except (
            AuthenticationError,
            RateLimitExceeded,
            RateLimitUnavailable,
            SQLAlchemyError,
            RedisError,
        ) as exc:
            raise map_error(exc) from exc
        response.set_cookie(
            settings.session_cookie_name,
            result.session_secret,
            httponly=True,
            secure=settings.session_cookie_secure,
            samesite=settings.session_cookie_samesite,
            path="/",
        )
        return LoginResponse(
            account_id=result.member.account_id,
            verified=result.member.verified,
            csrf_token=result.csrf_token,
        )

    @routes.get("/session", response_model=SessionResponse)
    async def current(request: Request, response: Response, session: DbSession) -> SessionResponse:
        try:
            async with session.begin():
                secret, member = await current_member(request, session)
        except (SQLAlchemyError, RedisError) as exc:
            raise map_error(exc) from exc
        response.headers["Cache-Control"] = "no-store"
        return SessionResponse(
            account_id=member.account_id,
            verified=member.verified,
            csrf_token=derive_csrf_token(secret),
        )

    @routes.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(
        request: Request,
        response: Response,
        session: DbSession,
        x_csrf_token: str | None = Header(default=None),
    ) -> None:
        origin(request)
        try:
            async with session.begin():
                secret, member = await current_member(request, session)
                require_csrf(
                    origin=request.headers.get("origin"),
                    trusted_origin=settings.trusted_web_origins,
                    token=x_csrf_token,
                    expected_digest=member.csrf_digest,
                )
                await sessions.sign_out(session, session_secret=secret)
        except RequestSecurityError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="request rejected"
            ) from exc
        except (SQLAlchemyError, RedisError) as exc:
            raise map_error(exc) from exc
        response.delete_cookie(
            settings.session_cookie_name,
            path="/",
            secure=settings.session_cookie_secure,
            samesite=settings.session_cookie_samesite,
        )

    @routes.post(
        "/verification-requests",
        response_model=AcceptedResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def verification_request(
        request: Request, session: DbSession, x_csrf_token: str | None = Header(default=None)
    ) -> AcceptedResponse:
        origin(request)
        try:
            async with session.begin():
                _, member = await current_member(request, session)
                require_csrf(
                    origin=request.headers.get("origin"),
                    trusted_origin=settings.trusted_web_origins,
                    token=x_csrf_token,
                    expected_digest=member.csrf_digest,
                )
                await registration.resend_verification(
                    session,
                    account_id=member.account_id,
                    source_key=request.client.host if request.client else "unknown",
                )
        except (
            RequestSecurityError,
            RateLimitExceeded,
            RateLimitUnavailable,
            SQLAlchemyError,
            RedisError,
        ) as exc:
            if isinstance(exc, RequestSecurityError):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="request rejected"
                ) from exc
            raise map_error(exc) from exc
        return AcceptedResponse()

    @routes.post("/verify", response_model=AcceptedResponse)
    async def verify(
        payload: TokenRequest, request: Request, session: DbSession
    ) -> AcceptedResponse:
        origin(request)
        try:
            async with session.begin():
                result = await verification.consume(
                    session,
                    token=payload.token,
                    source_key=request.client.host if request.client else "unknown",
                )
        except (RateLimitExceeded, RateLimitUnavailable, SQLAlchemyError, RedisError) as exc:
            raise map_error(exc) from exc
        if not result.verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="verification link unavailable"
            )
        return AcceptedResponse()

    @routes.post(
        "/password-reset-requests",
        response_model=AcceptedResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def password_reset_request(
        payload: EmailRequest, request: Request, session: DbSession
    ) -> AcceptedResponse:
        origin(request)
        try:
            async with session.begin():
                await recovery.request(
                    session,
                    email=payload.email,
                    source_key=request.client.host if request.client else "unknown",
                )
        except (RateLimitExceeded, RateLimitUnavailable, SQLAlchemyError, RedisError) as exc:
            raise map_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="invalid email",
            ) from exc
        return AcceptedResponse()

    @routes.post("/password-resets", status_code=status.HTTP_204_NO_CONTENT)
    async def password_reset(
        payload: PasswordResetRequest, request: Request, session: DbSession
    ) -> None:
        origin(request)
        try:
            async with session.begin():
                result = await recovery.reset(
                    session,
                    token=payload.token,
                    new_password=payload.new_password,
                    source_key=request.client.host if request.client else "unknown",
                )
        except (RateLimitExceeded, RateLimitUnavailable, SQLAlchemyError, RedisError) as exc:
            raise map_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid password"
            ) from exc
        if not result.reset:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="reset link unavailable"
            )

    return routes
