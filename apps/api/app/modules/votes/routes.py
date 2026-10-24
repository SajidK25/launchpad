"""Cookie-authenticated member vote commands with risk escalation."""

import asyncio
import base64
import hashlib
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

import httpx2
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, field_validator
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.sessions import MemberContext, SessionService, UnauthenticatedError
from app.modules.auth.staff import AccountState, AuthAccessService
from app.modules.products.service import ProductService
from app.modules.votes.policies import (
    VoteChallengeError,
    VoteConflictError,
    VoteForbiddenError,
    VoteInfrastructureError,
    VoteNotFoundError,
    VoteRateLimitError,
    require_vote_reviewer,
)
from app.modules.votes.schemas import VoteInput, VoteResponse
from app.modules.votes.service import VoteProductAccess, VoteReviewService, VoteService
from app.shared.config.settings import Settings
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.outbox import OutboxRepository
from app.shared.security.csrf import RequestSecurityError, require_csrf, validate_origin
from app.shared.security.rate_limit import RateLimitExceeded, RateLimitUnavailable


class VoteReviewDecisionInput(BaseModel):
    """Bounded reviewer outcome and rationale for one pending risk flag."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["cleared", "invalidated"]
    reason: str

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not 1 <= len(normalized) <= 2000:
            raise ValueError("reason must contain between 1 and 2000 characters")
        return normalized


class VoteReviewDecisionResponse(BaseModel):
    """Auditable result returned after the review transaction succeeds."""

    id: UUID
    flag_id: UUID
    reviewer_account_id: UUID
    outcome: Literal["cleared", "invalidated"]
    reason: str
    created_at: datetime


async def verify_turnstile(*, settings: Settings, token: str, remote_ip: str | None) -> bool:
    """Verify a high-risk action token server-side without logging secret material."""

    secret = settings.turnstile_secret_key
    if secret is None or not token.strip():
        return False
    try:
        async with httpx2.AsyncClient(timeout=4.0) as client:
            response = await client.post(
                str(settings.turnstile_site_verify_url),
                data={
                    "secret": secret.get_secret_value(),
                    "response": token,
                    **({"remoteip": remote_ip} if remote_ip else {}),
                },
            )
            response.raise_for_status()
            result = response.json()
    except (httpx2.HTTPError, ValueError):
        raise VoteChallengeError("risk challenge verification is unavailable") from None
    return isinstance(result, dict) and result.get("success") is True


def map_vote_error(error: Exception) -> HTTPException:
    """Map domain and dependency failures to stable, credential-free responses."""

    if isinstance(error, VoteForbiddenError):
        return HTTPException(status_code=403, detail="voting is unavailable for this account")
    if isinstance(error, VoteNotFoundError):
        return HTTPException(status_code=404, detail="product unavailable for voting")
    if isinstance(error, VoteChallengeError):
        return HTTPException(status_code=422, detail="complete the security check and retry")
    if isinstance(error, VoteRateLimitError):
        return HTTPException(status_code=429, detail="try again later")
    if isinstance(error, VoteConflictError):
        return HTTPException(status_code=409, detail="vote request conflicts with current state")
    if isinstance(error, RateLimitExceeded):
        return HTTPException(status_code=429, detail="try again later")
    if isinstance(
        error,
        (
            SQLAlchemyError,
            RedisError,
            RateLimitUnavailable,
            VoteInfrastructureError,
            UnauthenticatedError,
        ),
    ):
        return HTTPException(status_code=503, detail="service temporarily unavailable")
    return HTTPException(status_code=400, detail="vote request could not be completed")


def router(
    *,
    settings: Settings,
    database: Database,
    redis: Redis,
    service_factory: Callable[[], VoteService] | None = None,
    review_service_factory: Callable[[], VoteReviewService] | None = None,
    challenge_verifier: Callable[[str, str | None], object] | None = None,
) -> APIRouter:
    """Build origin-bound, CSRF-protected member vote commands."""

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

    def command_service() -> VoteService:
        if service_factory is not None:
            return service_factory()
        member_access = AuthAccessService()
        products = ProductService(
            member_access=member_access,
            outbox_repository=OutboxRepository(),
            payload_codec=codec,
        )
        return VoteService(
            member_access=member_access,
            product_access=cast(VoteProductAccess, products),
            outbox=OutboxRepository(),
            codec=codec,
            writes_enabled=lambda: settings.vote_writes_enabled,
        )

    def review_service() -> VoteReviewService:
        if review_service_factory is not None:
            return review_service_factory()
        member_access = AuthAccessService()
        products = ProductService(
            member_access=member_access,
            outbox_repository=OutboxRepository(),
            payload_codec=codec,
        )
        return VoteReviewService(
            member_access=member_access,
            product_access=cast(VoteProductAccess, products),
            outbox=OutboxRepository(),
            codec=codec,
        )

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

    async def risk_signal(*, member_id: UUID, request: Request) -> str | None:
        """Count configured short-lived velocity signals without retaining raw IP data."""

        source = request.client.host if request.client else None
        checks: list[tuple[str, str, int | None]] = [
            ("account_velocity", f"account:{member_id.hex}", settings.vote_account_velocity_limit),
            (
                "source_velocity",
                f"source:{hashlib.sha256((source or 'unknown').encode()).hexdigest()}",
                settings.vote_source_velocity_limit,
            ),
        ]
        signals: list[str] = []
        for signal, identity, limit in checks:
            if limit is None:
                continue
            try:
                count = await asyncio.to_thread(
                    _increment_velocity,
                    redis,
                    identity,
                    settings.vote_velocity_window_seconds,
                )
            except Exception as error:
                if isinstance(error, RedisError):
                    raise VoteInfrastructureError("risk limit unavailable") from None
                raise
            if count > limit:
                signals.append(signal)
        return signals[0] if signals else None

    async def require_challenge(*, token: str | None, remote_ip: str | None) -> bool:
        if not token:
            return False
        if challenge_verifier is not None:
            result = challenge_verifier(token, remote_ip)
            if asyncio.iscoroutine(result):
                return bool(await result)
            return bool(result)
        return await verify_turnstile(settings=settings, token=token, remote_ip=remote_ip)

    async def execute_command(
        *,
        command: str,
        member: MemberContext,
        product_id: UUID,
        idempotency_key: str,
        turnstile_token: str | None,
        session: AsyncSession,
        request: Request,
    ) -> VoteResponse:
        signal = await risk_signal(member_id=member.account_id, request=request)
        if signal is not None:
            verified = await require_challenge(
                token=turnstile_token,
                remote_ip=request.client.host if request.client else None,
            )
            if not verified:
                raise VoteChallengeError("required security check failed")
        service = command_service()
        method = service.cast if command == "cast" else service.withdraw
        result = await method(
            session,
            member_id=member.account_id,
            product_id=product_id,
            idempotency_key=idempotency_key,
            risk_signal=signal,
        )
        return VoteResponse(
            vote_id=result.vote_id,
            product_id=result.product_id,
            active=result.active,
            cast_at=result.cast_at,
            replayed=result.replayed,
        )

    @routes.post("/votes", response_model=VoteResponse, status_code=200)
    async def cast_vote(
        payload: VoteInput,
        request: Request,
        session: DbSession,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=255)
        ],
        x_csrf_token: str | None = Header(default=None),
        x_turnstile_token: str | None = Header(default=None),
    ) -> VoteResponse:
        async with session.begin():
            try:
                member = await authorize_write(request, session, x_csrf_token)
                return await execute_command(
                    command="cast",
                    member=member,
                    product_id=payload.product_id,
                    idempotency_key=idempotency_key,
                    turnstile_token=x_turnstile_token,
                    session=session,
                    request=request,
                )
            except HTTPException:
                raise
            except Exception as error:
                raise map_vote_error(error) from error

    @routes.delete("/votes/{product_id}", response_model=VoteResponse)
    async def withdraw_vote(
        product_id: UUID,
        request: Request,
        session: DbSession,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=255)
        ],
        x_csrf_token: str | None = Header(default=None),
        x_turnstile_token: str | None = Header(default=None),
    ) -> VoteResponse:
        async with session.begin():
            try:
                member = await authorize_write(request, session, x_csrf_token)
                return await execute_command(
                    command="withdraw",
                    member=member,
                    product_id=product_id,
                    idempotency_key=idempotency_key,
                    turnstile_token=x_turnstile_token,
                    session=session,
                    request=request,
                )
            except HTTPException:
                raise
            except Exception as error:
                raise map_vote_error(error) from error

    @routes.post(
        "/votes/reviews/{flag_id}/decision",
        response_model=VoteReviewDecisionResponse,
    )
    async def decide_vote_review(
        flag_id: UUID,
        payload: VoteReviewDecisionInput,
        request: Request,
        session: DbSession,
        x_csrf_token: str | None = Header(default=None),
    ) -> VoteReviewDecisionResponse:
        async with session.begin():
            try:
                member = await authorize_write(request, session, x_csrf_token)
                require_vote_reviewer(
                    AccountState(
                        member.account_id,
                        member.verified,
                        member.role,
                        member.suspended_at,
                    )
                )
                result = await review_service().decide(
                    session,
                    reviewer_id=member.account_id,
                    flag_id=flag_id,
                    outcome=payload.outcome,
                    reason=payload.reason,
                )
                return VoteReviewDecisionResponse(
                    id=result.id,
                    flag_id=result.flag_id,
                    reviewer_account_id=result.reviewer_account_id,
                    outcome=cast(Literal["cleared", "invalidated"], result.outcome),
                    reason=result.reason,
                    created_at=result.created_at,
                )
            except HTTPException:
                raise
            except Exception as error:
                raise map_vote_error(error) from error

    return routes


def _increment_velocity(redis: Redis, identity: str, window_seconds: int) -> int:
    key = f"launchpad:vote:velocity:{identity}"
    count = int(redis.incr(key))
    if count == 1 and not redis.expire(key, window_seconds):
        raise RedisError("velocity expiry unavailable")
    return count
