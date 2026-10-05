"""Owner-scoped notification inbox and read-state contracts."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from graphql import GraphQLObjectType
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from strawberry import Schema

from app.modules.auth.models import Account
from app.modules.auth.staff import AccountState
from app.modules.notifications.graphql import NotificationQuery
from app.modules.notifications.models import Notification
from app.modules.notifications.service import NotificationNotFoundError, NotificationService
from app.modules.products.models import Product, ProductReviewDecision, ProductSubmission
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.models import OutboxMessage


class _Access:
    def __init__(self, accounts: dict[Any, AccountState]) -> None:
        self.accounts = accounts

    async def current_account(self, session: Any, account_id: Any, *, lock: bool = False) -> Any:
        return self.accounts.get(account_id)


class _Repository:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.read_calls: list[tuple[Any, Any]] = []

    async def find_review_notification(self, session: Any, decision_id: Any) -> Any | None:
        return next((row for row in self.rows if row.review_decision_id == decision_id), None)

    async def add(self, session: Any, notification: Any) -> None:
        self.rows.append(notification)

    async def list_for_recipient(
        self, session: Any, *, recipient_id: Any, limit: int, after: Any
    ) -> list[Any]:
        rows = [row for row in self.rows if row.recipient_account_id == recipient_id]
        if after is not None:
            rows = [row for row in rows if (row.created_at, row.id) < after]
        rows.sort(key=lambda row: (row.created_at, row.id), reverse=True)
        return rows[:limit]

    async def count_unread(self, session: Any, *, recipient_id: Any) -> int:
        return sum(
            row.recipient_account_id == recipient_id and row.read_at is None for row in self.rows
        )

    async def get_for_recipient(
        self, session: Any, *, recipient_id: Any, notification_id: Any
    ) -> Any | None:
        return next(
            (
                row
                for row in self.rows
                if row.id == notification_id and row.recipient_account_id == recipient_id
            ),
            None,
        )

    async def mark_unread(
        self,
        session: Any,
        *,
        recipient_id: Any,
        notification_id: Any,
        read_at: datetime,
    ) -> Any:
        self.read_calls.append((recipient_id, notification_id))
        row = await self.get_for_recipient(
            session, recipient_id=recipient_id, notification_id=notification_id
        )
        if row is None or row.read_at is not None:
            return None
        row.read_at = read_at
        return row


class _Outbox:
    async def add(self, session: Any, event: Any) -> Any:
        self._events.append(event)
        return uuid4()

    def __init__(self) -> None:
        self._events: list[Any] = []


class _Codec:
    def encode(self, payload: Mapping[str, object]) -> tuple[str, bytes]:
        return "key", b"ciphertext"


def _session() -> AsyncSession:
    return cast(AsyncSession, object())


def test_notification_query_exposes_bounded_inbox_and_read_only_schema() -> None:
    schema = Schema(query=NotificationQuery)._schema
    root = schema.query_type
    assert root is not None
    assert "viewerNotificationInbox" in root.fields
    assert schema.mutation_type is None
    assert schema.subscription_type is None
    inbox = schema.get_type("NotificationInbox")
    assert isinstance(inbox, GraphQLObjectType)
    assert {"items", "unreadCount", "nextCursor"} <= inbox.fields.keys()
    entry = schema.get_type("NotificationEntry")
    assert isinstance(entry, GraphQLObjectType)
    assert "productId" in entry.fields


def test_notification_graphql_requires_an_authenticated_member_context() -> None:
    async def verify() -> None:
        result = await Schema(query=NotificationQuery).execute(
            "query { viewerNotificationInbox { unreadCount } }",
            context_value={},
        )
        assert result.data is None
        assert result.errors is not None
        assert "authentication required" in str(result.errors[0])

    asyncio.run(verify())


def test_inbox_pages_only_active_recipient_items_without_marking_them_read() -> None:
    async def verify() -> None:
        recipient, other = uuid4(), uuid4()
        now = datetime(2026, 10, 5, tzinfo=UTC)
        rows = [
            SimpleNamespace(
                id=uuid4(),
                recipient_account_id=recipient,
                product_id=uuid4(),
                review_decision_id=uuid4(),
                kind="review_approved",
                created_at=now.replace(minute=index),
                read_at=None,
            )
            for index in range(4)
        ]
        rows.append(
            SimpleNamespace(
                id=uuid4(),
                recipient_account_id=other,
                product_id=uuid4(),
                review_decision_id=uuid4(),
                kind="review_rejected",
                created_at=now,
                read_at=None,
            )
        )
        repository, outbox = _Repository(rows), _Outbox()
        service = NotificationService(
            repository=repository,
            outbox_repository=outbox,
            payload_codec=_Codec(),
            member_access=_Access(
                {
                    recipient: AccountState(recipient, True, "member", None),
                    other: AccountState(other, True, "member", None),
                }
            ),
            clock=lambda: now,
        )

        page = await service.inbox(_session(), actor_id=recipient, first=2)

        assert [item.id for item in page.items] == [rows[3].id, rows[2].id]
        assert page.unread_count == 4
        assert page.next_cursor is not None
        assert all(row.read_at is None for row in rows)
        assert outbox._events == []

        next_page = await service.inbox(
            _session(), actor_id=recipient, first=2, after=page.next_cursor
        )
        assert [item.id for item in next_page.items] == [rows[1].id, rows[0].id]
        assert next_page.next_cursor is None

    asyncio.run(verify())


def test_mark_read_changes_only_owned_item_once_and_enqueues_one_hint() -> None:
    async def verify() -> None:
        recipient, other = uuid4(), uuid4()
        notification_id, other_id = uuid4(), uuid4()
        now = datetime(2026, 10, 5, tzinfo=UTC)
        rows = [
            SimpleNamespace(
                id=notification_id,
                recipient_account_id=recipient,
                product_id=uuid4(),
                review_decision_id=uuid4(),
                kind="review_changes_requested",
                created_at=now,
                read_at=None,
            ),
            SimpleNamespace(
                id=other_id,
                recipient_account_id=recipient,
                product_id=uuid4(),
                review_decision_id=uuid4(),
                kind="review_approved",
                created_at=now,
                read_at=None,
            ),
        ]
        repository, outbox = _Repository(rows), _Outbox()
        service = NotificationService(
            repository=repository,
            outbox_repository=outbox,
            payload_codec=_Codec(),
            member_access=_Access(
                {
                    recipient: AccountState(recipient, True, "member", None),
                    other: AccountState(other, True, "member", None),
                }
            ),
            clock=lambda: now,
        )

        first = await service.mark_read(
            _session(), actor_id=recipient, notification_id=notification_id
        )
        second = await service.mark_read(
            _session(), actor_id=recipient, notification_id=notification_id
        )

        assert first.read_at == second.read_at == now
        assert rows[1].read_at is None
        assert repository.read_calls == [(recipient, notification_id)]
        assert len(outbox._events) == 1
        assert outbox._events[0].event_type == "notification.changed.v1"
        assert outbox._events[0].aggregate_id == notification_id

        with pytest.raises(NotificationNotFoundError):
            await service.mark_read(_session(), actor_id=other, notification_id=notification_id)
        assert len(outbox._events) == 1

    asyncio.run(verify())


def test_notification_reads_reject_inactive_or_missing_accounts_and_invalid_page_sizes() -> None:
    async def verify() -> None:
        active_id, suspended_id, missing_id = (uuid4() for _ in range(3))
        repository, outbox = _Repository([]), _Outbox()
        service = NotificationService(
            repository=repository,
            outbox_repository=outbox,
            payload_codec=_Codec(),
            member_access=_Access(
                {
                    active_id: AccountState(active_id, False, "member", None),
                    suspended_id: AccountState(suspended_id, True, "member", datetime.now(UTC)),
                }
            ),
        )

        with pytest.raises(ValueError, match="page size"):
            await service.inbox(_session(), actor_id=active_id, first=0)
        with pytest.raises(PermissionError):
            await service.inbox(_session(), actor_id=suspended_id)
        with pytest.raises(PermissionError):
            await service.inbox(_session(), actor_id=missing_id)

    asyncio.run(verify())


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_postgres_notification_reads_are_recipient_scoped_and_mark_once() -> None:
    async def verify() -> None:
        database = Database.connect(os.environ["DATABASE_URL"])
        staff_id, owner_id, other_id = (uuid4() for _ in range(3))
        product_ids = [uuid4() for _ in range(3)]
        submission_ids = [uuid4() for _ in range(3)]
        decision_ids = [uuid4() for _ in range(3)]
        notification_ids = [uuid4() for _ in range(3)]
        now = datetime(2026, 10, 5, 12, tzinfo=UTC)
        codec = EmailPayloadCodec({"notification-read-test": b"n" * 32}, "notification-read-test")
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                for account_id in (staff_id, owner_id, other_id):
                    session.add(
                        Account(
                            id=account_id,
                            email_display=f"{account_id}@example.test",
                            email_key=f"{account_id}@example.test",
                            password_hash="integration-only-placeholder",
                            verified_at=now,
                            created_at=now,
                            updated_at=now,
                        )
                    )
            async with sessions() as session, session.begin():
                for index, (product_id, submission_id, decision_id) in enumerate(
                    zip(product_ids, submission_ids, decision_ids, strict=True)
                ):
                    await session.execute(
                        insert(Product).values(
                            id=product_id,
                            founder_id=owner_id if index < 2 else other_id,
                            status="approved",
                            version=1,
                            name=f"Approved {index}",
                            pitch="Useful product",
                            description="Private approved content",
                            website_url=f"https://example.test/{product_id.hex}",
                            website_key=f"https://example.test/{product_id.hex}",
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
                            product_version=1,
                        )
                    )
                    await session.execute(
                        insert(ProductReviewDecision).values(
                            id=decision_id,
                            submission_id=submission_id,
                            actor_account_id=staff_id,
                            from_status="submitted",
                            outcome="approved",
                            reviewed_product_version=1,
                            feedback=None,
                            idempotency_key=f"notification-read-{decision_id}",
                            request_fingerprint="a" * 64,
                            created_at=now,
                        )
                    )
                    await session.execute(
                        insert(Notification).values(
                            id=notification_ids[index],
                            recipient_account_id=owner_id if index < 2 else other_id,
                            product_id=product_id,
                            review_decision_id=decision_id,
                            kind="review_approved",
                            created_at=now,
                            read_at=None,
                        )
                    )

            service = NotificationService(
                payload_codec=codec,
                clock=lambda: now,
            )
            async with sessions() as session:
                page = await service.inbox(session, actor_id=owner_id, first=1)
                assert len(page.items) == 1
                assert page.items[0].id == max(notification_ids[:2])
                assert page.unread_count == 2
                assert page.next_cursor is not None
                continuation = await service.inbox(
                    session, actor_id=owner_id, first=1, after=page.next_cursor
                )
                assert [item.id for item in continuation.items] == [min(notification_ids[:2])]
                assert continuation.next_cursor is None
                with pytest.raises(NotificationNotFoundError):
                    await service.mark_read(
                        session, actor_id=other_id, notification_id=notification_ids[0]
                    )

            async with sessions() as session, session.begin():
                first = await service.mark_read(
                    session, actor_id=owner_id, notification_id=notification_ids[0]
                )
                second = await service.mark_read(
                    session, actor_id=owner_id, notification_id=notification_ids[0]
                )
                assert first.read_at == second.read_at == now
            async with sessions() as session:
                notices = list(
                    await session.scalars(
                        select(Notification)
                        .where(Notification.recipient_account_id == owner_id)
                        .order_by(Notification.id)
                    )
                )
                assert sum(notice.read_at is None for notice in notices) == 1
                events = list(
                    await session.scalars(
                        select(OutboxMessage).where(
                            OutboxMessage.aggregate_id == notification_ids[0],
                            OutboxMessage.event_type == "notification.changed.v1",
                        )
                    )
                )
                assert len(events) == 1
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(
                    delete(Notification).where(Notification.id.in_(notification_ids))
                )
                await connection.execute(
                    delete(OutboxMessage).where(OutboxMessage.aggregate_id.in_(notification_ids))
                )
                await connection.execute(
                    delete(ProductReviewDecision).where(ProductReviewDecision.id.in_(decision_ids))
                )
                await connection.execute(
                    delete(ProductSubmission).where(ProductSubmission.id.in_(submission_ids))
                )
                await connection.execute(delete(Product).where(Product.id.in_(product_ids)))
                await connection.execute(
                    delete(Account).where(Account.id.in_((staff_id, owner_id, other_id)))
                )
            await database.close()

    asyncio.run(verify())
