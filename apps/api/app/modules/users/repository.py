"""Profile persistence boundary used by auth registration bootstrap."""

from __future__ import annotations

from uuid import UUID

from app.modules.users.models import Profile
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession


class ProfileRepository:
    """Own profile writes without depending on auth repositories."""

    async def create_private(self, session: AsyncSession, account_id: UUID) -> Profile:
        await session.execute(
            insert(Profile).values(
                account_id=account_id,
                visibility="private",
                version=0,
            )
        )
        return Profile(account_id=account_id, visibility="private", version=0)
