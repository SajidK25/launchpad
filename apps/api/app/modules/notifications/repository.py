"""Persistence boundary for founder notifications."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import insert, select
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
        """Insert through SQL Core across the notification module's separate metadata."""

        await session.execute(
            insert(Notification).values(
                id=notification.id,
                recipient_account_id=notification.recipient_account_id,
                review_decision_id=notification.review_decision_id,
                kind=notification.kind,
                created_at=notification.created_at,
                read_at=notification.read_at,
            )
        )
