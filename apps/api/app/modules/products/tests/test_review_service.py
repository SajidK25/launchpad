"""Unit and PostgreSQL coverage for product review transitions."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.auth.models import Account
from app.modules.auth.staff import AuthAccessService
from app.modules.notifications.models import Notification
from app.modules.products.models import Product, ProductReviewDecision, ProductSubmission
from app.modules.products.schemas import ProductContentInput
from app.modules.products.service import ProductService
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.models import OutboxMessage


def _account(account_id: UUID, *, role: str = "member") -> Account:
    now = datetime.now(UTC)
    return Account(
        id=account_id,
        email_display=f"{account_id}@example.test",
        email_key=f"{account_id}@example.test",
        password_hash="integration-only-placeholder",
        verified_at=now,
        role=role,
        created_at=now,
        updated_at=now,
    )


def _service(now: datetime) -> ProductService:
    return ProductService(
        member_access=AuthAccessService(),
        payload_codec=EmailPayloadCodec({"review-test": b"r" * 32}, "review-test"),
        clock=lambda: now,
    )


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
@pytest.mark.parametrize(
    ("outcome", "feedback"),
    [("approved", None), ("rejected", "Not eligible"), ("changes_requested", "Fix the copy")],
)
def test_resolves_each_pending_outcome_with_decision_and_founder_notice(
    outcome: str,
    feedback: str | None,
) -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 4, tzinfo=UTC)
        database = Database.connect(os.environ["DATABASE_URL"])
        staff_id, founder_id, product_id, submission_id = (uuid4() for _ in range(4))
        decision_id: UUID | None = None
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add_all([_account(staff_id, role="reviewer"), _account(founder_id)])
            async with sessions() as session, session.begin():
                await session.execute(
                    insert(Product).values(
                        id=product_id,
                        founder_id=founder_id,
                        status="submitted",
                        version=1,
                        name="Review product",
                        pitch="A useful tool",
                        description="Product description",
                        website_url="https://example.test/review",
                        website_key="https://example.test/review",
                        created_at=now,
                        updated_at=now,
                    )
                )
                session.add(
                    ProductSubmission(
                        id=submission_id,
                        product_id=product_id,
                        state="pending",
                        submitted_at=now,
                        closed_at=None,
                        product_version=1,
                    )
                )

            service = _service(now)
            async with sessions() as session, session.begin():
                result = await service.decide_review(
                    session,
                    actor_id=staff_id,
                    product_id=product_id,
                    submission_id=submission_id,
                    expected_version=1,
                    outcome=outcome,
                    feedback=feedback,
                    idempotency_key=f"review-{uuid4()}",
                )
                decision_id = result.decision.id
                assert result.status == outcome
                assert result.version == 2

            async with sessions() as session:
                product = await session.get(Product, product_id)
                period = await session.get(ProductSubmission, submission_id)
                decision = await session.get(ProductReviewDecision, decision_id)
                notice = await session.scalar(
                    select(Notification).where(Notification.review_decision_id == decision_id)
                )
                events = list(
                    await session.scalars(
                        select(OutboxMessage.event_type).where(
                            OutboxMessage.aggregate_id == decision_id
                        )
                    )
                )
                assert product is not None and product.status == outcome and product.version == 2
                assert period is not None and period.state == outcome and period.closed_at == now
                assert decision is not None and decision.actor_account_id == staff_id
                assert decision.feedback == feedback and decision.created_at == now
                assert notice is not None and notice.recipient_account_id == founder_id
                assert len(events) == 2
        finally:
            if "sessions" in locals():
                async with sessions() as session, session.begin():
                    event_ids = [product_id]
                    if decision_id is not None:
                        event_ids.append(decision_id)
                        await session.execute(
                            delete(Notification).where(
                                Notification.review_decision_id == decision_id
                            )
                        )
                        await session.execute(
                            delete(ProductReviewDecision).where(
                                ProductReviewDecision.id == decision_id
                            )
                        )
                    await session.execute(
                        delete(OutboxMessage).where(OutboxMessage.aggregate_id.in_(event_ids))
                    )
                    await session.execute(delete(Product).where(Product.id == product_id))
                    await session.execute(
                        delete(Account).where(Account.id.in_([staff_id, founder_id]))
                    )
            await database.close()

    asyncio.run(verify())


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_founder_can_edit_changes_requested_product_without_leaving_that_state() -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 4, tzinfo=UTC)
        database = Database.connect(os.environ["DATABASE_URL"])
        founder_id, product_id, submission_id = (uuid4() for _ in range(3))
        sessions = None
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add(_account(founder_id))
            async with sessions() as session, session.begin():
                await session.execute(
                    insert(Product).values(
                        id=product_id,
                        founder_id=founder_id,
                        status="changes_requested",
                        version=1,
                        name="Needs correction",
                        pitch="A useful tool",
                        description="Product description",
                        website_url="https://example.test/correction",
                        website_key="https://example.test/correction",
                        created_at=now,
                        updated_at=now,
                    )
                )
                session.add(
                    ProductSubmission(
                        id=submission_id,
                        product_id=product_id,
                        state="changes_requested",
                        submitted_at=now,
                        closed_at=now,
                        product_version=1,
                    )
                )

            service = _service(now)
            async with sessions() as session, session.begin():
                updated = await service.save_draft(
                    session,
                    actor_id=founder_id,
                    product_id=product_id,
                    expected_version=1,
                    content=ProductContentInput(name="Corrected title"),
                )
                assert updated.status == "changes_requested"
                assert updated.version == 2
                assert updated.content.name == "Corrected title"
        finally:
            if sessions is not None:
                async with sessions() as session, session.begin():
                    decision_ids = list(
                        await session.scalars(
                            select(ProductReviewDecision.id)
                            .join(
                                ProductSubmission,
                                ProductSubmission.id == ProductReviewDecision.submission_id,
                            )
                            .where(ProductSubmission.product_id == product_id)
                        )
                    )
                    await session.execute(
                        delete(Notification).where(
                            Notification.review_decision_id.in_(decision_ids)
                        )
                    )
                    await session.execute(
                        delete(ProductReviewDecision).where(
                            ProductReviewDecision.id.in_(decision_ids)
                        )
                    )
                    await session.execute(
                        delete(OutboxMessage).where(
                            OutboxMessage.aggregate_id.in_([product_id, *decision_ids])
                        )
                    )
                    await session.execute(delete(Product).where(Product.id == product_id))
                    await session.execute(delete(Account).where(Account.id == founder_id))
            await database.close()

    asyncio.run(verify())
