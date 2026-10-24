"""PostgreSQL persistence for vote history and retry receipts."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import extract, func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.modules.votes.models import (
    Vote,
    VoteIdempotencyReceipt,
    VoteRiskFlag,
)


class VoteRepository:
    """Keep all vote persistence and serialization inside the votes feature."""

    async def lock_member_product(
        self, session: AsyncSession, *, member_id: UUID, product_id: UUID
    ) -> None:
        """Serialize commands for a member/product pair through transaction advisory locks."""

        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:member_id), hashtext(:product_id))"),
            {"member_id": str(member_id), "product_id": str(product_id)},
        )

    async def lock_projection_product(
        self, session: AsyncSession, *, product_id: UUID, launch_date: date
    ) -> None:
        """Serialize product recomputations so delayed events cannot overwrite newer state."""

        await session.execute(
            text(
                "SELECT pg_advisory_xact_lock_shared(hashtext('vote-ranking'), "
                "hashtext(:launch_date))"
            ),
            {"launch_date": launch_date.isoformat()},
        )
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:product_id), hashtext(:launch_date))"),
            {"product_id": str(product_id), "launch_date": launch_date.isoformat()},
        )

    async def lock_projection_rebuild(self, session: AsyncSession, *, launch_date: date) -> None:
        """Exclude event writers while replacing one date's Redis projection."""

        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('vote-ranking'), hashtext(:launch_date))"),
            {"launch_date": launch_date.isoformat()},
        )

    async def lock_idempotency_key(
        self, session: AsyncSession, *, member_id: UUID, idempotency_key: str
    ) -> None:
        """Serialize reuse of one member's key even across different product locks."""

        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:member_id), hashtext(:idempotency_key))"),
            {"member_id": str(member_id), "idempotency_key": idempotency_key},
        )

    async def get_receipt(
        self, session: AsyncSession, *, member_id: UUID, idempotency_key: str
    ) -> VoteIdempotencyReceipt | None:
        """Read an actor-scoped idempotency receipt after locking the command lane."""

        statement = select(VoteIdempotencyReceipt).where(
            VoteIdempotencyReceipt.member_id == member_id,
            VoteIdempotencyReceipt.idempotency_key == idempotency_key,
        )
        return cast(VoteIdempotencyReceipt | None, await session.scalar(statement))

    async def ensure_voting_enabled_from(
        self, session: AsyncSession, *, enabled_from: date, now: datetime
    ) -> None:
        """Persist the first enabled UTC date, never replacing an earlier rollout date."""

        await session.execute(
            text(
                "INSERT INTO voting_feature_state (singleton_id, enabled_from, created_at) "
                "VALUES (1, :enabled_from, :created_at) ON CONFLICT (singleton_id) DO NOTHING"
            ),
            {"enabled_from": enabled_from, "created_at": now},
        )

    async def create_vote(
        self,
        session: AsyncSession,
        *,
        member_id: UUID,
        product_id: UUID,
        cast_at: datetime,
    ) -> Vote:
        """Create one new retained active vote row."""

        vote = (
            await session.scalars(
                insert(Vote)
                .values(
                    id=uuid7(),
                    member_id=member_id,
                    product_id=product_id,
                    cast_at=cast_at,
                    state="active",
                    withdrawn_at=None,
                    invalidated_at=None,
                )
                .returning(Vote)
            )
        ).one()
        return vote

    async def active_vote(
        self,
        session: AsyncSession,
        *,
        member_id: UUID,
        product_id: UUID,
        lock: bool = False,
    ) -> Vote | None:
        """Find the member's only active vote for a product."""

        statement = select(Vote).where(
            Vote.member_id == member_id,
            Vote.product_id == product_id,
            Vote.state == "active",
        )
        if lock:
            statement = statement.with_for_update()
        return cast(Vote | None, await session.scalar(statement))

    async def vote_by_id(self, session: AsyncSession, *, vote_id: UUID | None) -> Vote | None:
        """Load the original vote referenced by a successful command receipt."""

        if vote_id is None:
            return None
        return cast(Vote | None, await session.get(Vote, vote_id))

    async def withdraw_vote(self, session: AsyncSession, *, vote: Vote, now: datetime) -> Vote:
        """Transition active history without deleting the vote row."""

        saved = await session.scalar(
            update(Vote)
            .where(Vote.id == vote.id, Vote.state == "active")
            .values(state="withdrawn", withdrawn_at=now)
            .returning(Vote)
        )
        if saved is None:
            raise RuntimeError("locked vote could not be withdrawn")
        return saved

    async def add_receipt(
        self,
        session: AsyncSession,
        *,
        member_id: UUID,
        idempotency_key: str,
        request_fingerprint: str,
        command: str,
        vote_id: UUID,
        outcome: str,
        now: datetime,
    ) -> VoteIdempotencyReceipt:
        """Persist replay identity and original command outcome."""

        receipt = (
            await session.scalars(
                insert(VoteIdempotencyReceipt)
                .values(
                    id=uuid7(),
                    member_id=member_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    command=command,
                    vote_id=vote_id,
                    outcome=outcome,
                    created_at=now,
                )
                .returning(VoteIdempotencyReceipt)
            )
        ).one()
        return receipt

    async def add_risk_flag(
        self,
        session: AsyncSession,
        *,
        vote_id: UUID,
        member_id: UUID,
        signal_code: str,
        now: datetime,
    ) -> VoteRiskFlag:
        """Create a pending categorical flag without changing vote state."""

        flag = (
            await session.scalars(
                insert(VoteRiskFlag)
                .values(
                    id=uuid7(),
                    vote_id=vote_id,
                    member_id=member_id,
                    signal_code=signal_code,
                    state="pending",
                    created_at=now,
                    resolved_at=None,
                )
                .returning(VoteRiskFlag)
            )
        ).one()
        return flag

    async def ranking_values(
        self, session: AsyncSession, *, product_id: UUID, launch_date: date
    ) -> tuple[int, Decimal]:
        """Aggregate active vote count and normalized six-hour score for one launch."""

        day_start = datetime.combine(launch_date, time.min, tzinfo=UTC)
        day_end = day_start + timedelta(days=1)
        elapsed_hours = extract("epoch", Vote.cast_at - day_start) / 21600
        statement = select(
            func.count(Vote.id),
            func.coalesce(func.sum(func.power(2, elapsed_hours)), 0),
        ).where(
            Vote.product_id == product_id,
            Vote.state == "active",
            Vote.cast_at >= day_start,
            Vote.cast_at < day_end,
        )
        count, score = (await session.execute(statement)).one()
        return int(count), Decimal(str(score))

    async def ranking_values_for_products(
        self, session: AsyncSession, *, product_ids: tuple[UUID, ...], launch_date: date
    ) -> dict[UUID, tuple[int, Decimal]]:
        """Aggregate one public page in a single bounded query, including zero-vote rows."""

        if not product_ids:
            return {}
        day_start = datetime.combine(launch_date, time.min, tzinfo=UTC)
        day_end = day_start + timedelta(days=1)
        elapsed_hours = extract("epoch", Vote.cast_at - day_start) / 21600
        statement = (
            select(
                Vote.product_id,
                func.count(Vote.id),
                func.sum(func.power(2, elapsed_hours)),
            )
            .where(
                Vote.product_id.in_(product_ids),
                Vote.state == "active",
                Vote.cast_at >= day_start,
                Vote.cast_at < day_end,
            )
            .group_by(Vote.product_id)
        )
        rows = await session.execute(statement)
        values = {
            product_id: (int(count), Decimal(str(score))) for product_id, count, score in rows
        }
        return {product_id: values.get(product_id, (0, Decimal(0))) for product_id in product_ids}
