"""Founder-owned booking, reschedule, and cancellation operations."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import UUID

from app.modules.auth.staff import AccountState
from app.modules.launches.models import LaunchBooking
from app.modules.launches.policies import (
    LaunchConflictError,
    LaunchForbiddenError,
    LaunchNotFoundError,
    require_before_launch,
    require_eligible_date,
    utc_now,
)
from app.modules.launches.repository import LaunchBookingRepository
from sqlalchemy.ext.asyncio import AsyncSession


class LaunchMemberAccess(Protocol):
    """Named auth-owned account state and serialization boundary."""

    async def current_account(
        self, session: AsyncSession, account_id: UUID, *, lock: bool = False
    ) -> AccountState | None: ...


class LaunchProductAccess(Protocol):
    """Product-owned eligibility and lifecycle operations over the caller session."""

    async def get_approved_product(
        self,
        session: AsyncSession,
        *,
        founder_id: UUID,
        product_id: UUID,
        lock: bool = False,
    ) -> object | None: ...

    async def get_scheduled_product(
        self,
        session: AsyncSession,
        *,
        founder_id: UUID,
        product_id: UUID,
        lock: bool = False,
    ) -> object | None: ...

    async def schedule_product(
        self,
        session: AsyncSession,
        *,
        product: object,
        expected_version: int,
        launch_date: date,
        launch_at: datetime,
        now: datetime,
    ) -> object: ...

    async def reschedule_product(
        self,
        session: AsyncSession,
        *,
        product: object,
        expected_version: int,
        launch_date: date,
        launch_at: datetime,
        now: datetime,
    ) -> object: ...

    async def return_to_approved(
        self,
        session: AsyncSession,
        *,
        product: object,
        expected_version: int,
        now: datetime,
        reason: str,
    ) -> object: ...


class LaunchBookingService:
    """Apply booking invariants transactionally while delegating product state."""

    def __init__(
        self,
        *,
        member_access: LaunchMemberAccess,
        product_access: LaunchProductAccess,
        repository: LaunchBookingRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.member_access = member_access
        self.product_access = product_access
        self.repository = repository or LaunchBookingRepository()
        self.clock = clock or (lambda: datetime.now(UTC))

    async def book(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        product_id: UUID,
        launch_date: date,
        expected_version: int,
        idempotency_key: str,
    ) -> LaunchBooking:
        now = utc_now(self.clock())
        key = _validate_key(idempotency_key)
        fingerprint = _fingerprint("book", product_id, launch_date, expected_version)
        async with session.begin_nested():
            await self._active_founder(session, actor_id)
            previous = await self.repository.find_booking_by_founder_key(
                session, founder_id=actor_id, idempotency_key=key
            )
            if previous is not None:
                _require_same_fingerprint(previous.request_fingerprint, fingerprint)
                return previous
            launch_at = require_eligible_date(launch_date, now=now)
            product = await self.product_access.get_approved_product(
                session, founder_id=actor_id, product_id=product_id, lock=True
            )
            if product is None:
                raise LaunchNotFoundError("approved product unavailable")
            active = await self.repository.active_for_product(session, product_id=product_id)
            if active is not None:
                raise LaunchConflictError("product already has an active booking")
            await self._require_capacity(session, actor_id, launch_date)
            await self.product_access.schedule_product(
                session,
                product=product,
                expected_version=expected_version,
                launch_date=launch_date,
                launch_at=launch_at,
                now=now,
            )
            return await self.repository.create(
                session,
                product_id=product_id,
                founder_id=actor_id,
                launch_date=launch_date,
                launch_at=launch_at,
                idempotency_key=key,
                request_fingerprint=fingerprint,
                now=now,
            )

    async def reschedule(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        product_id: UUID,
        launch_date: date,
        expected_version: int,
        idempotency_key: str,
    ) -> LaunchBooking:
        now = utc_now(self.clock())
        key = _validate_key(idempotency_key)
        fingerprint = _fingerprint("reschedule", product_id, launch_date, expected_version)
        async with session.begin_nested():
            await self._active_founder(session, actor_id)
            previous_request = await self.repository.find_booking_by_founder_key(
                session, founder_id=actor_id, idempotency_key=key
            )
            if previous_request is not None:
                _require_same_fingerprint(previous_request.request_fingerprint, fingerprint)
                return previous_request
            launch_at = require_eligible_date(launch_date, now=now)
            product = await self.product_access.get_scheduled_product(
                session, founder_id=actor_id, product_id=product_id, lock=True
            )
            if product is None:
                raise LaunchNotFoundError("scheduled product unavailable")
            current = await self.repository.active_for_product(
                session, product_id=product_id, lock=True
            )
            if current is None or current.founder_id != actor_id:
                raise LaunchNotFoundError("scheduled product unavailable")
            require_before_launch(current.launch_at, now=now)
            await self._require_capacity(session, actor_id, launch_date)
            await self.product_access.reschedule_product(
                session,
                product=product,
                expected_version=expected_version,
                launch_date=launch_date,
                launch_at=launch_at,
                now=now,
            )
            await self.repository.close(
                session, booking_id=current.id, state="replaced", closed_at=now
            )
            replacement = await self.repository.create(
                session,
                product_id=product_id,
                founder_id=actor_id,
                launch_date=launch_date,
                launch_at=launch_at,
                idempotency_key=key,
                request_fingerprint=fingerprint,
                now=now,
            )
            return replacement

    async def cancel(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        product_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> LaunchBooking:
        now = utc_now(self.clock())
        key = _validate_key(idempotency_key)
        fingerprint = _fingerprint("cancel", product_id, None, expected_version)
        async with session.begin_nested():
            await self._active_founder(session, actor_id)
            previous = await self.repository.find_booking_by_close_key(
                session, founder_id=actor_id, idempotency_key=key
            )
            if previous is not None:
                _require_same_fingerprint(previous.close_request_fingerprint or "", fingerprint)
                return previous
            product = await self.product_access.get_scheduled_product(
                session, founder_id=actor_id, product_id=product_id, lock=True
            )
            if product is None:
                raise LaunchNotFoundError("scheduled product unavailable")
            booking = await self.repository.active_for_product(
                session, product_id=product_id, lock=True
            )
            if booking is None or booking.founder_id != actor_id:
                raise LaunchNotFoundError("scheduled product unavailable")
            require_before_launch(booking.launch_at, now=now)
            await self.product_access.return_to_approved(
                session,
                product=product,
                expected_version=expected_version,
                now=now,
                reason="booking_cancelled",
            )
            return await self.repository.close(
                session,
                booking_id=booking.id,
                state="cancelled",
                closed_at=now,
                idempotency_key=key,
                request_fingerprint=fingerprint,
            )

    async def _active_founder(self, session: AsyncSession, actor_id: UUID) -> AccountState:
        account = await self.member_access.current_account(session, actor_id, lock=True)
        if account is None or account.suspended_at is not None or account.role != "member":
            raise LaunchForbiddenError("launch booking is forbidden")
        return account

    async def _require_capacity(
        self, session: AsyncSession, founder_id: UUID, launch_date: date
    ) -> None:
        if (
            await self.repository.count_active(
                session, founder_id=founder_id, launch_date=launch_date
            )
            >= 2
        ):
            raise LaunchConflictError("daily launch booking limit reached")


def _validate_key(value: str) -> str:
    key = value.strip()
    if not key or len(key) > 255 or key != value:
        raise LaunchConflictError("invalid idempotency key")
    return key


def _fingerprint(action: str, product_id: UUID, launch_date: date | None, version: int) -> str:
    date_value = launch_date.isoformat() if launch_date else None
    payload = json.dumps(
        {
            "action": action,
            "product_id": str(product_id),
            "launch_date": date_value,
            "version": version,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _require_same_fingerprint(stored: str, supplied: str) -> None:
    if not hmac.compare_digest(stored, supplied):
        raise LaunchConflictError("idempotency key was already used for another request")
