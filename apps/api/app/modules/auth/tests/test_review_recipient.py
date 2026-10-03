"""The auth feature exposes only the current verified recipient address."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.staff import AuthAccessService


def test_verified_recipient_lookup_returns_current_address_and_never_another_account() -> None:
    async def verify() -> None:
        owner_id, other_id = uuid4(), uuid4()
        owner = SimpleNamespace(
            id=owner_id, email_display="current@example.test", verified_at=datetime.now(UTC)
        )
        other = SimpleNamespace(
            id=other_id, email_display="other@example.test", verified_at=datetime.now(UTC)
        )
        repository: Any = SimpleNamespace(
            find_account_by_id=AsyncMock(side_effect=[owner, other, None])
        )
        access = AuthAccessService(repository=repository)
        session = cast(AsyncSession, object())

        assert await access.verified_recipient_email(session, owner_id) == "current@example.test"
        assert await access.verified_recipient_email(session, other_id) == "other@example.test"
        assert await access.verified_recipient_email(session, uuid4()) is None
        assert repository.find_account_by_id.await_count == 3

    asyncio.run(verify())


def test_unverified_account_has_no_delivery_recipient() -> None:
    async def verify() -> None:
        owner_id = uuid4()
        account = SimpleNamespace(
            id=owner_id, email_display="pending@example.test", verified_at=None
        )
        repository: Any = SimpleNamespace(find_account_by_id=AsyncMock(return_value=account))

        assert (
            await AuthAccessService(repository=repository).verified_recipient_email(
                cast(AsyncSession, object()), owner_id
            )
            is None
        )

    asyncio.run(verify())
