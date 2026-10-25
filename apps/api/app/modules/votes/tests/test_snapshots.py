"""UTC ranking snapshot lifecycle contracts."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.models import Account
from app.modules.auth.staff import AuthAccessService
from app.modules.products.models import Product
from app.modules.products.service import ProductService
from app.modules.votes.models import (
    DailyRankingEntry,
    DailyRankingSnapshot,
    Vote,
    VotingFeatureState,
)
from app.modules.votes.repository import VoteRepository
from app.modules.votes.service import VoteSnapshotService
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.outbox import OutboxEvent


class _Products:
    def __init__(self, products: tuple[SimpleNamespace, ...]) -> None:
        self.products = products

    async def public_launches(
        self,
        _session: AsyncSession,
        *,
        requested_date: date | None,
        first: int = 20,
        after: str | None = None,
    ) -> SimpleNamespace:
        del requested_date, first, after
        return SimpleNamespace(items=self.products, next_cursor=None)


class _Repository:
    def __init__(self, values: dict[UUID, tuple[int, Decimal]]) -> None:
        self.values = values
        self.enabled_from = date(2026, 10, 1)
        self.entries: dict[date, list[tuple[UUID, int, Decimal, int]]] = {}

    async def voting_enabled_from(self, _session: AsyncSession) -> date:
        return self.enabled_from

    async def snapshot_values_for_products(
        self,
        _session: AsyncSession,
        *,
        product_ids: tuple[UUID, ...],
        cutoff_at: datetime,
    ) -> dict[UUID, tuple[int, Decimal]]:
        del cutoff_at
        return {
            product_id: self.values.get(product_id, (0, Decimal(0))) for product_id in product_ids
        }

    async def create_daily_snapshot(
        self,
        _session: AsyncSession,
        *,
        launch_date: date,
        cutoff_at: datetime,
        created_at: datetime,
        entries: list[tuple[UUID, int, Decimal, int]],
    ) -> UUID:
        del cutoff_at, created_at
        self.entries.setdefault(launch_date, entries)
        return uuid5(NAMESPACE_URL, f"launchpad:daily-ranking:{launch_date.isoformat()}")


class _Codec:
    def encode(self, payload: Any) -> tuple[str, bytes]:
        return "test", repr(sorted(payload.items())).encode()

    def decode(self, _key_id: str, _ciphertext: bytes) -> dict[str, Any]:
        return {}


class _Outbox:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def add_once(self, _session: AsyncSession, event: OutboxEvent) -> UUID:
        self.events.append(event)
        assert event.id is not None
        return event.id


def test_freezes_final_ranking_at_utc_cutoff() -> None:
    async def verify() -> None:
        launch_date = date(2026, 10, 24)
        products = (
            SimpleNamespace(id=UUID(int=3), name="Alpha"),
            SimpleNamespace(id=UUID(int=2), name="Beta"),
            SimpleNamespace(id=UUID(int=1), name="Zero"),
        )
        repository = _Repository(
            {
                products[0].id: (1, Decimal("0.5")),
                products[1].id: (2, Decimal("0.5")),
            }
        )
        service = VoteSnapshotService(
            products=cast(Any, _Products(products)),
            repository=cast(Any, repository),
            outbox=cast(Any, _Outbox()),
            codec=cast(Any, _Codec()),
            clock=lambda: datetime(2026, 10, 25, 0, 0, 1, tzinfo=UTC),
        )

        await service.handle_outbox_event(
            cast(AsyncSession, object()),
            event_type="vote.snapshot_due.v1",
            aggregate_id=uuid5(NAMESPACE_URL, f"launchpad:daily-ranking:{launch_date.isoformat()}"),
            payload={"launch_date": launch_date.isoformat()},
        )

        assert repository.entries[launch_date] == [
            (products[1].id, 1, Decimal("0.5"), 2),
            (products[0].id, 2, Decimal("0.5"), 1),
            (products[2].id, 3, Decimal(0), 0),
        ]

    asyncio.run(verify())


def test_schedule_uses_one_stable_due_event_per_voting_date() -> None:
    async def verify() -> None:
        launch_date = date(2026, 10, 24)
        repository = _Repository({})
        outbox = _Outbox()
        service = VoteSnapshotService(
            products=cast(Any, _Products(())),
            repository=cast(Any, repository),
            outbox=cast(Any, outbox),
            codec=cast(Any, _Codec()),
            clock=lambda: datetime(2026, 10, 24, 12, tzinfo=UTC),
        )

        await service.schedule_for_launch_date(cast(AsyncSession, object()), launch_date)
        await service.schedule_for_launch_date(cast(AsyncSession, object()), launch_date)

        assert len(outbox.events) == 2
        first, second = outbox.events
        expected_id = uuid5(NAMESPACE_URL, f"launchpad:daily-ranking:{launch_date.isoformat()}")
        assert first.id == second.id == expected_id
        assert first.event_type == second.event_type == "vote.snapshot_due.v1"
        assert first.available_at == second.available_at == datetime(2026, 10, 25, tzinfo=UTC)
        assert first.aggregate_id == second.aggregate_id == expected_id

    asyncio.run(verify())


def test_snapshot_uses_cutoff_state_and_stays_immutable_after_later_invalidation() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("PostgreSQL snapshot coverage runs in the integration environment")

    async def verify() -> None:
        database = Database.connect(database_url)
        session_factory = async_sessionmaker(database.engine, expire_on_commit=False)
        launch_date = date(2026, 10, 23)
        cutoff = datetime(2026, 10, 24, tzinfo=UTC)
        now = datetime(2026, 10, 24, 12, tzinfo=UTC)
        founders = [uuid4(), uuid4(), uuid4()]
        voters = [uuid4(), uuid4()]
        product_ids = [uuid4(), uuid4(), uuid4()]
        vote_ids: list[UUID] = []
        existing_enabled_from: date | None = None
        codec = EmailPayloadCodec({"snapshot-test": b"s" * 32}, "snapshot-test")
        repository = VoteRepository()
        products = ProductService(
            member_access=AuthAccessService(),
            payload_codec=codec,
        )
        service = VoteSnapshotService(
            products=cast(Any, products),
            repository=repository,
            outbox=cast(Any, _Outbox()),
            codec=codec,
            clock=lambda: now,
        )

        try:
            async with session_factory() as session:
                async with session.begin():
                    try:
                        for account_id in [*founders, *voters]:
                            email = f"snapshot-{account_id}@vote.test"
                            await session.execute(
                                text(
                                    "INSERT INTO accounts "
                                    "(id,email_display,email_key,password_hash,verified_at,role,"
                                    "created_at,updated_at) "
                                    "VALUES (:id,:email,:email,'hash',:now,'member',:now,:now)"
                                ),
                                {"id": account_id, "email": email, "now": now},
                            )
                        for idx, (product_id, founder_id, name) in enumerate(
                            zip(product_ids, founders, ("Alpha", "Beta", "Zero"), strict=True)
                        ):
                            await session.execute(
                                text(
                                    "INSERT INTO products "
                                    "(id,founder_id,status,version,name,pitch,description,website_url,"
                                    "website_key,launched_at,created_at,updated_at) "
                                    "VALUES (:id,:founder,'launched',1,:name,'Pitch','Description',"
                                    ":url,:host,:launched,:now,:now)"
                                ),
                                {
                                    "id": product_id,
                                    "founder": founder_id,
                                    "name": name,
                                    "url": f"https://snapshot-{idx}.test",
                                    "host": f"snapshot-{idx}.test",
                                    "launched": datetime(2026, 10, 23, 8, tzinfo=UTC),
                                    "now": now,
                                },
                            )
                        existing_enabled_from = await session.scalar(
                            select(VotingFeatureState.enabled_from).where(
                                VotingFeatureState.singleton_id == 1
                            )
                        )
                        await session.execute(
                            text(
                                "INSERT INTO voting_feature_state "
                                "(singleton_id,enabled_from,created_at) VALUES (1,:date,:now) "
                                "ON CONFLICT (singleton_id) DO UPDATE SET enabled_from=:date"
                            ),
                            {"date": launch_date, "now": now},
                        )
                        first_vote = await repository.create_vote(
                            session,
                            member_id=voters[0],
                            product_id=product_ids[0],
                            cast_at=datetime(2026, 10, 23, 22, tzinfo=UTC),
                        )
                        second_vote = await repository.create_vote(
                            session,
                            member_id=voters[1],
                            product_id=product_ids[1],
                            cast_at=datetime(2026, 10, 23, 23, 50, tzinfo=UTC),
                        )
                        vote_ids.extend((first_vote.id, second_vote.id))
                        await session.execute(
                            update(Vote)
                            .where(Vote.id == second_vote.id)
                            .values(
                                state="invalidated", invalidated_at=cutoff - timedelta(seconds=1)
                            )
                        )
                        event_id = uuid5(
                            NAMESPACE_URL,
                            f"launchpad:daily-ranking:{launch_date.isoformat()}",
                        )
                        await service.handle_outbox_event(
                            session,
                            event_type="vote.snapshot_due.v1",
                            aggregate_id=event_id,
                            payload={"launch_date": launch_date.isoformat()},
                        )
                        first_snapshot = await repository.daily_snapshot(
                            session, launch_date=launch_date
                        )
                        assert first_snapshot is not None
                        snapshot, first_entries = first_snapshot
                        assert [
                            (entry.product_id, entry.rank, entry.active_vote_count)
                            for entry in first_entries
                        ] == [
                            (product_ids[0], 1, 1),
                            (product_ids[1], 2, 0),
                            (product_ids[2], 3, 0),
                        ]

                        await session.execute(
                            update(Vote)
                            .where(Vote.id == first_vote.id)
                            .values(
                                state="invalidated", invalidated_at=cutoff + timedelta(minutes=1)
                            )
                        )
                        await service.handle_outbox_event(
                            session,
                            event_type="vote.snapshot_due.v1",
                            aggregate_id=event_id,
                            payload={"launch_date": launch_date.isoformat()},
                        )
                        replayed_snapshot = await repository.daily_snapshot(
                            session, launch_date=launch_date
                        )
                        assert replayed_snapshot is not None
                        replayed, replayed_entries = replayed_snapshot
                        assert replayed.id == snapshot.id
                        assert [
                            (entry.product_id, entry.rank, entry.active_vote_count)
                            for entry in replayed_entries
                        ] == [
                            (entry.product_id, entry.rank, entry.active_vote_count)
                            for entry in first_entries
                        ]
                    finally:
                        await session.execute(
                            delete(DailyRankingEntry).where(
                                DailyRankingEntry.snapshot_id
                                == select(DailyRankingSnapshot.id)
                                .where(DailyRankingSnapshot.launch_date == launch_date)
                                .scalar_subquery()
                            )
                        )
                        await session.execute(
                            delete(DailyRankingSnapshot).where(
                                DailyRankingSnapshot.launch_date == launch_date
                            )
                        )
                        await session.execute(delete(Vote).where(Vote.id.in_(vote_ids)))
                        await session.execute(delete(Product).where(Product.id.in_(product_ids)))
                        await session.execute(
                            delete(Account).where(Account.id.in_([*founders, *voters]))
                        )
                        if existing_enabled_from is None:
                            await session.execute(
                                delete(VotingFeatureState).where(
                                    VotingFeatureState.singleton_id == 1
                                )
                            )
                        else:
                            await session.execute(
                                update(VotingFeatureState)
                                .where(VotingFeatureState.singleton_id == 1)
                                .values(enabled_from=existing_enabled_from)
                            )
        finally:
            await database.close()

    asyncio.run(verify())
