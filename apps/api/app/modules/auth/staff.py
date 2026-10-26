"""Named, auth-owned access to current account authorization state."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.modules.auth.models import Account, AccountAdminAction
from app.modules.auth.repository import AuthRepository


@dataclass(frozen=True, slots=True)
class AccountState:
    """Minimal live state safe for product authorization decisions."""

    account_id: UUID
    verified: bool
    role: str
    suspended_at: datetime | None


class AuthAccessService:
    """Expose account state and row locking without leaking auth repositories."""

    def __init__(self, repository: AuthRepository | None = None) -> None:
        self.repository = repository or AuthRepository()

    async def verified_recipient_email(self, session: AsyncSession, account_id: UUID) -> str | None:
        """Return this account's current verified address for deferred delivery."""

        account = await self.repository.find_account_by_id(session, account_id)
        if account is None or account.verified_at is None:
            return None
        return account.email_display

    async def current_account(
        self, session: AsyncSession, account_id: UUID, *, lock: bool = False
    ) -> AccountState | None:
        account = await self.repository.find_account_by_id(session, account_id, lock=lock)
        if account is None:
            return None
        return AccountState(
            account_id=account.id,
            verified=account.verified_at is not None,
            role=account.role,
            suspended_at=account.suspended_at,
        )

    async def profile_identity_data(
        self, session: AsyncSession, account_id: UUID
    ) -> tuple[UUID, str, bool] | None:
        """Return the minimal identity fields required by the users boundary."""

        account = await self.repository.find_account_by_id(session, account_id)
        if account is None:
            return None
        return account.id, account.email_display, account.verified_at is not None

    async def founder_states(
        self, session: AsyncSession, account_ids: Sequence[UUID]
    ) -> dict[UUID, AccountState]:
        """Return current flags for one queue page without N+1 account reads."""

        unique_ids = list(dict.fromkeys(account_ids))
        if not unique_ids:
            return {}
        accounts = await self.repository.find_accounts_by_ids(session, unique_ids)
        return {
            account.id: AccountState(
                account_id=account.id,
                verified=account.verified_at is not None,
                role=account.role,
                suspended_at=account.suspended_at,
            )
            for account in accounts
        }


AccountRole = Literal["member", "reviewer", "admin"]


class StaffManagementError(ValueError):
    """Invalid operator action with a safe, credential-free message."""


class StaffManagementService:
    """Apply audited privilege changes inside one database transaction."""

    def __init__(self, repository: AuthRepository | None = None) -> None:
        self.repository = repository or AuthRepository()

    async def set_role(
        self,
        session: AsyncSession,
        *,
        target_account_id: UUID,
        role: AccountRole,
        actor: str,
    ) -> AccountState:
        if role not in {"member", "reviewer", "admin"}:
            raise StaffManagementError("invalid role")
        operator = _operator_actor(actor)
        async with session.begin():
            account = await self.repository.find_account_by_id(
                session, target_account_id, lock=True
            )
            if account is None:
                raise StaffManagementError("account unavailable")
            if role != "member" and account.verified_at is None:
                raise StaffManagementError("staff account must be verified")
            if account.role == role:
                raise StaffManagementError("role unchanged")
            before = _audit_state(account)
            account.role = role
            now = datetime.now(UTC)
            account.updated_at = now
            _add_audit(session, account, operator, "set_role", before, now)
            await session.flush()
            return _account_state(account)

    async def set_suspension(
        self,
        session: AsyncSession,
        *,
        target_account_id: UUID,
        suspended: bool,
        actor: str,
    ) -> AccountState:
        operator = _operator_actor(actor)
        async with session.begin():
            account = await self.repository.find_account_by_id(
                session, target_account_id, lock=True
            )
            if account is None:
                raise StaffManagementError("account unavailable")
            if (account.suspended_at is not None) == suspended:
                raise StaffManagementError("suspension unchanged")
            before = _audit_state(account)
            now = datetime.now(UTC)
            account.suspended_at = now if suspended else None
            account.updated_at = now
            _add_audit(
                session,
                account,
                operator,
                "suspend" if suspended else "resume",
                before,
                now,
            )
            await session.flush()
            return _account_state(account)


def _operator_actor(actor: str) -> str:
    value = actor.strip()
    if not value or len(value) > 128 or any(character.isspace() for character in value):
        raise StaffManagementError("invalid operator actor")
    return value


def _audit_state(account: Account) -> str:
    """Serialize only authorization fields, never identity credentials."""

    return json.dumps(
        {
            "role": account.role,
            "suspended_at": (
                account.suspended_at.isoformat() if account.suspended_at is not None else None
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _add_audit(
    session: AsyncSession,
    account: Account,
    actor: str,
    action: str,
    before: str,
    now: datetime,
) -> None:
    session.add(
        AccountAdminAction(
            id=uuid7(),
            actor=actor,
            target_account_id=account.id,
            action=action,
            before_state=before,
            after_state=_audit_state(account),
            created_at=now,
        )
    )


def _account_state(account: Account) -> AccountState:
    return AccountState(
        account_id=account.id,
        verified=account.verified_at is not None,
        role=account.role,
        suspended_at=account.suspended_at,
    )
