"""PostgreSQL integration checks for atomic review and launch booking closure."""

from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.auth.models import Account
from app.modules.auth.staff import AuthAccessService
from app.modules.launches.models import LaunchBooking
from app.modules.launches.repository import LaunchBookingRepository
from app.modules.notifications.models import Notification
from app.modules.products.models import Product, ProductReviewDecision, ProductSubmission
from app.modules.products.service import ProductService
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec


class _NoNotices:
    async def record_review_outcome(self, session: Any, **values: Any) -> object:
        return object()


class _FailInvalidator:
    async def invalidate_for_review(self, session: Any, *, product_id: UUID, now: datetime) -> bool:
        raise RuntimeError("test invalidator failure")


def _service(now: datetime, *, invalidator: Any | None = None) -> ProductService:
    return ProductService(
        member_access=AuthAccessService(),
        payload_codec=EmailPayloadCodec({"review-launch": b"r" * 32}, "review-launch"),
        review_notifications=_NoNotices(),
        launch_booking_access=invalidator,
        clock=lambda: now,
    )


async def _seed_review(
    session: Any,
    *,
    now: datetime,
    reviewer_id: UUID,
    founder_id: UUID,
    product_id: UUID,
    submission_id: UUID,
    booking_id: UUID,
) -> None:
    await session.execute(
        insert(Account).values(
            id=reviewer_id,
            email_display=f"{reviewer_id}@example.test",
            email_key=f"{reviewer_id}@example.test",
            password_hash="integration-only-placeholder",
            verified_at=now,
            role="reviewer",
            created_at=now,
            updated_at=now,
        )
    )
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
            name="Scheduled review product",
            pitch="Scheduled pitch",
            description="Private description",
            website_url="https://example.test/scheduled",
            website_key="https://example.test/scheduled",
            created_at=now,
            updated_at=now,
        )
    )
    await session.execute(
        insert(ProductSubmission).values(
            id=submission_id,
            product_id=product_id,
            state="approved",
            submitted_at=now,
            closed_at=now,
            product_version=3,
        )
    )
    launch_date = date(2026, 10, 20)
    await session.execute(
        insert(LaunchBooking).values(
            id=booking_id,
            product_id=product_id,
            founder_id=founder_id,
            launch_date=launch_date,
            launch_at=datetime.combine(launch_date, datetime.min.time(), tzinfo=UTC),
            state="scheduled",
            idempotency_key=f"booking-{booking_id.hex}",
            request_fingerprint=hashlib.sha256(booking_id.bytes).hexdigest(),
            created_at=now,
            closed_at=None,
        )
    )


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_scheduled_return_closes_booking_and_review_replay_is_idempotent() -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 17, 12, tzinfo=UTC)
        reviewer_id, founder_id, product_id, submission_id, booking_id = (uuid4() for _ in range(5))
        database = Database.connect(os.environ["DATABASE_URL"])
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                await _seed_review(
                    session,
                    now=now,
                    reviewer_id=reviewer_id,
                    founder_id=founder_id,
                    product_id=product_id,
                    submission_id=submission_id,
                    booking_id=booking_id,
                )
            service = _service(now)
            async with sessions() as session, session.begin():
                result = await service.decide_review(
                    session,
                    actor_id=reviewer_id,
                    product_id=product_id,
                    submission_id=submission_id,
                    expected_version=4,
                    outcome="changes_requested",
                    feedback="Please revise the launch copy",
                    idempotency_key="scheduled-return",
                )
                assert result.status == "changes_requested" and result.version == 5
                assert (
                    await LaunchBookingRepository().active_for_product(
                        session, product_id=product_id
                    )
                    is None
                )
            async with sessions() as session, session.begin():
                replay = await service.decide_review(
                    session,
                    actor_id=reviewer_id,
                    product_id=product_id,
                    submission_id=submission_id,
                    expected_version=4,
                    outcome="changes_requested",
                    feedback="Please revise the launch copy",
                    idempotency_key="scheduled-return",
                )
                assert replay.decision.id == result.decision.id
                product = await session.scalar(select(Product).where(Product.id == product_id))
                booking = await session.scalar(
                    select(LaunchBooking).where(LaunchBooking.id == booking_id)
                )
                decisions = await session.scalar(
                    select(ProductReviewDecision.id).where(
                        ProductReviewDecision.submission_id == submission_id
                    )
                )
                assert product is not None and product.status == "changes_requested"
                assert booking is not None and booking.state == "returned_for_changes"
                assert decisions == result.decision.id
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(
                    delete(LaunchBooking).where(LaunchBooking.id == booking_id)
                )
                await connection.execute(
                    delete(Notification).where(Notification.product_id == product_id)
                )
                await connection.execute(
                    delete(ProductReviewDecision).where(
                        ProductReviewDecision.submission_id == submission_id
                    )
                )
                await connection.execute(
                    delete(ProductSubmission).where(ProductSubmission.id == submission_id)
                )
                await connection.execute(delete(Product).where(Product.id == product_id))
                await connection.execute(
                    delete(Account).where(Account.id.in_([reviewer_id, founder_id]))
                )
            await database.engine.dispose()

    asyncio.run(verify())


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_review_invalidation_failure_rolls_back_review_and_booking() -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 17, 12, tzinfo=UTC)
        reviewer_id, founder_id, product_id, submission_id, booking_id = (uuid4() for _ in range(5))
        database = Database.connect(os.environ["DATABASE_URL"])
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                await _seed_review(
                    session,
                    now=now,
                    reviewer_id=reviewer_id,
                    founder_id=founder_id,
                    product_id=product_id,
                    submission_id=submission_id,
                    booking_id=booking_id,
                )
            service = _service(now, invalidator=_FailInvalidator())
            async with sessions() as session:
                with pytest.raises(RuntimeError):
                    async with session.begin():
                        await service.decide_review(
                            session,
                            actor_id=reviewer_id,
                            product_id=product_id,
                            submission_id=submission_id,
                            expected_version=4,
                            outcome="changes_requested",
                            feedback="Please revise the launch copy",
                            idempotency_key="scheduled-return-fail",
                        )
            async with sessions() as session:
                product = await session.scalar(select(Product).where(Product.id == product_id))
                booking = await session.scalar(
                    select(LaunchBooking).where(LaunchBooking.id == booking_id)
                )
                decision_count = await session.scalar(
                    select(ProductReviewDecision.id).where(
                        ProductReviewDecision.submission_id == submission_id
                    )
                )
                assert product is not None and product.status == "scheduled"
                assert booking is not None and booking.state == "scheduled"
                assert decision_count is None
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(
                    delete(LaunchBooking).where(LaunchBooking.id == booking_id)
                )
                await connection.execute(
                    delete(ProductReviewDecision).where(
                        ProductReviewDecision.submission_id == submission_id
                    )
                )
                await connection.execute(
                    delete(ProductSubmission).where(ProductSubmission.id == submission_id)
                )
                await connection.execute(delete(Product).where(Product.id == product_id))
                await connection.execute(
                    delete(Account).where(Account.id.in_([reviewer_id, founder_id]))
                )
            await database.engine.dispose()

    asyncio.run(verify())
