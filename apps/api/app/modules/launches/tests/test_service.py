"""Domain-level tests for UTC booking and founder capacity rules."""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from app.modules.auth.staff import AccountState
from app.modules.launches.policies import LaunchConflictError, LaunchForbiddenError
from app.modules.launches.service import LaunchBookingService


class _Transaction(AbstractAsyncContextManager[None]):
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        return None


class _Session:
    def begin_nested(self) -> _Transaction:
        return _Transaction()


class _Accounts:
    def __init__(self) -> None:
        self.account_id = uuid4()
        self.locks: list[bool] = []
        self.suspended_at: datetime | None = None
        self.exists = True

    async def current_account(
        self, session: Any, account_id: UUID, *, lock: bool = False
    ) -> AccountState | None:
        self.locks.append(lock)
        if not self.exists:
            return None
        return AccountState(account_id, True, "member", self.suspended_at)


class _ProductAccess:
    def __init__(self) -> None:
        self.product_id = uuid4()
        self.product = SimpleNamespace(
            id=self.product_id,
            founder_id=uuid4(),
            status="approved",
            version=4,
        )
        self.scheduled: list[tuple[date, datetime, int]] = []

    async def get_approved_product(
        self, session: Any, *, founder_id: UUID, product_id: UUID, lock: bool = False
    ) -> Any:
        if product_id != self.product_id or founder_id != self.product.founder_id:
            return None
        return self.product

    async def schedule_product(
        self,
        session: Any,
        *,
        product: Any,
        expected_version: int,
        launch_date: date,
        launch_at: datetime,
        now: datetime,
    ) -> Any:
        self.scheduled.append((launch_date, launch_at, expected_version))
        product.status = "scheduled"
        product.version += 1
        return product

    async def get_scheduled_product(
        self, session: Any, *, founder_id: UUID, product_id: UUID, lock: bool = False
    ) -> Any:
        if product_id != self.product_id or founder_id != self.product.founder_id:
            return None
        return self.product if self.product.status == "scheduled" else None

    async def reschedule_product(self, session: Any, **values: Any) -> Any:
        return await self.schedule_product(session, **values)

    async def return_to_approved(self, session: Any, *, product: Any, **values: Any) -> Any:
        product.status = "approved"
        product.version += 1
        return product


class _Repository:
    def __init__(self) -> None:
        self.bookings: list[Any] = []

    async def find_booking_by_founder_key(
        self, session: Any, *, founder_id: UUID, idempotency_key: str
    ) -> Any | None:
        return next(
            (
                booking
                for booking in self.bookings
                if booking.founder_id == founder_id and booking.idempotency_key == idempotency_key
            ),
            None,
        )

    async def find_booking_by_close_key(
        self, session: Any, *, founder_id: UUID, idempotency_key: str
    ) -> Any | None:
        return next(
            (
                booking
                for booking in self.bookings
                if booking.founder_id == founder_id
                and booking.closed_by_idempotency_key == idempotency_key
            ),
            None,
        )

    async def active_for_product(
        self, session: Any, *, product_id: UUID, lock: bool = False
    ) -> Any | None:
        return next(
            (
                booking
                for booking in self.bookings
                if booking.product_id == product_id and booking.state == "scheduled"
            ),
            None,
        )

    async def count_active(self, session: Any, *, founder_id: UUID, launch_date: date) -> int:
        return sum(
            booking.founder_id == founder_id
            and booking.launch_date == launch_date
            and booking.state == "scheduled"
            for booking in self.bookings
        )

    async def add(self, session: Any, booking: Any) -> None:
        self.bookings.append(booking)

    async def create(self, session: Any, **values: Any) -> Any:
        booking = SimpleNamespace(id=uuid4(), state="scheduled", **values)
        self.bookings.append(booking)
        return booking


def test_booking_accepts_tomorrow_and_day_90_as_utc_dates() -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 17, 23, 59, tzinfo=UTC)
        accounts, products, repository = _Accounts(), _ProductAccess(), _Repository()
        products.product.founder_id = accounts.account_id
        service = LaunchBookingService(
            member_access=cast(Any, accounts),
            product_access=cast(Any, products),
            repository=cast(Any, repository),
            clock=lambda: now,
        )
        session = _Session()

        for offset in (1, 90):
            target = now.date() + timedelta(days=offset)
            result = await service.book(
                cast(Any, session),
                actor_id=accounts.account_id,
                product_id=products.product_id,
                launch_date=target,
                expected_version=4,
                idempotency_key=f"booking-{offset}",
            )
            assert result.launch_date == target
            assert result.launch_at == datetime.combine(target, datetime.min.time(), tzinfo=UTC)
            repository.bookings.clear()
            products.product.status = "approved"
            products.product.version = 4

        assert accounts.locks == [True, True]

    asyncio.run(verify())


@pytest.mark.parametrize("offset", [-1, 0, 91])
def test_booking_rejects_dates_outside_utc_window_without_mutation(offset: int) -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 17, 23, 59, tzinfo=UTC)
        accounts, products, repository = _Accounts(), _ProductAccess(), _Repository()
        products.product.founder_id = accounts.account_id
        service = LaunchBookingService(
            member_access=cast(Any, accounts),
            product_access=cast(Any, products),
            repository=cast(Any, repository),
            clock=lambda: now,
        )
        with pytest.raises(LaunchConflictError):
            await service.book(
                cast(Any, _Session()),
                actor_id=accounts.account_id,
                product_id=products.product_id,
                launch_date=now.date() + timedelta(days=offset),
                expected_version=4,
                idempotency_key="outside-window",
            )
        assert repository.bookings == []
        assert products.scheduled == []

    asyncio.run(verify())


@pytest.mark.parametrize("account_state", ["missing", "suspended"])
def test_booking_requires_existing_unsuspended_founder(account_state: str) -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 17, tzinfo=UTC)
        accounts, products, repository = _Accounts(), _ProductAccess(), _Repository()
        products.product.founder_id = accounts.account_id
        if account_state == "missing":
            accounts.exists = False
        else:
            accounts.suspended_at = now
        service = LaunchBookingService(
            member_access=cast(Any, accounts),
            product_access=cast(Any, products),
            repository=cast(Any, repository),
            clock=lambda: now,
        )
        with pytest.raises(LaunchForbiddenError):
            await service.book(
                cast(Any, _Session()),
                actor_id=accounts.account_id,
                product_id=products.product_id,
                launch_date=now.date() + timedelta(days=1),
                expected_version=4,
                idempotency_key="ineligible-founder",
            )
        assert products.scheduled == []
        assert repository.bookings == []

    asyncio.run(verify())


def test_booking_replay_returns_same_booking_and_key_conflict_is_rejected() -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 17, tzinfo=UTC)
        accounts, products, repository = _Accounts(), _ProductAccess(), _Repository()
        products.product.founder_id = accounts.account_id
        current_time = [now]
        service = LaunchBookingService(
            member_access=cast(Any, accounts),
            product_access=cast(Any, products),
            repository=cast(Any, repository),
            clock=lambda: current_time[0],
        )
        first = await service.book(
            cast(Any, _Session()),
            actor_id=accounts.account_id,
            product_id=products.product_id,
            launch_date=now.date() + timedelta(days=2),
            expected_version=4,
            idempotency_key="stable-request",
        )
        current_time[0] = datetime(2026, 10, 22, tzinfo=UTC)
        replay = await service.book(
            cast(Any, _Session()),
            actor_id=accounts.account_id,
            product_id=products.product_id,
            launch_date=now.date() + timedelta(days=2),
            expected_version=4,
            idempotency_key="stable-request",
        )
        assert replay is first
        assert len(repository.bookings) == 1
        with pytest.raises(LaunchConflictError):
            await service.book(
                cast(Any, _Session()),
                actor_id=accounts.account_id,
                product_id=products.product_id,
                launch_date=now.date() + timedelta(days=3),
                expected_version=4,
                idempotency_key="stable-request",
            )
        assert len(repository.bookings) == 1

    asyncio.run(verify())
