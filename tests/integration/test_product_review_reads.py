"""PostgreSQL-backed GraphQL coverage for private review reads."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.graphql import Query
from app.modules.auth.models import Account
from app.modules.auth.sessions import MemberContext
from app.modules.auth.staff import AuthAccessService
from app.modules.products.models import (
    Product,
    ProductAsset,
    ProductReviewDecision,
    ProductSubmission,
)
from app.modules.products.policies import ProductNotFoundError, create_product_media_signature
from app.modules.products.service import ProductService
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from conftest import IntegrationSettings
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import async_sessionmaker
from strawberry import Schema


def test_review_graphql_reads_owner_outcomes_and_pages_only_approved_products(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        now = datetime(2026, 10, 4, tzinfo=UTC)
        staff_id, founder_id, other_founder_id = (uuid4() for _ in range(3))
        product_ids = [uuid4() for _ in range(5)]
        submission_ids = [uuid4() for _ in product_ids]
        decision_ids: list[UUID] = []
        sessions = None
        codec = EmailPayloadCodec({"review-read-test": b"r" * 32}, "review-read-test")
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                for account_id, role in (
                    (staff_id, "reviewer"),
                    (founder_id, "member"),
                    (other_founder_id, "member"),
                ):
                    session.add(
                        Account(
                            id=account_id,
                            email_display=f"{account_id}@example.com",
                            email_key=f"{account_id}@example.com",
                            password_hash="integration-only-placeholder",
                            verified_at=now,
                            role=role,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                states = ("approved", "approved", "changes_requested", "rejected", "submitted")
                for index, (product_id, submission_id, status) in enumerate(
                    zip(product_ids, submission_ids, states, strict=True)
                ):
                    approved_at = now - timedelta(minutes=index)
                    founder = other_founder_id if index == 1 else founder_id
                    await session.execute(
                        insert(Product).values(
                            id=product_id,
                            founder_id=founder,
                            status=status,
                            version=3 if index == 2 else 1,
                            name=f"Private product {index}",
                            pitch="A useful tool",
                            description="Private review detail.",
                            website_url=f"https://example.test/{product_id.hex}",
                            website_key=f"https://example.test/{product_id.hex}",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    period_state = "pending" if status == "submitted" else status
                    await session.execute(
                        insert(ProductSubmission).values(
                            id=submission_id,
                            product_id=product_id,
                            state=period_state,
                            submitted_at=now - timedelta(days=1),
                            closed_at=None if period_state == "pending" else approved_at,
                            product_version=2 if index == 2 else 1,
                        )
                    )
                    outcomes = (
                        (("submitted", "approved", None),)
                        if status == "approved"
                        else (
                            (
                                ("submitted", "approved", None),
                                (
                                    "approved",
                                    "changes_requested",
                                    "Add clearer setup instructions.",
                                ),
                            )
                            if status == "changes_requested"
                            else (("submitted", "rejected", "The launch details need work."),)
                            if status == "rejected"
                            else ()
                        )
                    )
                    for decision_index, (from_status, outcome, feedback) in enumerate(outcomes):
                        decision_id = uuid4()
                        decision_ids.append(decision_id)
                        await session.execute(
                            insert(ProductReviewDecision).values(
                                id=decision_id,
                                submission_id=submission_id,
                                actor_account_id=staff_id,
                                from_status=from_status,
                                outcome=outcome,
                                reviewed_product_version=decision_index + 1,
                                feedback=feedback,
                                idempotency_key=f"read-{index}-{decision_index}",
                                request_fingerprint="a" * 64,
                                created_at=approved_at + timedelta(seconds=decision_index),
                            )
                        )

            schema = Schema(query=Query)

            def context(account_id: UUID | None, role: str = "member") -> dict[str, object]:
                return {
                    "member": (
                        MemberContext(
                            account_id=account_id,
                            verified=True,
                            session_id=uuid4(),
                            role=role,
                        )
                        if account_id is not None
                        else None
                    ),
                    "session_secret": "integration-read-session",
                    "session_factory": sessions,
                    "product_service_factory": lambda: ProductService(
                        member_access=AuthAccessService(), payload_codec=codec
                    ),
                }

            async def query(text: str, actor: UUID | None, role: str = "member"):
                return await schema.execute(text, context_value=context(actor, role))

            first = await query(
                "query { approvedReviews(first: 1) { items { product { id status } "
                "submission { id productVersion } approvedAt } nextCursor } }",
                staff_id,
                "reviewer",
            )
            assert first.errors is None
            first_page = first.data["approvedReviews"]
            assert len(first_page["items"]) == 1
            assert first_page["items"][0]["product"]["status"] == "approved"
            cursor = first_page["nextCursor"]
            assert cursor is not None
            second = await query(
                f'query {{ approvedReviews(first: 1, after: "{cursor}") '
                "{ items { product { id } } nextCursor } }",
                staff_id,
                "reviewer",
            )
            assert second.errors is None
            assert len(second.data["approvedReviews"]["items"]) == 1
            assert second.data["approvedReviews"]["nextCursor"] is None

            detail = await query(
                f'query {{ reviewProduct(id: "{product_ids[0]}") '
                "{ product { summary { id status } } submission { id } } }",
                staff_id,
                "reviewer",
            )
            assert detail.errors is None
            assert detail.data["reviewProduct"]["product"]["summary"]["status"] == "approved"

            owner = await query(
                f'query {{ viewerProduct(id: "{product_ids[2]}") '
                "{ summary { status } reviewOutcome { status feedback } } }",
                founder_id,
            )
            assert owner.errors is None
            outcome = owner.data["viewerProduct"]["reviewOutcome"]
            assert outcome["status"] == "changes_requested"
            assert outcome["feedback"] == "Add clearer setup instructions."
            approved_outcome = await query(
                f'query {{ viewerProduct(id: "{product_ids[0]}") '
                "{ reviewOutcome { status feedback } } }",
                founder_id,
            )
            assert approved_outcome.errors is None
            assert approved_outcome.data["viewerProduct"]["reviewOutcome"] == {
                "status": "approved",
                "feedback": None,
            }
            rejected_outcome = await query(
                f'query {{ viewerProduct(id: "{product_ids[3]}") '
                "{ reviewOutcome { status feedback } } }",
                founder_id,
            )
            assert rejected_outcome.errors is None
            assert rejected_outcome.data["viewerProduct"]["reviewOutcome"] == {
                "status": "rejected",
                "feedback": "The launch details need work.",
            }
            foreign = await query(
                f'query {{ viewerProduct(id: "{product_ids[1]}") {{ summary {{ id }} }} }}',
                founder_id,
            )
            assert foreign.errors is None and foreign.data["viewerProduct"] is None
            for index in (0, 2, 3):
                for actor_id in (None, other_founder_id):
                    hidden = await query(
                        f'query {{ viewerProduct(id: "{product_ids[index]}") '
                        "{ summary { id status } reviewOutcome { status feedback } } }",
                        actor_id,
                    )
                    if actor_id is None:
                        assert hidden.data["viewerProduct"] is None and hidden.errors
                    else:
                        assert hidden.errors is None and hidden.data["viewerProduct"] is None

            asset_ids: dict[int, UUID] = {}
            async with sessions() as session, session.begin():
                for index in (0, 2, 3):
                    asset_id = uuid4()
                    asset_ids[index] = asset_id
                    session.add(
                        ProductAsset(
                            id=asset_id,
                            product_id=product_ids[index],
                            kind="logo",
                            state="clean",
                            staging_key=f"product-staging/{founder_id.hex}/{asset_id.hex}",
                            clean_key=f"product-clean/{founder_id.hex}/{asset_id.hex}",
                            media_type="image/png",
                            byte_count=128,
                            position=None,
                            expires_at=now + timedelta(days=1),
                            attached_at=now,
                        )
                    )
            service = ProductService(member_access=AuthAccessService(), payload_codec=codec)
            session_secret = "not-the-owning-session"
            signature_expiry = int(datetime.now(UTC).timestamp()) + 120

            class _Storage:
                async def get_product_private(
                    self, *, account_id: UUID, product_id: UUID, object_key: str
                ) -> tuple[bytes, str | None]:
                    del account_id, product_id, object_key
                    raise AssertionError("foreign media access must stop before storage")

            for index, asset_id in asset_ids.items():
                path = f"/api/v1/products/{product_ids[index]}/assets/{asset_id}"
                signature = create_product_media_signature(session_secret, path, signature_expiry)
                for actor_id in (other_founder_id, uuid4()):
                    with pytest.raises(ProductNotFoundError):
                        async with sessions() as session, session.begin():
                            await service.read_private_asset(
                                session,
                                actor_id=actor_id,
                                session_secret=session_secret,
                                product_id=product_ids[index],
                                asset_id=asset_id,
                                expires_at=signature_expiry,
                                signature=signature,
                                storage=_Storage(),
                            )
            denied_approved_list = await query(
                "query { approvedReviews { items { product { id } } } }", founder_id
            )
            assert denied_approved_list.data is None and denied_approved_list.errors
            rejected = await query(
                f'query {{ reviewProduct(id: "{product_ids[3]}") {{ submission {{ id }} }} }}',
                staff_id,
                "reviewer",
            )
            assert rejected.errors is None and rejected.data["reviewProduct"] is None
        finally:
            if sessions is not None:
                async with sessions() as session, session.begin():
                    await session.execute(
                        delete(ProductReviewDecision).where(
                            ProductReviewDecision.id.in_(decision_ids)
                        )
                    )
                    await session.execute(delete(Product).where(Product.id.in_(product_ids)))
                    await session.execute(
                        delete(Account).where(
                            Account.id.in_((staff_id, founder_id, other_founder_id))
                        )
                    )
            await database.close()

    asyncio.run(verify())
