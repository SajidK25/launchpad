"""Sign-in, sign-out, and PostgreSQL-backed member session resolution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.repository import AuthRepository
from app.shared.security.csrf import derive_csrf_token, verify_csrf_token
from app.shared.security.email import canonicalize_email
from app.shared.security.passwords import verify_password
from app.shared.security.rate_limit import RateLimiter
from app.shared.security.tokens import digest_token, generate_token


class AuthenticationError(ValueError):
    """Safe generic authentication failure."""


class UnauthenticatedError(AuthenticationError):
    """No valid, unrevoked session was supplied."""


@dataclass(frozen=True, slots=True)
class MemberContext:
    account_id: UUID
    verified: bool
    session_id: UUID
    csrf_digest: bytes = b""
    email_display: str = ""

    @property
    def can_publish(self) -> bool:
        return self.verified


@dataclass(frozen=True, slots=True)
class SignInResult:
    session_secret: str
    csrf_token: str
    csrf_digest: bytes
    member: MemberContext


class SessionService:
    """Own session lifecycle and keep account state authoritative in PostgreSQL."""

    def __init__(
        self,
        *,
        repository: AuthRepository | None = None,
        idle_seconds: int = 86_400,
        absolute_seconds: int = 604_800,
        activity_write_interval_seconds: int = 300,
        rate_limiter: RateLimiter | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository or AuthRepository()
        self.idle = timedelta(seconds=idle_seconds)
        self.absolute = timedelta(seconds=absolute_seconds)
        self.activity_write_interval = timedelta(seconds=activity_write_interval_seconds)
        self.rate_limiter = rate_limiter
        self.clock = clock or (lambda: datetime.now(UTC))

    async def sign_in(
        self,
        session: AsyncSession,
        *,
        email: str,
        password: str,
        source_key: str = "unknown",
    ) -> SignInResult:
        try:
            identity = canonicalize_email(email)
        except ValueError as exc:
            raise AuthenticationError("invalid credentials") from exc
        if self.rate_limiter is not None:
            await self.rate_limiter.check(address_key=identity.key, source_key=source_key)
        account = await self.repository.find_account_by_email_key(session, identity.key, lock=True)
        if account is None:
            verify_password(password, DUMMY_PASSWORD_HASH)
            raise AuthenticationError("invalid credentials")
        if not verify_password(password, account.password_hash):
            raise AuthenticationError("invalid credentials")
        now = _utc(self.clock())
        secret = generate_token()
        csrf = derive_csrf_token(secret)
        csrf_digest = digest_token(csrf)
        record = await self.repository.create_session(
            session,
            account_id=account.id,
            secret_digest=digest_token(secret),
            session_epoch=account.session_epoch,
            now=now,
            idle_expires_at=min(now + self.idle, now + self.absolute),
            absolute_expires_at=now + self.absolute,
        )
        return SignInResult(
            session_secret=secret,
            csrf_token=csrf,
            csrf_digest=csrf_digest,
            member=MemberContext(
                account.id,
                account.verified_at is not None,
                record.id,
                csrf_digest,
                account.email_display,
            ),
        )

    async def resolve(self, session: AsyncSession, *, session_secret: str) -> MemberContext:
        now = _utc(self.clock())
        row = await self.repository.find_session(session, digest_token(session_secret), lock=True)
        if row is None:
            raise UnauthenticatedError("authentication required")
        record, account = row
        if (
            record.revoked_at is not None
            or record.session_epoch != account.session_epoch
            or now >= record.idle_expires_at
            or now >= record.absolute_expires_at
        ):
            raise UnauthenticatedError("authentication required")
        if now - record.last_seen_at >= self.activity_write_interval:
            record.last_seen_at = now
            record.idle_expires_at = min(now + self.idle, record.absolute_expires_at)
            await session.flush()
        return MemberContext(
            account.id,
            account.verified_at is not None,
            record.id,
            digest_token(derive_csrf_token(session_secret)),
            getattr(account, "email_display", ""),
        )

    async def sign_out(self, session: AsyncSession, *, session_secret: str) -> None:
        await self.repository.revoke_session(
            session, digest_token(session_secret), now=_utc(self.clock())
        )

    @staticmethod
    def verify_csrf(*, token: str, expected_digest: bytes) -> None:
        if not verify_csrf_token(token, expected_digest):
            raise AuthenticationError("invalid csrf token")


DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$9Y+0hXCE8uD6TKRd3/TR1Q$"
    "QO814anZ0qUFdnkySWUKuOGBnQgCHCibWflkCav5AT0"
)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
