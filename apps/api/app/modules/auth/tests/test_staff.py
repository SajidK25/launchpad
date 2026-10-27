"""Live account-state and named auth access tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.modules.auth.repository import AuthRepository
from app.modules.auth.sessions import SessionService
from app.modules.auth.staff import (
    AuthAccessService,
    StaffManagementError,
    StaffManagementService,
)


def test_existing_session_reflects_current_role_and_suspension() -> None:
    """A session reads current account authorization, not login-time claims."""

    async def verify() -> None:
        now = datetime.now(UTC)
        account = SimpleNamespace(
            id=uuid4(),
            session_epoch=0,
            verified_at=now,
            email_display="a@example.test",
            role="member",
            suspended_at=None,
        )
        record = SimpleNamespace(
            id=uuid4(),
            revoked_at=None,
            session_epoch=0,
            last_seen_at=now,
            idle_expires_at=now + timedelta(hours=1),
            absolute_expires_at=now + timedelta(days=1),
        )
        repository: Any = SimpleNamespace(find_session=AsyncMock(return_value=(record, account)))
        service = SessionService(repository=repository, clock=lambda: now)
        session: Any = SimpleNamespace(flush=AsyncMock())
        first = await service.resolve(session, session_secret="same-browser-session")
        assert first.role == "member"
        assert first.suspended_at is None
        account.role = "reviewer"
        account.suspended_at = now
        second = await service.resolve(session, session_secret="same-browser-session")
        assert second.role == "reviewer"
        assert second.suspended_at == now
        assert second.session_id == first.session_id

    asyncio.run(verify())


def test_named_access_locks_current_account_for_quota_commands() -> None:
    async def verify() -> None:
        account_id = uuid4()
        now = datetime.now(UTC)
        account = SimpleNamespace(id=account_id, verified_at=now, role="member", suspended_at=None)
        repository: Any = SimpleNamespace(find_account_by_id=AsyncMock(return_value=account))
        session: Any = SimpleNamespace()
        access = AuthAccessService(repository=repository)
        state = await access.current_account(session, account_id, lock=True)
        assert state is not None
        assert state.account_id == account_id
        assert state.verified is True
        assert state.role == "member"
        assert state.suspended_at is None
        repository.find_account_by_id.assert_awaited_once_with(session, account_id, lock=True)

    asyncio.run(verify())


def test_founder_states_are_fetched_in_one_bounded_batch() -> None:
    async def verify() -> None:
        first_id, second_id = uuid4(), uuid4()
        now = datetime.now(UTC)
        accounts = [
            SimpleNamespace(id=first_id, verified_at=now, role="member", suspended_at=None),
            SimpleNamespace(id=second_id, verified_at=now, role="member", suspended_at=now),
        ]
        repository: Any = SimpleNamespace(find_accounts_by_ids=AsyncMock(return_value=accounts))
        session: Any = SimpleNamespace()
        states = await AuthAccessService(repository=repository).founder_states(
            session, [first_id, second_id, first_id]
        )
        assert set(states) == {first_id, second_id}
        assert states[first_id].suspended_at is None
        assert states[second_id].suspended_at == now
        repository.find_accounts_by_ids.assert_awaited_once_with(session, [first_id, second_id])

    asyncio.run(verify())


def test_session_lookup_refreshes_cached_account_authorization() -> None:
    async def verify() -> None:
        result: Any = SimpleNamespace(first=lambda: None)
        session: Any = SimpleNamespace(execute=AsyncMock(return_value=result))
        await AuthRepository().find_session(session, b"digest", lock=True)
        query = session.execute.await_args.args[0]
        assert query.get_execution_options()["populate_existing"] is True

    asyncio.run(verify())


def test_named_account_lock_refreshes_cached_authorization() -> None:
    async def verify() -> None:
        session: Any = SimpleNamespace(scalar=AsyncMock(return_value=None))
        await AuthRepository().find_account_by_id(session, uuid4(), lock=True)
        query = session.scalar.await_args.args[0]
        assert query.get_execution_options()["populate_existing"] is True
        assert "FOR UPDATE" in str(query)

    asyncio.run(verify())


def test_batched_founder_lookup_refreshes_cached_flags() -> None:
    async def verify() -> None:
        session: Any = SimpleNamespace(scalars=AsyncMock(return_value=[]))
        await AuthRepository().find_accounts_by_ids(session, [uuid4()])
        query = session.scalars.await_args.args[0]
        assert query.get_execution_options()["populate_existing"] is True

    asyncio.run(verify())


@pytest.mark.parametrize("actor", ["", "ops\nspoof", "x" * 129])
def test_operator_actor_must_be_a_bounded_single_identifier(actor: str) -> None:
    async def verify() -> None:
        with pytest.raises(StaffManagementError, match="invalid operator actor"):
            await StaffManagementService().set_role(
                SimpleNamespace(),  # type: ignore[arg-type]
                target_account_id=uuid4(),
                role="reviewer",
                actor=actor,
            )

    asyncio.run(verify())


def test_set_role_reuses_an_existing_caller_transaction() -> None:
    async def verify() -> None:
        account_id = uuid4()
        account = SimpleNamespace(
            id=account_id,
            verified_at=datetime.now(UTC),
            role="member",
            suspended_at=None,
            updated_at=None,
        )
        repository: Any = SimpleNamespace(find_account_by_id=AsyncMock(return_value=account))
        session: Any = SimpleNamespace(
            in_transaction=Mock(return_value=True),
            add=Mock(),
            flush=AsyncMock(),
        )

        state = await StaffManagementService(repository=repository).set_role(
            session,
            target_account_id=account_id,
            role="reviewer",
            actor="demo-seed-operator",
        )

        assert state.role == "reviewer"
        assert account.role == "reviewer"
        repository.find_account_by_id.assert_awaited_once_with(session, account_id, lock=True)
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    asyncio.run(verify())
