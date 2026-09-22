"""Named users service interfaces for cross-feature profile operations."""

from __future__ import annotations

from uuid import UUID

from app.modules.users.models import Profile
from app.modules.users.repository import ProfileRepository
from sqlalchemy.ext.asyncio import AsyncSession


class ProfileBootstrap:
    """Create the private profile paired with a newly registered account."""

    def __init__(self, repository: ProfileRepository | None = None) -> None:
        self.repository = repository or ProfileRepository()

    async def create_private_profile(self, session: AsyncSession, account_id: UUID) -> Profile:
        return await self.repository.create_private(session, account_id)
