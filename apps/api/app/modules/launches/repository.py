"""PostgreSQL persistence for retained launch booking history."""

from __future__ import annotations

from datetime import date, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.modules.launches.models import LaunchBooking


class LaunchBookingRepository:
    """Keep booking queries and mutations inside the launches feature."""

    async def get_by_id(
        self, session: AsyncSession, *, booking_id: UUID, lock: bool = False
    ) -> LaunchBooking | None:
        statement = select(LaunchBooking).where(LaunchBooking.id == booking_id)
        if lock:
            statement = statement.with_for_update()
        return cast(LaunchBooking | None, await session.scalar(statement))

    async def record_publication_outcome(
        self,
        session: AsyncSession,
        *,
        booking_id: UUID,
        state: str,
        failure_reason: str | None,
        closed_at: datetime,
    ) -> LaunchBooking | None:
        """Close only an active booking; return the persisted row for safe replay."""

        saved = await session.scalar(
            update(LaunchBooking)
            .where(LaunchBooking.id == booking_id, LaunchBooking.state == "scheduled")
            .values(state=state, failure_reason=failure_reason, closed_at=closed_at)
            .returning(LaunchBooking)
        )
        if saved is not None:
            return saved
        return await self.get_by_id(session, booking_id=booking_id)

    async def find_booking_by_founder_key(
        self, session: AsyncSession, *, founder_id: UUID, idempotency_key: str
    ) -> LaunchBooking | None:
        result = await session.scalar(
            select(LaunchBooking).where(
                LaunchBooking.founder_id == founder_id,
                LaunchBooking.idempotency_key == idempotency_key,
            )
        )
        return result

    async def find_booking_by_close_key(
        self, session: AsyncSession, *, founder_id: UUID, idempotency_key: str
    ) -> LaunchBooking | None:
        result = await session.scalar(
            select(LaunchBooking).where(
                LaunchBooking.founder_id == founder_id,
                LaunchBooking.closed_by_idempotency_key == idempotency_key,
            )
        )
        return result

    async def active_for_product(
        self, session: AsyncSession, *, product_id: UUID, lock: bool = False
    ) -> LaunchBooking | None:
        statement = select(LaunchBooking).where(
            LaunchBooking.product_id == product_id, LaunchBooking.state == "scheduled"
        )
        if lock:
            statement = statement.with_for_update()
        return cast(LaunchBooking | None, await session.scalar(statement))

    async def count_active(
        self, session: AsyncSession, *, founder_id: UUID, launch_date: date
    ) -> int:
        count = await session.scalar(
            select(func.count())
            .select_from(LaunchBooking)
            .where(
                LaunchBooking.founder_id == founder_id,
                LaunchBooking.launch_date == launch_date,
                LaunchBooking.state == "scheduled",
            )
        )
        return int(count or 0)

    async def create(
        self,
        session: AsyncSession,
        *,
        product_id: UUID,
        founder_id: UUID,
        launch_date: date,
        launch_at: datetime,
        idempotency_key: str,
        request_fingerprint: str,
        now: datetime,
    ) -> LaunchBooking:
        statement = (
            insert(LaunchBooking)
            .values(
                id=uuid7(),
                product_id=product_id,
                founder_id=founder_id,
                launch_date=launch_date,
                launch_at=launch_at,
                state="scheduled",
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                created_at=now,
                closed_at=None,
            )
            .returning(LaunchBooking)
        )
        return (await session.scalars(statement)).one()

    async def close(
        self,
        session: AsyncSession,
        *,
        booking_id: UUID,
        state: str,
        closed_at: datetime,
        idempotency_key: str | None = None,
        request_fingerprint: str | None = None,
    ) -> LaunchBooking:
        """Close an active booking with one atomic database update."""

        values: dict[str, object] = {"state": state, "closed_at": closed_at}
        if idempotency_key is not None:
            values["closed_by_idempotency_key"] = idempotency_key
            values["close_request_fingerprint"] = request_fingerprint
        statement = (
            update(LaunchBooking)
            .where(LaunchBooking.id == booking_id, LaunchBooking.state == "scheduled")
            .values(**values)
            .returning(LaunchBooking)
        )
        result = await session.scalars(statement)
        return result.one()
