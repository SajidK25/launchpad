"""Named, auth-owned access to current account authorization state."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

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
