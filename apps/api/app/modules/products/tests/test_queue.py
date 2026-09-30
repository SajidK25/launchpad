"""Staff-only pending queue ordering, access, and live review flags."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.models import Account
from app.modules.auth.staff import AccountState, AuthAccessService
from app.modules.products.models import Product, ProductSubmission
from app.modules.products.policies import (
    ProductForbiddenError,
    ProductNotFoundError,
    require_staff_reviewer,
)
from app.modules.products.service import ProductService
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec


class _CountingAccess(AuthAccessService):
    def __init__(self) -> None:
        super().__init__()
        self.batch_calls: list[tuple[UUID, ...]] = []

    async def founder_states(
        self, session: AsyncSession, account_ids: Sequence[UUID]
    ) -> dict[UUID, AccountState]:
        self.batch_calls.append(tuple(account_ids))
        return await super().founder_states(session, account_ids)


@pytest.mark.parametrize(
    ("verified", "role", "suspended"),
    [
        (False, "reviewer", False),
        (True, "member", False),
        (True, "admin", True),
    ],
)
def test_staff_read_policy_rejects_unverified_nonstaff_or_suspended(
    verified: bool, role: str, suspended: bool
) -> None:
    state = AccountState(
        account_id=uuid4(),
        verified=verified,
        role=role,
        suspended_at=datetime.now(UTC) if suspended else None,
    )
    with pytest.raises(ProductForbiddenError):
        require_staff_reviewer(state)


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_review_queue_is_pending_oldest_first_with_live_staff_flags() -> None:
    async def verify() -> None:
        database = Database.connect(os.environ["DATABASE_URL"])
        staff_id, founder_id, other_id = uuid4(), uuid4(), uuid4()
        product_ids = [uuid4() for _ in range(4)]
        submission_ids = [uuid4() for _ in range(3)]
        now = datetime.now(UTC)
        website = f"https://example.test/{product_ids[0]}"
        access = _CountingAccess()
        service = ProductService(
            member_access=access,
            payload_codec=EmailPayloadCodec({"queue-test": b"q" * 32}, "queue-test"),
        )
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                for account_id, role, suspended in (
                    (staff_id, "reviewer", False),
                    (founder_id, "member", True),
                    (other_id, "member", False),
                ):
                    session.add(
                        Account(
                            id=account_id,
                            email_display=f"{account_id}@example.test",
                            email_key=f"{account_id}@example.test",
                            password_hash="integration-only-placeholder",
                            verified_at=now,
                            role=role,
                            suspended_at=now if suspended else None,
                            created_at=now,
                            updated_at=now,
                        )
                    )
            async with sessions() as session, session.begin():
                await session.execute(
                    insert(Product).values(
                        [
                            {
                                "id": product_id,
                                "founder_id": founder_id if index < 2 else other_id,
                                "status": "draft" if index == 3 else "submitted",
                                "version": index + 1,
                                "name": f"Product {index}",
                                "pitch": "A useful launch",
                                "description": "Description",
                                "website_url": website
                                if index < 2
                                else f"https://example.test/{product_id}",
                                "website_key": website
                                if index < 2
                                else f"https://example.test/{product_id}",
                                "created_at": now,
                                "updated_at": now,
                            }
                            for index, product_id in enumerate(product_ids)
                        ]
                    )
                )
                session.add_all(
                    ProductSubmission(
                        id=submission_ids[index],
                        product_id=product_ids[index],
                        state="pending",
                        submitted_at=now + timedelta(minutes=index),
                        product_version=index + 1,
                    )
                    for index in range(3)
                )
                session.add(
                    ProductSubmission(
                        id=uuid4(),
                        product_id=product_ids[0],
                        state="withdrawn",
                        submitted_at=now - timedelta(days=1),
                        closed_at=now - timedelta(hours=1),
                        product_version=0,
                    )
                )
            async with sessions() as session:
                first = await service.staff_queue(session, actor_id=staff_id, first=2)
                assert [item.product.id for item in first.items] == product_ids[:2]
                assert first.next_cursor is not None
                assert first.items[0].founder_suspended
                assert first.items[0].possible_duplicate
                assert first.items[1].possible_duplicate
                assert access.batch_calls == [(founder_id, founder_id)]
                second = await service.staff_queue(
                    session, actor_id=staff_id, first=2, after=first.next_cursor
                )
                assert [item.product.id for item in second.items] == [product_ids[2]]
                assert second.next_cursor is None
                detail = await service.staff_detail(
                    session, actor_id=staff_id, product_id=product_ids[0]
                )
                assert detail.submission.id == submission_ids[0]
                assert detail.submission.product_version == 1
                with pytest.raises(ProductNotFoundError):
                    await service.staff_detail(
                        session, actor_id=staff_id, product_id=product_ids[3]
                    )
                with pytest.raises(ProductForbiddenError):
                    await service.staff_queue(session, actor_id=other_id)
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(delete(Product).where(Product.id.in_(product_ids)))
                await connection.execute(
                    delete(Account).where(Account.id.in_((staff_id, founder_id, other_id)))
                )
            await database.close()

    asyncio.run(verify())
