"""Internal auth-owned provisioning for fictional demo accounts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.repository import AuthRepository
from app.modules.auth.staff import AccountRole, AccountState, StaffManagementService
from app.shared.security.email import canonicalize_email
from app.shared.security.passwords import hash_password


class DemoAccountConflict(ValueError):
    """A requested demo identity conflicts with an unowned or changed account."""


@dataclass(frozen=True, slots=True)
class DemoAccountProvisioningResult:
    """Safe account identity and whether this invocation created it."""

    account_id: UUID
    created: bool


class AuthProvisioningRepository(Protocol):
    """Minimal auth repository surface required by the seed provisioner."""

    async def find_account_by_email_key(
        self, session: AsyncSession, email_key: str, *, lock: bool = False
    ) -> object | None: ...

    async def find_account_by_id(
        self, session: AsyncSession, account_id: UUID, *, lock: bool = False
    ) -> object | None: ...

    async def create_account(
        self,
        session: AsyncSession,
        *,
        email_display: str,
        email_key: str,
        password_hash: str,
        now: datetime,
    ) -> object: ...


class ReviewerRoleProvisioner(Protocol):
    """Narrow role-change interface; real implementation persists staff audit."""

    async def set_role(
        self,
        session: AsyncSession,
        *,
        target_account_id: UUID,
        role: AccountRole,
        actor: str,
    ) -> AccountState: ...


class DemoAccountProvisioningService:
    """Create verified accounts without verification challenges or mail events."""

    def __init__(
        self,
        *,
        repository: AuthProvisioningRepository | None = None,
        staff_management: ReviewerRoleProvisioner | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository or AuthRepository()
        self.staff_management = staff_management or StaffManagementService()
        self.clock = clock or (lambda: datetime.now(UTC))

    async def provision_verified_account(
        self,
        session: AsyncSession,
        *,
        email: str,
        password: str,
        owned_account_id: UUID | None = None,
    ) -> DemoAccountProvisioningResult:
        """Create an account once or verify that a ledger-owned account still matches."""

        identity = canonicalize_email(email)
        existing = await self.repository.find_account_by_email_key(session, identity.key, lock=True)
        if existing is not None:
            account_id = getattr(existing, "id", None)
            if owned_account_id is None:
                raise DemoAccountConflict("identity is already in use")
            if account_id != owned_account_id:
                raise DemoAccountConflict("ownership record does not match")
            return DemoAccountProvisioningResult(account_id=owned_account_id, created=False)

        if owned_account_id is not None:
            owned = await self.repository.find_account_by_id(session, owned_account_id, lock=True)
            if owned is not None:
                raise DemoAccountConflict("ownership record does not match")
            raise DemoAccountConflict("owned account is unavailable")

        now = self.clock().astimezone(UTC)
        password_hash = hash_password(password)
        try:
            async with session.begin_nested():
                account = await self.repository.create_account(
                    session,
                    email_display=identity.delivery,
                    email_key=identity.key,
                    password_hash=password_hash,
                    now=now,
                )
                setattr(account, "verified_at", now)
                setattr(account, "updated_at", now)
                await session.flush()
        except IntegrityError as error:
            raise DemoAccountConflict("identity is already in use") from error

        account_id = getattr(account, "id", None)
        if not isinstance(account_id, UUID):
            raise RuntimeError("Auth repository returned an invalid account identity.")
        return DemoAccountProvisioningResult(account_id=account_id, created=True)

    async def grant_reviewer(
        self, session: AsyncSession, *, account_id: UUID, actor: str
    ) -> AccountState:
        """Grant only reviewer access via the existing audited staff boundary."""

        return await self.staff_management.set_role(
            session,
            target_account_id=account_id,
            role="reviewer",
            actor=actor,
        )
