"""PostgreSQL coverage for review decisions and founder correction transitions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.modules.auth.models import Account
from app.modules.auth.staff import AuthAccessService
from app.modules.notifications.models import Notification
from app.modules.products.models import (
    Product,
    ProductAsset,
    ProductReviewDecision,
    ProductSubmission,
    ProductTopic,
    Topic,
)
from app.modules.products.policies import ProductConflictError
from app.modules.products.service import ProductReviewResult, ProductService
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.models import OutboxMessage
from conftest import IntegrationSettings
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _account(account_id: UUID, *, role: str) -> Account:
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
        payload_codec=EmailPayloadCodec({"review-flow-test": b"f" * 32}, "review-flow-test"),
        clock=lambda: now,
    )


async def _seed_product(
    sessions: async_sessionmaker[AsyncSession],
    *,
    product_id: UUID,
    submission_id: UUID,
    founder_id: UUID,
    submitted_at: datetime,
    status: str = "submitted",
    version: int = 1,
    state: str = "pending",
    complete: bool = False,
) -> None:
    async with sessions() as session, session.begin():
        await session.execute(
            insert(Product).values(
                id=product_id,
                founder_id=founder_id,
                status=status,
                version=version,
                name="Review product",
                pitch="A useful tool",
                description="Product description",
                website_url=f"https://example.test/{product_id.hex}",
                website_key=f"https://example.test/{product_id.hex}",
                created_at=submitted_at,
                updated_at=submitted_at,
            )
        )
        session.add(
            ProductSubmission(
                id=submission_id,
                product_id=product_id,
                state=state,
                submitted_at=submitted_at,
                closed_at=None if state == "pending" else submitted_at,
                product_version=version,
            )
        )
        if complete:
            topic_id = uuid4()
            session.add(
                Topic(
                    id=topic_id,
                    display_name="Review tools",
                    name_key=f"review-{topic_id.hex}",
                )
            )
            await session.flush()
            session.add_all(
                [
                    ProductAsset(
                        id=uuid4(),
                        product_id=product_id,
                        kind="logo",
                        state="clean",
                        staging_key=f"products/{founder_id}/{product_id}/logo-stage",
                        clean_key=f"products/{founder_id}/{product_id}/logo-clean",
                        media_type="image/png",
                        byte_count=100,
                        position=None,
                        expires_at=None,
                        attached_at=submitted_at,
                    ),
                    ProductAsset(
                        id=uuid4(),
                        product_id=product_id,
                        kind="screenshot",
                        state="clean",
                        staging_key=f"products/{founder_id}/{product_id}/shot-stage",
                        clean_key=f"products/{founder_id}/{product_id}/shot-clean",
                        media_type="image/png",
                        byte_count=100,
                        position=1,
                        expires_at=None,
                        attached_at=submitted_at,
                    ),
                    ProductTopic(
                        product_id=product_id,
                        topic_id=topic_id,
                        position=1,
                        selected_label="Review tools",
                    ),
                ]
            )


async def _clean(
    sessions: async_sessionmaker[AsyncSession],
    *,
    product_ids: list[UUID],
    account_ids: list[UUID],
) -> None:
    async with sessions() as session, session.begin():
        decision_ids = list(
            await session.scalars(
                select(ProductReviewDecision.id)
                .join(
                    ProductSubmission, ProductSubmission.id == ProductReviewDecision.submission_id
                )
                .where(ProductSubmission.product_id.in_(product_ids))
            )
        )
        await session.execute(
            delete(Notification).where(Notification.review_decision_id.in_(decision_ids))
        )
        await session.execute(
            delete(ProductReviewDecision).where(ProductReviewDecision.id.in_(decision_ids))
        )
        await session.execute(
            delete(OutboxMessage).where(
                OutboxMessage.aggregate_id.in_([*product_ids, *decision_ids])
            )
        )
        await session.execute(delete(Product).where(Product.id.in_(product_ids)))
        await session.execute(delete(Account).where(Account.id.in_(account_ids)))


async def _decide(
    service: ProductService,
    sessions: async_sessionmaker[AsyncSession],
    *,
    actor_id: UUID,
    product_id: UUID,
    submission_id: UUID,
    expected_version: int,
    outcome: str,
    feedback: str | None,
    idempotency_key: str,
) -> ProductReviewResult:
    async with sessions() as session, session.begin():
        return await service.decide_review(
            session,
            actor_id=actor_id,
            product_id=product_id,
            submission_id=submission_id,
            expected_version=expected_version,
            outcome=outcome,
            feedback=feedback,
            idempotency_key=idempotency_key,
        )


def test_staff_can_return_approved_product_for_changes_without_erasing_approval(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 4, tzinfo=UTC)
        database = Database.connect(integration_settings_fixture.database_url)
        staff_id, founder_id, product_id, submission_id = (uuid4() for _ in range(4))
        sessions: async_sessionmaker[AsyncSession] | None = None
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add_all(
                    [_account(staff_id, role="reviewer"), _account(founder_id, role="member")]
                )
            await _seed_product(
                sessions,
                product_id=product_id,
                submission_id=submission_id,
                founder_id=founder_id,
                submitted_at=now,
            )
            service = _service(now)

            initial = await _decide(
                service,
                sessions,
                actor_id=staff_id,
                product_id=product_id,
                submission_id=submission_id,
                expected_version=1,
                outcome="approved",
                feedback=None,
                idempotency_key=f"approve-{uuid4()}",
            )
            returned = await _decide(
                service,
                sessions,
                actor_id=staff_id,
                product_id=product_id,
                submission_id=submission_id,
                expected_version=2,
                outcome="changes_requested",
                feedback="Update the onboarding copy.",
                idempotency_key=f"return-{uuid4()}",
            )

            async with sessions() as session:
                decisions = list(
                    await session.scalars(
                        select(ProductReviewDecision)
                        .where(ProductReviewDecision.submission_id == submission_id)
                        .order_by(ProductReviewDecision.created_at, ProductReviewDecision.id)
                    )
                )
                product = await session.get(Product, product_id)
                assert initial.status == "approved" and initial.version == 2
                assert returned.status == "changes_requested" and returned.version == 3
                assert [item.outcome for item in decisions] == ["approved", "changes_requested"]
                assert [item.from_status for item in decisions] == ["submitted", "approved"]
                assert product is not None and product.status == "changes_requested"
        finally:
            if sessions is not None:
                await _clean(
                    sessions,
                    product_ids=[product_id],
                    account_ids=[staff_id, founder_id],
                )
            await database.close()


def test_identical_review_replay_returns_the_original_decision_and_changed_replay_conflicts(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 4, tzinfo=UTC)
        database = Database.connect(integration_settings_fixture.database_url)
        staff_id, founder_id, product_id, submission_id = (uuid4() for _ in range(4))
        sessions: async_sessionmaker[AsyncSession] | None = None
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add_all(
                    [_account(staff_id, role="reviewer"), _account(founder_id, role="member")]
                )
            await _seed_product(
                sessions,
                product_id=product_id,
                submission_id=submission_id,
                founder_id=founder_id,
                submitted_at=now,
            )
            service = _service(now)
            key = f"decision-{uuid4()}"
            command = {
                "actor_id": staff_id,
                "product_id": product_id,
                "submission_id": submission_id,
                "expected_version": 1,
                "outcome": "changes_requested",
                "feedback": "  Add setup guidance.  ",
                "idempotency_key": key,
            }
            original = await _decide(service, sessions, **command)
            replay = await _decide(service, sessions, **command)
            assert replay.decision.id == original.decision.id
            assert replay.version == original.version

            with pytest.raises(ProductConflictError):
                await _decide(
                    service,
                    sessions,
                    **{**command, "feedback": "Different feedback."},
                )

            async with sessions() as session:
                decisions = list(
                    await session.scalars(
                        select(ProductReviewDecision).where(
                            ProductReviewDecision.submission_id == submission_id
                        )
                    )
                )
                notices = list(
                    await session.scalars(
                        select(Notification).where(
                            Notification.review_decision_id.in_([item.id for item in decisions])
                        )
                    )
                )
                assert len(decisions) == len(notices) == 1
                assert decisions[0].feedback == "Add setup guidance."
        finally:
            if sessions is not None:
                await _clean(
                    sessions,
                    product_ids=[product_id],
                    account_ids=[staff_id, founder_id],
                )
            await database.close()


def test_competing_reviewers_resolve_one_submission_once(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 4, tzinfo=UTC)
        database = Database.connect(integration_settings_fixture.database_url)
        staff_ids = [uuid4(), uuid4()]
        founder_id, product_id, submission_id = (uuid4() for _ in range(3))
        sessions: async_sessionmaker[AsyncSession] | None = None
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add_all(
                    [
                        _account(staff_ids[0], role="reviewer"),
                        _account(staff_ids[1], role="admin"),
                        _account(founder_id, role="member"),
                    ]
                )
            await _seed_product(
                sessions,
                product_id=product_id,
                submission_id=submission_id,
                founder_id=founder_id,
                submitted_at=now,
            )
            service = _service(now)
            barrier = asyncio.Barrier(2)

            async def decide(staff_id: UUID, outcome: str) -> ProductReviewResult | Exception:
                try:
                    async with sessions() as session, session.begin():
                        await barrier.wait()
                        return await service.decide_review(
                            session,
                            actor_id=staff_id,
                            product_id=product_id,
                            submission_id=submission_id,
                            expected_version=1,
                            outcome=outcome,
                            feedback=None if outcome == "approved" else "Not accepted.",
                            idempotency_key=f"race-{staff_id.hex}",
                        )
                except Exception as error:
                    return error

            results = await asyncio.gather(
                decide(staff_ids[0], "approved"), decide(staff_ids[1], "rejected")
            )
            successes = [item for item in results if isinstance(item, ProductReviewResult)]
            failures = [item for item in results if isinstance(item, ProductConflictError)]
            assert len(successes) == len(failures) == 1
            async with sessions() as session:
                decisions = list(
                    await session.scalars(
                        select(ProductReviewDecision).where(
                            ProductReviewDecision.submission_id == submission_id
                        )
                    )
                )
                notices = list(
                    await session.scalars(
                        select(Notification).where(
                            Notification.review_decision_id == decisions[0].id
                        )
                    )
                )
                assert len(decisions) == len(notices) == 1
        finally:
            if sessions is not None:
                await _clean(
                    sessions,
                    product_ids=[product_id],
                    account_ids=[*staff_ids, founder_id],
                )
            await database.close()


class _MissingStorage:
    async def get_product_private(
        self, *, account_id: UUID, product_id: UUID, object_key: str
    ) -> tuple[bytes, str | None]:
        del account_id, product_id, object_key
        from app.shared.storage.objects import ObjectNotFound

        raise ObjectNotFound("probe key is absent")


def test_reviewed_product_cannot_be_deleted_after_later_submission_is_withdrawn(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 4, tzinfo=UTC)
        database = Database.connect(integration_settings_fixture.database_url)
        staff_id, founder_id, product_id, first_period_id = (uuid4() for _ in range(4))
        sessions: async_sessionmaker[AsyncSession] | None = None
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add_all(
                    [_account(staff_id, role="reviewer"), _account(founder_id, role="member")]
                )
            await _seed_product(
                sessions,
                product_id=product_id,
                submission_id=first_period_id,
                founder_id=founder_id,
                submitted_at=now,
                complete=True,
            )
            service = _service(now)
            requested = await _decide(
                service,
                sessions,
                actor_id=staff_id,
                product_id=product_id,
                submission_id=first_period_id,
                expected_version=1,
                outcome="changes_requested",
                feedback="Please revise.",
                idempotency_key=f"request-{uuid4()}",
            )
            async with sessions() as session, session.begin():
                submission = await service.submit_draft(
                    session,
                    actor_id=founder_id,
                    product_id=product_id,
                    expected_version=requested.version,
                )
                assert submission.id != first_period_id
            async with sessions() as session, session.begin():
                withdrawn = await service.withdraw_submission(
                    session,
                    actor_id=founder_id,
                    product_id=product_id,
                    submission_id=submission.id,
                    expected_version=requested.version + 1,
                )
                assert withdrawn.status == "draft"

            with pytest.raises(ProductConflictError, match="reviewed products"):
                async with sessions() as session, session.begin():
                    await service.delete_draft(
                        session,
                        actor_id=founder_id,
                        product_id=product_id,
                        expected_version=withdrawn.version,
                        storage=_MissingStorage(),
                    )
        finally:
            if sessions is not None:
                await _clean(
                    sessions,
                    product_ids=[product_id],
                    account_ids=[staff_id, founder_id],
                )
            await database.close()

    asyncio.run(verify())
