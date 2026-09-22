from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.auth.models import Account, Session
from app.modules.auth.sessions import AuthenticationError, SessionService, UnauthenticatedError
from app.shared.security.passwords import hash_password


def test_unverified_sign_in_returns_restricted_member_context() -> None:
    async def run() -> None:
        account = Account(
            id=uuid4(),
            email_display="member@example.com",
            email_key="member@example.com",
            password_hash=hash_password("a secure password!"),
            session_epoch=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        record = Session(id=uuid4())
        repository: Any = SimpleNamespace(
            find_account_by_email_key=AsyncMock(return_value=account),
            create_session=AsyncMock(return_value=record),
        )
        db_session: Any = SimpleNamespace()
        result = await SessionService(repository=repository).sign_in(
            db_session, email="MEMBER@example.com", password="a secure password!"
        )
        assert result.member.verified is False
        assert result.member.can_publish is False
        assert result.session_secret

    asyncio.run(run())


def test_unknown_and_wrong_credentials_are_same_safe_error() -> None:
    async def run() -> None:
        repository: Any = SimpleNamespace(find_account_by_email_key=AsyncMock(return_value=None))
        service = SessionService(repository=repository)
        db_session: Any = SimpleNamespace()
        with pytest.raises(AuthenticationError) as unknown:
            await service.sign_in(
                db_session, email="none@example.com", password="a secure password!"
            )
        assert str(unknown.value) == "invalid credentials"
        account = SimpleNamespace(
            id=uuid4(),
            password_hash=hash_password("a secure password!"),
            session_epoch=0,
            verified_at=None,
        )
        repository.find_account_by_email_key.return_value = account
        with pytest.raises(AuthenticationError) as wrong:
            await service.sign_in(
                db_session, email="member@example.com", password="wrong password!"
            )
        assert str(wrong.value) == str(unknown.value)

    asyncio.run(run())


def test_expired_session_is_rejected_and_sign_out_revokes() -> None:
    async def run() -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        account = SimpleNamespace(id=uuid4(), session_epoch=0, verified_at=now)
        record = SimpleNamespace(
            id=uuid4(),
            revoked_at=None,
            session_epoch=0,
            idle_expires_at=now + timedelta(hours=1),
            absolute_expires_at=now + timedelta(days=1),
        )
        repository: Any = SimpleNamespace(
            find_session=AsyncMock(return_value=(record, account)),
            revoke_session=AsyncMock(),
        )
        service = SessionService(repository=repository, clock=lambda: now)
        db_session: Any = SimpleNamespace(flush=AsyncMock())
        member = await service.resolve(db_session, session_secret="secret")
        assert member.verified
        await service.sign_out(db_session, session_secret="secret")
        repository.revoke_session.assert_awaited_once()
        record.idle_expires_at = now - timedelta(seconds=1)
        with pytest.raises(UnauthenticatedError):
            await service.resolve(db_session, session_secret="secret")

    asyncio.run(run())
