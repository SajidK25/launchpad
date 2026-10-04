"""Persistence boundary for founder notifications."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_, func, insert, or_, select, update
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

    async def list_for_recipient(
        self,
        session: AsyncSession,
        *,
        recipient_id: UUID,
        limit: int,
        after: tuple[datetime, UUID] | None,
    ) -> list[Notification]:
        """Read one recipient's newest notifications using a stable keyset cursor."""

        statement = select(Notification).where(Notification.recipient_account_id == recipient_id)
        if after is not None:
            created_at, notification_id = after
            statement = statement.where(
                or_(
                    Notification.created_at < created_at,
                    and_(
                        Notification.created_at == created_at,
                        Notification.id < notification_id,
                    ),
                )
            )
        return list(
            (
                await session.scalars(
                    statement.order_by(
                        Notification.created_at.desc(), Notification.id.desc()
                    ).limit(limit)
                )
            ).all()
        )

    async def count_unread(self, session: AsyncSession, *, recipient_id: UUID) -> int:
        count = await session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.recipient_account_id == recipient_id,
                Notification.read_at.is_(None),
            )
        )
        return int(count or 0)

    async def get_for_recipient(
        self, session: AsyncSession, *, recipient_id: UUID, notification_id: UUID
    ) -> Notification | None:
        return cast(
            Notification | None,
            await session.scalar(
                select(Notification)
                .where(
                    Notification.id == notification_id,
                    Notification.recipient_account_id == recipient_id,
                )
                .execution_options(populate_existing=True)
            ),
        )

    async def mark_unread(
        self,
        session: AsyncSession,
        *,
        recipient_id: UUID,
        notification_id: UUID,
        read_at: datetime,
    ) -> Notification | None:
        """Atomically mark one owned unread item; return None for a prior read/race."""

        return cast(
            Notification | None,
            await session.scalar(
                update(Notification)
                .where(
                    Notification.id == notification_id,
                    Notification.recipient_account_id == recipient_id,
                    Notification.read_at.is_(None),
                )
                .values(read_at=read_at)
                .returning(Notification)
            ),
        )
