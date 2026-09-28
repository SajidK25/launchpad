"""Registration and email-verification domain services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.repository import AuthRepository
from app.modules.users.service import ProfileBootstrap
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.outbox import OutboxEvent, OutboxRepository
from app.shared.security.email import CanonicalEmail, canonicalize_email
from app.shared.security.passwords import hash_password
from app.shared.security.rate_limit import RateLimiter
from app.shared.security.tokens import digest_token, generate_token

CHALLENGE_TTL = timedelta(minutes=60)


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    """Safe public result; it intentionally does not disclose account existence."""

    accepted: bool = True


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Safe verification outcome for transport mapping."""

    verified: bool


class RegistrationService:
    """Create an account, private profile, challenge, and encrypted mail atomically."""

    def __init__(
        self,
        *,
        auth_repository: AuthRepository | None = None,
        profile_bootstrap: ProfileBootstrap | None = None,
        outbox_repository: OutboxRepository | None = None,
        payload_codec: EmailPayloadCodec,
        mail_web_origin: str,
        rate_limiter: RateLimiter | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.auth_repository = auth_repository or AuthRepository()
        self.profile_bootstrap = profile_bootstrap or ProfileBootstrap()
        self.outbox_repository = outbox_repository or OutboxRepository()
        self.payload_codec = payload_codec
        self.mail_web_origin = mail_web_origin.rstrip("/")
        self.rate_limiter = rate_limiter
        self.clock = clock or (lambda: datetime.now(UTC))

    async def register(
        self,
        session: AsyncSession,
        *,
        email: str,
        password: str,
        source_key: str = "unknown",
    ) -> RegistrationResult:
        identity = canonicalize_email(email)
        if self.rate_limiter is not None:
            await self.rate_limiter.check(address_key=identity.key, source_key=source_key)
        password_hash = hash_password(password)
        now = self.clock()
        if await self.auth_repository.find_account_by_email_key(session, identity.key) is not None:
            return RegistrationResult()
        try:
            async with session.begin_nested():
                account = await self.auth_repository.create_account(
                    session,
                    email_display=identity.delivery,
                    email_key=identity.key,
                    password_hash=password_hash,
                    now=now,
                )
        except IntegrityError:
            return RegistrationResult()
        await self.profile_bootstrap.create_private_profile(session, account.id)
        await self._issue_verification(session, account_id=account.id, identity=identity, now=now)
        return RegistrationResult()

    async def resend_verification(
        self, session: AsyncSession, *, account_id: UUID, source_key: str = "unknown"
    ) -> RegistrationResult:
        account = await self.auth_repository.find_account_by_id(session, account_id, lock=True)
        if account is None or account.verified_at is not None:
            return RegistrationResult()
        if self.rate_limiter is not None:
            await self.rate_limiter.check(address_key=account.email_key, source_key=source_key)
        await self._issue_verification(
            session,
            account_id=account.id,
            identity=CanonicalEmail(account.email_display, account.email_key),
            now=self.clock(),
        )
        return RegistrationResult()

    async def verify(
        self, session: AsyncSession, *, token: str, source_key: str = "unknown"
    ) -> VerificationResult:
        if self.rate_limiter is not None:
            await self.rate_limiter.check(
                address_key=f"verification:{digest_token(token).hex()}", source_key=source_key
            )
        account = await self.auth_repository.consume_verification(
            session, digest_token(token), now=self.clock()
        )
        return VerificationResult(verified=account is not None)

    async def _issue_verification(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
        identity: CanonicalEmail,
        now: datetime,
    ) -> None:
        raw_token = generate_token()
        expires_at = now + CHALLENGE_TTL
        await self.auth_repository.issue_verification(
            session,
            account_id=account_id,
            token_digest=digest_token(raw_token),
            issued_at=now,
            expires_at=expires_at,
        )
        key_id, encrypted_payload = self.payload_codec.encode(
            {
                "recipient": identity.delivery,
                "subject": "Verify your Launchpad account",
                "body": f"{self.mail_web_origin}/verify?token={raw_token}",
                "expires_at": expires_at.isoformat(),
            }
        )
        await self.outbox_repository.add(
            session,
            OutboxEvent(
                event_type="auth.verification_requested.v1",
                aggregate_id=account_id,
                key_id=key_id,
                encrypted_payload=encrypted_payload,
                available_at=now,
            ),
        )


class VerificationService:
    """Named façade for explicit email verification consumption."""

    def __init__(self, registration: RegistrationService) -> None:
        self.registration = registration

    async def consume(
        self, session: AsyncSession, *, token: str, source_key: str = "unknown"
    ) -> VerificationResult:
        return await self.registration.verify(session, token=token, source_key=source_key)


RESET_TTL = CHALLENGE_TTL


@dataclass(frozen=True, slots=True)
class PasswordResetResult:
    """Safe recovery result that never discloses whether an address exists."""

    accepted: bool = True
    reset: bool = False


class PasswordResetService:
    """Issue and consume one-use recovery links without authenticating the member."""

    def __init__(
        self,
        *,
        repository: AuthRepository | None = None,
        outbox_repository: OutboxRepository | None = None,
        payload_codec: EmailPayloadCodec,
        mail_web_origin: str,
        rate_limiter: RateLimiter | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository or AuthRepository()
        self.outbox_repository = outbox_repository or OutboxRepository()
        self.payload_codec = payload_codec
        self.mail_web_origin = mail_web_origin.rstrip("/")
        self.rate_limiter = rate_limiter
        self.clock = clock or (lambda: datetime.now(UTC))

    async def request(
        self, session: AsyncSession, *, email: str, source_key: str = "unknown"
    ) -> PasswordResetResult:
        identity = canonicalize_email(email)
        if self.rate_limiter is not None:
            await self.rate_limiter.check(address_key=identity.key, source_key=source_key)
        account = await self.repository.find_account_by_email_key(session, identity.key, lock=True)
        if account is None:
            # Keep unknown-address work comparable without retaining the result.
            hash_password("recovery timing padding")
            return PasswordResetResult()
        now = _utc(self.clock())
        raw_token = generate_token()
        expires_at = now + RESET_TTL
        await self.repository.issue_password_reset(
            session,
            account_id=account.id,
            token_digest=digest_token(raw_token),
            issued_at=now,
            expires_at=expires_at,
        )
        key_id, encrypted_payload = self.payload_codec.encode(
            {
                "recipient": account.email_display,
                "subject": "Reset your Launchpad password",
                "body": f"{self.mail_web_origin}/reset?token={raw_token}",
                "expires_at": expires_at.isoformat(),
            }
        )
        await self.outbox_repository.add(
            session,
            OutboxEvent(
                event_type="auth.password_reset_requested.v1",
                aggregate_id=account.id,
                key_id=key_id,
                encrypted_payload=encrypted_payload,
                available_at=now,
            ),
        )
        return PasswordResetResult()

    async def reset(
        self,
        session: AsyncSession,
        *,
        token: str,
        new_password: str,
        source_key: str = "unknown",
    ) -> PasswordResetResult:
        password_hash = hash_password(new_password)
        if self.rate_limiter is not None:
            await self.rate_limiter.check(
                address_key=f"reset:{digest_token(token).hex()}", source_key=source_key
            )
        now = _utc(self.clock())
        consumed = await self.repository.consume_password_reset(
            session, digest_token(token), now=now
        )
        if consumed is None:
            return PasswordResetResult(reset=False)
        _, account = consumed
        account.password_hash = password_hash
        account.session_epoch += 1
        account.updated_at = now
        await self.repository.revoke_all_sessions(session, account.id, now=now)
        key_id, encrypted_payload = self.payload_codec.encode(
            {
                "recipient": account.email_display,
                "subject": "Your Launchpad password was changed",
                "body": "Your password was changed. Sign in again on your devices.",
                "changed_at": now.isoformat(),
            }
        )
        await self.outbox_repository.add(
            session,
            OutboxEvent(
                event_type="auth.password_reset_completed.v1",
                aggregate_id=account.id,
                key_id=key_id,
                encrypted_payload=encrypted_payload,
                available_at=now,
            ),
        )
        return PasswordResetResult(reset=True)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
