from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.auth.service import PasswordResetService
from app.shared.security.passwords import hash_password, verify_password


def test_reset_request_is_generic_for_known_and_unknown_addresses() -> None:
    async def run() -> None:
        account = SimpleNamespace(
            id=uuid4(), email_display="member@example.com", email_key="member@example.com"
        )
        repository: Any = SimpleNamespace(
            find_account_by_email_key=AsyncMock(side_effect=[account, None]),
            issue_password_reset=AsyncMock(),
        )
        codec: Any = SimpleNamespace(encode=lambda payload: ("v1", b"encrypted"))
        outbox: Any = SimpleNamespace(add=AsyncMock())
        db_session: Any = SimpleNamespace()
        service = PasswordResetService(
            repository=repository,
            outbox_repository=outbox,
            payload_codec=codec,
            mail_web_origin="https://launchpad.example",
        )
        known = await service.request(db_session, email="member@example.com")
        unknown = await service.request(db_session, email="unknown@example.com")
        assert known == unknown
        repository.issue_password_reset.assert_awaited_once()

    asyncio.run(run())


def test_valid_reset_changes_password_and_revokes_all_sessions() -> None:
    async def run() -> None:
        account = SimpleNamespace(
            id=uuid4(),
            email_display="member@example.com",
            email_key="member@example.com",
            password_hash=hash_password("old password!"),
            verified_at=None,
            session_epoch=4,
            updated_at=datetime.now(UTC),
        )
        challenge = SimpleNamespace(
            account_id=account.id,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
            consumed_at=None,
            superseded_at=None,
        )
        repository: Any = SimpleNamespace(
            consume_password_reset=AsyncMock(return_value=(challenge, account)),
            revoke_all_sessions=AsyncMock(),
        )
        outbox: Any = SimpleNamespace(add=AsyncMock())
        codec: Any = SimpleNamespace(encode=lambda payload: ("v1", b"encrypted"))
        service = PasswordResetService(
            repository=repository,
            outbox_repository=outbox,
            payload_codec=codec,
            mail_web_origin="https://launchpad.example",
            clock=lambda: datetime.now(UTC),
        )
        db_session: Any = SimpleNamespace()
        result = await service.reset(db_session, token="token", new_password="new password!")
        assert result.reset
        assert verify_password("new password!", account.password_hash)
        assert account.verified_at is None
        assert account.session_epoch == 5
        repository.revoke_all_sessions.assert_awaited_once()
        outbox.add.assert_awaited_once()

    asyncio.run(run())


def test_invalid_password_does_not_consume_reset_challenge() -> None:
    async def run() -> None:
        repository: Any = SimpleNamespace(consume_password_reset=AsyncMock())
        codec: Any = SimpleNamespace()
        service = PasswordResetService(
            repository=repository,
            payload_codec=codec,
            mail_web_origin="https://launchpad.example",
        )
        db_session: Any = SimpleNamespace()
        with pytest.raises(ValueError):
            await service.reset(db_session, token="token", new_password="short")
        repository.consume_password_reset.assert_not_awaited()

    asyncio.run(run())
