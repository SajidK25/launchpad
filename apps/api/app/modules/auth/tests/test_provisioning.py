"""Tests for the operator-only, no-email account provisioning boundary."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.modules.auth.models import Account
from app.modules.auth.provisioning import (
    DemoAccountConflict,
    DemoAccountProvisioningService,
)
from app.modules.auth.staff import AccountState
from app.shared.security.passwords import verify_password


class FakeSession:
    """Only the transaction and flush surface used by auth provisioning."""

    @asynccontextmanager
    async def begin_nested(self) -> AsyncIterator[None]:
        yield

    async def flush(self) -> None:
        return None


class FakeAuthRepository:
    """Retain account rows while recording forbidden verification side effects."""

    def __init__(self) -> None:
        self.accounts_by_email: dict[str, Account] = {}
        self.verification_calls = 0

    async def find_account_by_email_key(
        self, session: AsyncSession, email_key: str, *, lock: bool = False
    ) -> Account | None:
        return self.accounts_by_email.get(email_key)

    async def find_account_by_id(
        self, session: AsyncSession, account_id: UUID, *, lock: bool = False
    ) -> Account | None:
        return next(
            (account for account in self.accounts_by_email.values() if account.id == account_id),
            None,
        )

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
            role="member",
            created_at=now,
            updated_at=now,
        )
        self.accounts_by_email[email_key] = account
        return account


class FakeStaffManagement:
    """Record explicit role requests and emulate the audited service response."""

    def __init__(self) -> None:
        self.requests: list[tuple[UUID, str, str]] = []

    async def set_role(
        self,
        session: AsyncSession,
        *,
        target_account_id: UUID,
        role: Literal["member", "reviewer", "admin"],
        actor: str,
    ) -> AccountState:
        self.requests.append((target_account_id, role, actor))
        return AccountState(
            account_id=target_account_id,
            verified=True,
            role=role,
            suspended_at=None,
        )


def test_creates_verified_argon2_account_without_verification_side_effects() -> None:
    async def verify() -> None:
        repository = FakeAuthRepository()
        now = datetime(2026, 10, 26, tzinfo=UTC)
        service = DemoAccountProvisioningService(repository=repository, clock=lambda: now)
        result = await service.provision_verified_account(
            _session(),
            email="Founder.One@example.com",
            password="random-generated-demo-secret-01",
        )
        account = repository.accounts_by_email["founder.one@example.com"]
        assert result.account_id == account.id
        assert result.created is True
        assert account.verified_at == now
        assert account.password_hash.startswith("$argon2id$")
        assert verify_password("random-generated-demo-secret-01", account.password_hash)
        assert repository.verification_calls == 0

    asyncio.run(verify())


def test_owned_account_retry_preserves_password_verification_and_role() -> None:
    async def verify() -> None:
        repository = FakeAuthRepository()
        now = datetime(2026, 10, 26, tzinfo=UTC)
        service = DemoAccountProvisioningService(repository=repository, clock=lambda: now)
        session = _session()
        first = await service.provision_verified_account(
            session, email="founder@example.com", password="initial-random-secret-01"
        )
        account = repository.accounts_by_email["founder@example.com"]
        account.role = "reviewer"
        before = (account.password_hash, account.verified_at, account.role)
        retried = await service.provision_verified_account(
            session,
            email="founder@example.com",
            password="different-random-secret-02",
            owned_account_id=first.account_id,
        )
        assert retried.created is False
        assert retried.account_id == first.account_id
        assert (account.password_hash, account.verified_at, account.role) == before

    asyncio.run(verify())


def test_rejects_unowned_email_collision_without_mutation() -> None:
    async def verify() -> None:
        repository = FakeAuthRepository()
        now = datetime(2026, 10, 26, tzinfo=UTC)
        service = DemoAccountProvisioningService(repository=repository, clock=lambda: now)
        account = await repository.create_account(
            _session(),
            email_display="occupied@example.com",
            email_key="occupied@example.com",
            password_hash="unchanged-hash",
            now=now,
        )
        before = (account.id, account.password_hash, account.verified_at, account.role)
        with pytest.raises(DemoAccountConflict, match="identity is already in use"):
            await service.provision_verified_account(
                _session(),
                email="occupied@example.com",
                password="random-secret-03",
            )
        assert (account.id, account.password_hash, account.verified_at, account.role) == before

    asyncio.run(verify())


def test_reviewer_grant_uses_audited_staff_service_and_never_admin() -> None:
    async def verify() -> None:
        staff = FakeStaffManagement()
        service = DemoAccountProvisioningService(
            repository=FakeAuthRepository(),
            staff_management=staff,
        )
        account_id = uuid7()
        result = await service.grant_reviewer(
            _session(), account_id=account_id, actor="demo-seed-operator"
        )
        assert result.role == "reviewer"
        assert result.verified is True
        assert staff.requests == [(account_id, "reviewer", "demo-seed-operator")]

    asyncio.run(verify())


def test_rejects_mismatched_ledger_account_without_mutation() -> None:
    async def verify() -> None:
        repository = FakeAuthRepository()
        service = DemoAccountProvisioningService(repository=repository)
        now = datetime.now(UTC)
        await repository.create_account(
            _session(),
            email_display="founder@example.com",
            email_key="founder@example.com",
            password_hash="owned-hash",
            now=now,
        )
        with pytest.raises(DemoAccountConflict, match="ownership record does not match"):
            await service.provision_verified_account(
                _session(),
                email="founder@example.com",
                password="random-secret-04",
                owned_account_id=uuid7(),
            )

    asyncio.run(verify())


def _session() -> AsyncSession:
    """Cast the minimal fake session to the service's typed boundary."""

    from typing import cast

    return cast(AsyncSession, FakeSession())
