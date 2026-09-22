"""Account and verification persistence with row-lock boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import select
from uuid6 import uuid7

from app.modules.auth.models import Account, EmailVerification


class AuthRepository:
    """Repository for auth-owned account and verification rows."""

    async def find_account_by_email_key(
        self, session: AsyncSession, email_key: str, *, lock: bool = False
    ) -> Account | None:
        query = select(Account).where(Account.email_key == email_key)
        if lock:
            query = query.with_for_update()
        return cast(Account | None, await session.scalar(query))

    async def find_account_by_id(
        self, session: AsyncSession, account_id: UUID, *, lock: bool = False
    ) -> Account | None:
        query = select(Account).where(Account.id == account_id)
        if lock:
            query = query.with_for_update()
        return cast(Account | None, await session.scalar(query))

    async def create_account(
        self,
        session: AsyncSession,
        *,
        email_display: str,
        email_key: str,
        password_hash: str,
        now: datetime,
    ) -> Account:
        account = Account(
            id=uuid7(),
            email_display=email_display,
            email_key=email_key,
            password_hash=password_hash,
            created_at=_utc(now),
            updated_at=_utc(now),
        )
        session.add(account)
        await session.flush()
        return account

    async def supersede_verifications(
        self, session: AsyncSession, account_id: UUID, *, now: datetime
    ) -> None:
        await session.execute(
            update(EmailVerification)
            .where(
                EmailVerification.account_id == account_id,
                EmailVerification.consumed_at.is_(None),
                EmailVerification.superseded_at.is_(None),
            )
            .values(superseded_at=_utc(now))
        )

    async def issue_verification(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
        token_digest: bytes,
        issued_at: datetime,
        expires_at: datetime,
    ) -> EmailVerification:
        await self.supersede_verifications(session, account_id, now=issued_at)
        challenge = EmailVerification(
            id=uuid7(),
            account_id=account_id,
            token_digest=token_digest,
            issued_at=_utc(issued_at),
            expires_at=_utc(expires_at),
        )
        session.add(challenge)
        await session.flush()
        return challenge

    async def consume_verification(
        self, session: AsyncSession, token_digest: bytes, *, now: datetime
    ) -> Account | None:
        current = _utc(now)
        challenge = await session.scalar(
            select(EmailVerification)
            .where(
                EmailVerification.token_digest == token_digest,
                EmailVerification.consumed_at.is_(None),
                EmailVerification.superseded_at.is_(None),
            )
            .with_for_update()
        )
        if challenge is None or challenge.expires_at <= current:
            return None
        account = await session.scalar(
            select(Account).where(Account.id == challenge.account_id).with_for_update()
        )
        if account is None:
            return None
        challenge.consumed_at = current
        if account.verified_at is None:
            account.verified_at = current
            account.updated_at = current
        await session.flush()
        return account


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
