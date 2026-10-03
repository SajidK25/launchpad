"""Persistence boundary for founder notifications."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import Notification


class NotificationRepository:
    """Read and write notification rows through the caller's transaction."""

    async def find_review_notification(
        self, session: AsyncSession, review_decision_id: UUID
    ) -> Notification | None:
        return cast(
            Notification | None,
            await session.scalar(
                select(Notification).where(Notification.review_decision_id == review_decision_id)
            ),
        )

    async def add(self, session: AsyncSession, notification: Notification) -> None:
        session.add(notification)
        await session.flush()
