"""Launch notice creation stays encrypted, preference-aware, and replay-safe."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.models import Account
from app.modules.launches.models import LaunchBooking
from app.modules.notifications.models import LaunchNotificationPreference, Notification
from app.modules.notifications.service import NotificationService
from app.modules.products.models import Product
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.models import OutboxMessage
from app.shared.events.outbox import OutboxRepository


class _Repository:
    def __init__(self, preferences: dict[str, bool] | None = None) -> None:
        self.preferences = preferences
        self.notices: dict[tuple[Any, str], Any] = {}

    async def find_launch_preferences(self, session: Any, *, account_id: Any) -> Any:
        if self.preferences is None:
            return None
        return SimpleNamespace(account_id=account_id, **self.preferences)

    async def save_launch_preferences(
        self, session: Any, *, account_id: Any, values: dict[str, bool], updated_at: Any
    ) -> dict[str, bool]:
        return values

    async def find_launch_notification(self, session: Any, *, booking_id: Any, kind: str) -> Any:
        return self.notices.get((booking_id, kind))

    async def add_launch_notification(self, session: Any, notice: Any) -> Any:
        self.notices[(notice.launch_booking_id, notice.kind)] = notice
        return notice, True


class _Outbox:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def add(self, session: Any, event: Any) -> Any:
        self.events.append(event)
        return event.id

    async def add_once(self, session: Any, event: Any) -> Any:
        if not any(item.id == event.id for item in self.events):
            self.events.append(event)
        return event.id


def test_launch_live_notice_uses_preferences_and_private_identifier_only_events() -> None:
    async def verify() -> None:
        booking_id, founder_id, product_id = uuid4(), uuid4(), uuid4()
        now = datetime(2026, 10, 18, tzinfo=UTC)
        repository = _Repository(
            {
                "reminder_email": True,
                "reminder_in_site": True,
                "live_email": True,
                "live_in_site": True,
                "failure_email": True,
                "failure_in_site": True,
            }
        )
        outbox = _Outbox()
        codec = EmailPayloadCodec({"launch-notice-test": b"n" * 32}, "launch-notice-test")
        service = NotificationService(
            preference_repository=repository,
            launch_notice_repository=repository,
            outbox_repository=outbox,
            idempotent_outbox_repository=outbox,
            payload_codec=codec,
            clock=lambda: now,
        )
        session = cast(AsyncSession, object())
        booking = SimpleNamespace(id=booking_id, founder_id=founder_id, product_id=product_id)

        notice = await service.record_launch_notice(session, booking=booking, kind="launch_live")

        assert notice is repository.notices[(booking_id, "launch_live")]
        assert notice.recipient_account_id == founder_id
        assert notice.product_id == product_id
        assert len(outbox.events) == 2
        assert {event.event_type for event in outbox.events} == {
            "launch.notice_email_requested.v1",
            "notification.changed.v1",
        }
        decoded = [codec.decode(event.key_id, event.encrypted_payload) for event in outbox.events]
        assert all(
            payload["recipient_account_id"] == str(founder_id)
            and payload["launch_booking_id"] == str(booking_id)
            for payload in decoded
        )
        assert all("email" not in payload and "reason" not in payload for payload in decoded)
        replay = await service.record_launch_notice(session, booking=booking, kind="launch_live")
        assert replay is notice
        assert len(outbox.events) == 2

    asyncio.run(verify())


def test_launch_notice_replay_and_disabled_channels_do_not_duplicate_delivery_intents() -> None:
    async def verify() -> None:
        booking_id, founder_id, product_id = uuid4(), uuid4(), uuid4()
        now = datetime(2026, 10, 18, tzinfo=UTC)
        repository = _Repository(
            {
                "reminder_email": True,
                "reminder_in_site": True,
                "live_email": True,
                "live_in_site": False,
                "failure_email": True,
                "failure_in_site": True,
            }
        )
        outbox = _Outbox()
        codec = EmailPayloadCodec({"launch-notice-test": b"n" * 32}, "launch-notice-test")
        service = NotificationService(
            preference_repository=repository,
            launch_notice_repository=repository,
            outbox_repository=outbox,
            idempotent_outbox_repository=outbox,
            payload_codec=codec,
            clock=lambda: now,
        )
        booking = SimpleNamespace(id=booking_id, founder_id=founder_id, product_id=product_id)
        session = cast(AsyncSession, object())

        first = await service.record_launch_notice(session, booking=booking, kind="launch_live")
        second = await service.record_launch_notice(session, booking=booking, kind="launch_live")

        assert first is None and second is None
        assert repository.notices == {}
        assert len(outbox.events) == 1
        assert outbox.events[0].event_type == "launch.notice_email_requested.v1"

    asyncio.run(verify())


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_postgres_launch_notices_dedupe_and_failure_reason_ignores_channel_preferences() -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 18, tzinfo=UTC)
        founder_id, product_id, booking_id = uuid4(), uuid4(), uuid4()
        database = Database.connect(os.environ["DATABASE_URL"])
        codec = EmailPayloadCodec({"launch-notice-pg": b"n" * 32}, "launch-notice-pg")
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
                        version=2,
                        name="Notice product",
                        pitch="A short pitch",
                        description="Description",
                        website_url="https://example.test/notice-product",
                        website_key="https://example.test/notice-product",
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
                        idempotency_key="notice-test-booking",
                        request_fingerprint="a" * 64,
                        created_at=now,
                        closed_at=None,
                    )
                )

            service = NotificationService(
                outbox_repository=OutboxRepository(),
                payload_codec=codec,
                clock=lambda: now,
            )
            booking = SimpleNamespace(id=booking_id, founder_id=founder_id, product_id=product_id)
            async with sessions() as session, session.begin():
                first = await service.record_launch_notice(
                    session, booking=booking, kind="launch_live"
                )
            async with sessions() as session, session.begin():
                replay = await service.record_launch_notice(
                    session, booking=booking, kind="launch_live"
                )
                events = list(
                    (
                        await session.scalars(
                            select(OutboxMessage).where(OutboxMessage.aggregate_id == booking_id)
                        )
                    ).all()
                )
                notices = list(
                    (
                        await session.scalars(
                            select(Notification).where(Notification.launch_booking_id == booking_id)
                        )
                    ).all()
                )
                assert first is not None and replay is not None
                assert first.id == replay.id
                assert len(events) == 2
                assert len(notices) == 1

            async with sessions() as session, session.begin():
                await service.update_launch_preferences(
                    session,
                    actor_id=founder_id,
                    values={"failure_email": False, "failure_in_site": False},
                )
                await session.execute(
                    update(LaunchBooking)
                    .where(LaunchBooking.id == booking_id)
                    .values(
                        state="missed_day",
                        failure_reason="missed_day",
                        closed_at=now,
                    )
                )
                failed_notice = await service.record_launch_notice(
                    session, booking=booking, kind="launch_failed"
                )
                saved_booking = await session.get(LaunchBooking, booking_id)
                assert failed_notice is None
                assert saved_booking is not None and saved_booking.failure_reason == "missed_day"
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(
                    delete(OutboxMessage).where(OutboxMessage.aggregate_id == booking_id)
                )
                await connection.execute(
                    delete(Notification).where(Notification.launch_booking_id == booking_id)
                )
                await connection.execute(
                    delete(LaunchNotificationPreference).where(
                        LaunchNotificationPreference.account_id == founder_id
                    )
                )
                await connection.execute(
                    delete(LaunchBooking).where(LaunchBooking.id == booking_id)
                )
                await connection.execute(delete(Product).where(Product.id == product_id))
                await connection.execute(delete(Account).where(Account.id == founder_id))
            await database.close()

    asyncio.run(verify())
