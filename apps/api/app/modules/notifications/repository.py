"""Persistence boundary for founder notifications."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import LaunchNotificationPreference, Notification


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

    async def find_launch_notification(
        self, session: AsyncSession, *, booking_id: UUID, kind: str
    ) -> Notification | None:
        return cast(
            Notification | None,
            await session.scalar(
                select(Notification).where(
                    Notification.launch_booking_id == booking_id,
                    Notification.kind == kind,
                )
            ),
        )

    async def add_launch_notification(
        self, session: AsyncSession, notification: Notification
    ) -> tuple[Notification, bool]:
        """Insert one booking/kind notice without racing into a duplicate inbox row."""

        booking_id = notification.launch_booking_id
        if booking_id is None:
            raise ValueError("launch booking identity is required")
        statement = (
            pg_insert(Notification)
            .values(
                id=notification.id,
                recipient_account_id=notification.recipient_account_id,
                product_id=notification.product_id,
                review_decision_id=None,
                launch_booking_id=notification.launch_booking_id,
                kind=notification.kind,
                created_at=notification.created_at,
                read_at=notification.read_at,
            )
            .on_conflict_do_nothing(
                index_elements=[Notification.launch_booking_id, Notification.kind],
                index_where=Notification.launch_booking_id.is_not(None),
            )
            .returning(Notification)
        )
        created = await session.scalar(statement)
        if created is not None:
            return created, True
        existing = await self.find_launch_notification(
            session, booking_id=booking_id, kind=notification.kind
        )
        if existing is None:
            raise RuntimeError("notification insert was not visible")
        return existing, False

    async def find_launch_preferences(
        self, session: AsyncSession, *, account_id: UUID
    ) -> LaunchNotificationPreference | None:
        return cast(
            LaunchNotificationPreference | None,
            await session.scalar(
                select(LaunchNotificationPreference).where(
                    LaunchNotificationPreference.account_id == account_id
                )
            ),
        )

    async def save_launch_preferences(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
        values: dict[str, bool],
        updated_at: datetime,
    ) -> dict[str, bool]:
        """Upsert selected values without overwriting independently changed channels."""

        defaults = {
            "reminder_email": True,
            "reminder_in_site": True,
            "live_email": True,
            "live_in_site": True,
            "failure_email": True,
            "failure_in_site": True,
        }
        statement = pg_insert(LaunchNotificationPreference).values(
            account_id=account_id,
            updated_at=updated_at,
            **{**defaults, **values},
        )
        result = await session.execute(
            statement.on_conflict_do_update(
                index_elements=[LaunchNotificationPreference.account_id],
                set_={**values, "updated_at": updated_at},
            ).returning(LaunchNotificationPreference)
        )
        row = result.scalar_one()
        return {
            "reminder_email": row.reminder_email,
            "reminder_in_site": row.reminder_in_site,
            "live_email": row.live_email,
            "live_in_site": row.live_in_site,
            "failure_email": row.failure_email,
            "failure_in_site": row.failure_in_site,
        }

    async def add(self, session: AsyncSession, notification: Notification) -> None:
        """Insert through SQL Core across the notification module's separate metadata."""

        await session.execute(
            insert(Notification).values(
                id=notification.id,
                recipient_account_id=notification.recipient_account_id,
                product_id=notification.product_id,
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
