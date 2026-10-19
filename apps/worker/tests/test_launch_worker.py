"""Worker-side launch relevance and delivery checks."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from app.modules.auth.models import Account
from app.modules.auth.staff import AuthAccessService
from app.modules.launches.models import LaunchBooking
from app.modules.launches.policies import LaunchConflictError
from app.modules.launches.repository import LaunchBookingRepository
from app.modules.launches.service import LaunchBookingService
from app.modules.notifications.live import notification_channel
from app.modules.notifications.models import Notification
from app.modules.notifications.service import NotificationService
from app.modules.products.models import Product
from app.modules.products.service import ProductService
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.models import OutboxMessage
from app.shared.events.outbox import OutboxRepository, PermanentEventError
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

sys.path.insert(0, "apps/worker")

from worker import LaunchEventWorker, LaunchNoticeEmailHandler, NotificationChangedPublisher


class _Bookings:
    def __init__(self, booking: SimpleNamespace) -> None:
        self.booking = booking
        self.outcomes: list[str] = []

    async def booking_by_id(
        self, _session: AsyncSession, *, booking_id: UUID, lock: bool = False
    ) -> SimpleNamespace | None:
        return self.booking if booking_id == self.booking.id else None

    async def record_publication_outcome(
        self, _session: AsyncSession, *, booking_id: UUID, outcome: str, now: datetime
    ) -> SimpleNamespace | None:
        assert booking_id == self.booking.id
        self.outcomes.append(outcome)
        self.booking.state = outcome
        self.booking.failure_reason = None if outcome == "launched" else outcome
        self.booking.closed_at = now
        return self.booking


class _Products:
    def __init__(self, status: str = "launched", failure: str | None = None) -> None:
        self.status = status
        self.failure = failure
        self.published: list[UUID] = []

    async def get_scheduled_product(self, *_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(status="scheduled")

    async def publish_scheduled_product(
        self,
        _session: AsyncSession,
        *,
        product_id: UUID,
        launch_at: datetime,
        now: datetime,
    ) -> SimpleNamespace:
        self.published.append(product_id)
        return SimpleNamespace(status=self.status, launch_failure_reason=self.failure)


class _MemberAccess:
    def __init__(
        self, *, suspended: bool = False, email: str | None = "founder@example.test"
    ) -> None:
        self.suspended = suspended
        self.email = email

    async def current_account(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(suspended_at=datetime.now(UTC) if self.suspended else None)

    async def verified_recipient_email(self, *_args: object) -> str | None:
        return self.email


class _Notifications:
    def __init__(self, *, email_enabled: bool = True) -> None:
        self.email_enabled = email_enabled
        self.notices: list[str] = []

    async def record_launch_notice(
        self, _session: AsyncSession, *, booking: Any, kind: str
    ) -> None:
        self.notices.append(kind)

    async def find_launch_preferences(
        self, _session: AsyncSession, *, account_id: UUID
    ) -> SimpleNamespace | None:
        return SimpleNamespace(
            reminder_email=self.email_enabled,
            live_email=self.email_enabled,
            failure_email=self.email_enabled,
        )

    async def get_for_recipient(
        self, _session: AsyncSession, *, recipient_id: UUID, notification_id: UUID
    ) -> SimpleNamespace | None:
        return SimpleNamespace(
            recipient_account_id=recipient_id,
            id=notification_id,
            launch_booking_id=self.booking_id,
            kind="launch_live",
        )

    booking_id: UUID


class _Redis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1


def _booking(*, state: str = "scheduled") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        product_id=uuid4(),
        founder_id=uuid4(),
        launch_at=datetime(2026, 10, 18, tzinfo=UTC),
        state=state,
        failure_reason=None,
        closed_at=None,
    )


def _launch_worker(
    booking: SimpleNamespace,
    products: _Products,
    notifications: _Notifications,
    member_access: _MemberAccess | None = None,
    *,
    now: datetime,
) -> LaunchEventWorker:
    return LaunchEventWorker(
        bookings=cast(Any, _Bookings(booking)),
        products=cast(Any, products),
        notifications=cast(Any, notifications),
        member_access=cast(Any, member_access or _MemberAccess()),
        clock=lambda: now,
    )


def test_reminder_rechecks_active_booking_and_before_launch_time() -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 17, 12, tzinfo=UTC)
        booking = _booking(state="replaced")
        notices = _Notifications()
        handler = _launch_worker(booking, _Products(), notices, now=now)
        payload: dict[str, object] = {
            "launch_booking_id": str(booking.id),
            "product_id": str(booking.product_id),
        }

        await handler.handle_launch_event(
            cast(AsyncSession, object()),
            event_type="launch.reminder_requested.v1",
            aggregate_id=booking.id,
            payload=payload,
        )

        assert notices.notices == []

        booking.state = "scheduled"
        handler = _launch_worker(
            booking,
            _Products(),
            notices,
            now=booking.launch_at + timedelta(seconds=1),
        )
        await handler.handle_launch_event(
            cast(AsyncSession, object()),
            event_type="launch.reminder_requested.v1",
            aggregate_id=booking.id,
            payload=payload,
        )
        assert notices.notices == []

    asyncio.run(verify())


def test_launch_event_locks_account_product_then_booking() -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 17, 12, tzinfo=UTC)
        booking = _booking()
        order: list[str] = []

        class OrderedBookings(_Bookings):
            async def booking_by_id(
                self, session: AsyncSession, *, booking_id: UUID, lock: bool = False
            ) -> SimpleNamespace | None:
                order.append("booking_lock" if lock else "booking_read")
                return await super().booking_by_id(session, booking_id=booking_id, lock=lock)

        class OrderedProducts(_Products):
            async def get_scheduled_product(self, *_args: object, **_kwargs: object) -> object:
                order.append("product_lock")
                return SimpleNamespace(status="scheduled")

        class OrderedMemberAccess(_MemberAccess):
            async def current_account(self, *_args: object, **kwargs: object) -> SimpleNamespace:
                assert kwargs.get("lock") is True
                order.append("account_lock")
                return SimpleNamespace(suspended_at=None)

        handler = LaunchEventWorker(
            bookings=cast(Any, OrderedBookings(booking)),
            products=cast(Any, OrderedProducts()),
            notifications=cast(Any, _Notifications()),
            member_access=cast(Any, OrderedMemberAccess()),
            clock=lambda: now,
        )
        await handler.handle_launch_event(
            cast(AsyncSession, object()),
            event_type="launch.reminder_requested.v1",
            aggregate_id=booking.id,
            payload={"launch_booking_id": str(booking.id), "product_id": str(booking.product_id)},
        )

        assert order == ["booking_read", "account_lock", "product_lock", "booking_lock"]

    asyncio.run(verify())


@pytest.mark.parametrize(
    ("product_status", "failure", "expected_outcome", "notice"),
    [
        ("launched", None, "launched", "launch_live"),
        ("approved", "missed_day", "missed_day", "launch_failed"),
        ("approved", "suspension_blocked", "suspension_blocked", "launch_failed"),
    ],
)
def test_publication_persists_booking_outcome_and_records_the_matching_notice(
    product_status: str, failure: str | None, expected_outcome: str, notice: str
) -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 18, 0, 1, tzinfo=UTC)
        booking = _booking()
        bookings = _Bookings(booking)
        products = _Products(product_status, failure)
        notifications = _Notifications()
        handler = LaunchEventWorker(
            bookings=cast(Any, bookings),
            products=cast(Any, products),
            notifications=cast(Any, notifications),
            member_access=cast(Any, _MemberAccess()),
            clock=lambda: now,
        )
        await handler.handle_launch_event(
            cast(AsyncSession, object()),
            event_type="launch.publish_requested.v1",
            aggregate_id=booking.id,
            payload={"launch_booking_id": str(booking.id), "product_id": str(booking.product_id)},
        )

        assert bookings.outcomes == [expected_outcome]
        assert booking.state == expected_outcome
        assert booking.failure_reason == (None if expected_outcome == "launched" else failure)
        assert notifications.notices == [notice]

    asyncio.run(verify())


def test_launch_email_rechecks_current_preference_state_and_verified_recipient() -> None:
    async def verify() -> None:
        booking = _booking(state="launched")
        repository = _Notifications(email_enabled=True)
        repository.booking_id = booking.id
        bookings = _Bookings(booking)
        handler = LaunchNoticeEmailHandler(
            bookings=cast(Any, bookings),
            member_access=cast(Any, _MemberAccess()),
            notifications=cast(Any, repository),
            clock=lambda: datetime(2026, 10, 18, 0, 1, tzinfo=UTC),
        )
        payload: dict[str, object] = {
            "recipient_account_id": str(booking.founder_id),
            "launch_booking_id": str(booking.id),
            "notification_id": str(booking.id),
            "kind": "launch_live",
        }
        email = await handler.prepare_email(
            cast(AsyncSession, object()), aggregate_id=booking.id, payload=payload
        )
        assert email["recipient"] == "founder@example.test"
        assert "failure_reason" not in email

        repository.email_enabled = False
        with pytest.raises(PermanentEventError, match="disabled"):
            await handler.prepare_email(
                cast(AsyncSession, object()), aggregate_id=booking.id, payload=payload
            )

    asyncio.run(verify())


def test_live_invalidation_validates_launch_booking_and_publishes_generic_hint() -> None:
    async def verify() -> None:
        recipient_id, notice_id, booking_id = uuid4(), uuid4(), uuid4()
        repository = _Notifications()
        repository.booking_id = booking_id
        redis = _Redis()
        publisher = NotificationChangedPublisher(
            redis=cast(Any, redis), notifications=cast(Any, repository)
        )
        payload: dict[str, object] = {
            "recipient_account_id": str(recipient_id),
            "notification_id": str(notice_id),
            "launch_booking_id": str(booking_id),
            "kind": "launch_live",
        }
        await publisher.publish_changed(
            cast(AsyncSession, object()), aggregate_id=booking_id, payload=payload
        )
        assert redis.published == [(notification_channel(recipient_id), "notifications_changed")]

        payload["launch_booking_id"] = str(uuid4())
        with pytest.raises(PermanentEventError, match="booking"):
            await publisher.publish_changed(
                cast(AsyncSession, object()), aggregate_id=booking_id, payload=payload
            )

    asyncio.run(verify())


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_postgres_publication_updates_product_booking_inbox_and_outbox_atomically() -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 18, tzinfo=UTC)
        founder_id, product_id, booking_id = uuid4(), uuid4(), uuid4()
        database = Database.connect(os.environ["DATABASE_URL"])
        codec = EmailPayloadCodec({"launch-worker-pg": b"w" * 32}, "launch-worker-pg")
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                await session.execute(
                    insert(Account).values(
                        id=founder_id,
                        email_display=f"{founder_id}@example.test",
                        email_key=f"{founder_id}@example.test",
                        password_hash="integration-only-placeholder",
                        verified_at=now,
                        role="member",
                        created_at=now,
                        updated_at=now,
                    )
                )
                await session.execute(
                    insert(Product).values(
                        id=product_id,
                        founder_id=founder_id,
                        status="scheduled",
                        version=4,
                        name="Worker launch",
                        pitch="A launch from a due event",
                        description="Description",
                        website_url="https://example.test/worker-launch",
                        website_key="https://example.test/worker-launch",
                        created_at=now,
                        updated_at=now,
                    )
                )
                await session.execute(
                    insert(LaunchBooking).values(
                        id=booking_id,
                        product_id=product_id,
                        founder_id=founder_id,
                        launch_date=date(2026, 10, 18),
                        launch_at=now,
                        state="scheduled",
                        idempotency_key="worker-event-booking",
                        request_fingerprint="b" * 64,
                        created_at=now,
                        closed_at=None,
                    )
                )

            outbox = OutboxRepository()
            access = AuthAccessService()
            products = ProductService(
                member_access=access,
                outbox_repository=outbox,
                payload_codec=codec,
                clock=lambda: now,
            )
            bookings = LaunchBookingService(
                member_access=access,
                product_access=products,
                repository=LaunchBookingRepository(),
                outbox_repository=outbox,
                payload_codec=codec,
                clock=lambda: now,
            )
            notification_service = NotificationService(
                outbox_repository=outbox,
                payload_codec=codec,
                member_access=access,
                clock=lambda: now,
            )
            handler = LaunchEventWorker(
                bookings=bookings,
                products=products,
                notifications=notification_service,
                member_access=access,
                clock=lambda: now,
            )
            async with sessions() as session, session.begin():
                await handler.handle_launch_event(
                    session,
                    event_type="launch.publish_requested.v1",
                    aggregate_id=booking_id,
                    payload={
                        "launch_booking_id": str(booking_id),
                        "product_id": str(product_id),
                    },
                )
            async with sessions() as session:
                product = await session.get(Product, product_id)
                booking = await session.get(LaunchBooking, booking_id)
                notices = list(
                    (
                        await session.scalars(
                            select(Notification).where(Notification.launch_booking_id == booking_id)
                        )
                    ).all()
                )
                events = list(
                    (
                        await session.scalars(
                            select(OutboxMessage).where(OutboxMessage.aggregate_id == booking_id)
                        )
                    ).all()
                )
                assert product is not None and product.status == "launched"
                assert booking is not None and booking.state == "launched"
                assert len(notices) == 1 and notices[0].kind == "launch_live"
                assert {event.event_type for event in events} == {
                    "launch.notice_email_requested.v1",
                    "notification.changed.v1",
                }
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(
                    delete(OutboxMessage).where(OutboxMessage.aggregate_id == booking_id)
                )
                await connection.execute(
                    delete(Notification).where(Notification.launch_booking_id == booking_id)
                )
                await connection.execute(
                    delete(LaunchBooking).where(LaunchBooking.id == booking_id)
                )
                await connection.execute(delete(Product).where(Product.id == product_id))
                await connection.execute(delete(Account).where(Account.id == founder_id))
            await database.close()

    asyncio.run(verify())


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_postgres_publication_and_cancel_cutoff_do_not_deadlock() -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 18, tzinfo=UTC)
        founder_id, product_id, booking_id = uuid4(), uuid4(), uuid4()
        database = Database.connect(os.environ["DATABASE_URL"])
        codec = EmailPayloadCodec({"launch-worker-race": b"r" * 32}, "launch-worker-race")
        worker_waiting_for_founder = asyncio.Event()

        class ObservedAuthAccessService(AuthAccessService):
            async def current_account(
                self, session: AsyncSession, account_id: UUID, *, lock: bool = False
            ) -> Any:
                task = asyncio.current_task()
                if lock and task is not None and task.get_name() == "launch-worker-race":
                    worker_waiting_for_founder.set()
                return await super().current_account(session, account_id, lock=lock)

        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                await session.execute(
                    insert(Account).values(
                        id=founder_id,
                        email_display=f"{founder_id}@example.test",
                        email_key=f"{founder_id}@example.test",
                        password_hash="integration-only-placeholder",
                        verified_at=now,
                        role="member",
                        created_at=now,
                        updated_at=now,
                    )
                )
                await session.execute(
                    insert(Product).values(
                        id=product_id,
                        founder_id=founder_id,
                        status="scheduled",
                        version=4,
                        name="Concurrent launch",
                        pitch="Publication races cancellation",
                        description="Description",
                        website_url="https://example.test/concurrent-launch",
                        website_key="https://example.test/concurrent-launch",
                        created_at=now,
                        updated_at=now,
                    )
                )
                await session.execute(
                    insert(LaunchBooking).values(
                        id=booking_id,
                        product_id=product_id,
                        founder_id=founder_id,
                        launch_date=now.date(),
                        launch_at=now,
                        state="scheduled",
                        idempotency_key="worker-cancel-race",
                        request_fingerprint="c" * 64,
                        created_at=now,
                        closed_at=None,
                    )
                )

            access = ObservedAuthAccessService()
            outbox = OutboxRepository()
            products = ProductService(
                member_access=access,
                outbox_repository=outbox,
                payload_codec=codec,
                clock=lambda: now,
            )
            bookings = LaunchBookingService(
                member_access=access,
                product_access=products,
                repository=LaunchBookingRepository(),
                outbox_repository=outbox,
                payload_codec=codec,
                clock=lambda: now,
            )
            notifications = NotificationService(
                outbox_repository=outbox,
                payload_codec=codec,
                member_access=access,
                clock=lambda: now,
            )
            handler = LaunchEventWorker(
                bookings=bookings,
                products=products,
                notifications=notifications,
                member_access=access,
                clock=lambda: now,
            )

            async def publish() -> None:
                async with sessions() as worker_session, worker_session.begin():
                    await handler.handle_launch_event(
                        worker_session,
                        event_type="launch.publish_requested.v1",
                        aggregate_id=booking_id,
                        payload={
                            "launch_booking_id": str(booking_id),
                            "product_id": str(product_id),
                        },
                    )

            async with sessions() as cancel_session:
                await cancel_session.begin()
                # Hold the founder lock while publication reaches its first
                # lock wait. Cancellation then proceeds to product/booking;
                # the worker must not already hold the booking row.
                await access.current_account(cancel_session, founder_id, lock=True)
                worker_task = asyncio.create_task(publish(), name="launch-worker-race")
                await asyncio.wait_for(worker_waiting_for_founder.wait(), timeout=5)
                with pytest.raises(LaunchConflictError):
                    await bookings.cancel(
                        cancel_session,
                        actor_id=founder_id,
                        product_id=product_id,
                        expected_version=4,
                        idempotency_key="cancel-at-launch-cutoff",
                    )
                await cancel_session.commit()
                await asyncio.wait_for(worker_task, timeout=10)

            async with sessions() as session:
                product = await session.get(Product, product_id)
                booking = await session.get(LaunchBooking, booking_id)
                assert product is not None and product.status == "launched"
                assert booking is not None and booking.state == "launched"
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(
                    delete(OutboxMessage).where(OutboxMessage.aggregate_id == booking_id)
                )
                await connection.execute(
                    delete(Notification).where(Notification.launch_booking_id == booking_id)
                )
                await connection.execute(
                    delete(LaunchBooking).where(LaunchBooking.id == booking_id)
                )
                await connection.execute(delete(Product).where(Product.id == product_id))
                await connection.execute(delete(Account).where(Account.id == founder_id))
            await database.close()

    asyncio.run(verify())
