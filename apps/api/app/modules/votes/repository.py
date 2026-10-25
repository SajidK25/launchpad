"""PostgreSQL persistence for vote history and retry receipts."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import extract, func, insert, or_, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.schema import Table
from uuid6 import uuid7

from app.modules.votes.models import (
    DailyRankingEntry,
    DailyRankingSnapshot,
    Vote,
    VoteIdempotencyReceipt,
    VoteReviewDecision,
    VoteRiskFlag,
    VotingFeatureState,
)
from app.shared.config.settings import DEFAULT_VOTE_SCORE_HALF_LIFE_SECONDS


class VoteRepository:
    """Keep all vote persistence and serialization inside the votes feature."""

    def __init__(
        self,
        *,
        score_half_life_seconds: int = DEFAULT_VOTE_SCORE_HALF_LIFE_SECONDS,
    ) -> None:
        if score_half_life_seconds < 1:
            raise ValueError("vote score half-life must be positive")
        self.score_half_life_seconds = score_half_life_seconds

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

    async def voting_enabled_from(self, session: AsyncSession) -> date | None:
        """Return the durable first UTC date with ranking enabled, if initialized."""

        value = await session.scalar(
            select(VotingFeatureState.enabled_from).where(VotingFeatureState.singleton_id == 1)
        )
        return value

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

    async def lock_risk_flag(self, session: AsyncSession, *, flag_id: UUID) -> VoteRiskFlag | None:
        """Lock one review flag so only one reviewer can resolve it."""

        return cast(
            VoteRiskFlag | None,
            await session.scalar(
                select(VoteRiskFlag).where(VoteRiskFlag.id == flag_id).with_for_update()
            ),
        )

    async def decide_risk_flag(
        self,
        session: AsyncSession,
        *,
        flag: VoteRiskFlag,
        outcome: str,
        now: datetime,
    ) -> VoteRiskFlag:
        """Set a pending flag's terminal state while preserving its history."""

        saved = await session.scalar(
            update(VoteRiskFlag)
            .where(VoteRiskFlag.id == flag.id, VoteRiskFlag.state == "pending")
            .values(state=outcome, resolved_at=now)
            .returning(VoteRiskFlag)
        )
        if saved is None:
            raise RuntimeError("locked vote review flag could not be resolved")
        return saved

    async def add_review_decision(
        self,
        session: AsyncSession,
        *,
        flag_id: UUID,
        reviewer_account_id: UUID,
        outcome: str,
        reason: str,
        now: datetime,
    ) -> VoteReviewDecision:
        """Append the reviewer attribution and rationale for one decision."""

        decision = (
            await session.scalars(
                insert(VoteReviewDecision)
                .values(
                    id=uuid7(),
                    flag_id=flag_id,
                    reviewer_account_id=reviewer_account_id,
                    outcome=outcome,
                    reason=reason,
                    created_at=now,
                )
                .returning(VoteReviewDecision)
            )
        ).one()
        return decision

    async def invalidate_vote(self, session: AsyncSession, *, vote: Vote, now: datetime) -> Vote:
        """Explicitly invalidate a reviewed vote without deleting its history."""

        saved = await session.scalar(
            update(Vote)
            .where(Vote.id == vote.id, Vote.state != "invalidated")
            .values(state="invalidated", invalidated_at=now)
            .returning(Vote)
        )
        if saved is None:
            raise RuntimeError("reviewed vote could not be invalidated")
        return saved

    async def ranking_values(
        self, session: AsyncSession, *, product_id: UUID, launch_date: date
    ) -> tuple[int, Decimal]:
        """Aggregate active vote count and normalized recency score for one launch."""

        day_start = datetime.combine(launch_date, time.min, tzinfo=UTC)
        day_end = day_start + timedelta(days=1)
        elapsed_hours = extract("epoch", Vote.cast_at - day_start) / self.score_half_life_seconds
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
        elapsed_hours = extract("epoch", Vote.cast_at - day_start) / self.score_half_life_seconds
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

    async def snapshot_values_for_products(
        self,
        session: AsyncSession,
        *,
        product_ids: tuple[UUID, ...],
        cutoff_at: datetime,
    ) -> dict[UUID, tuple[int, Decimal]]:
        """Aggregate votes at cutoff using the configured half-life."""

        if not product_ids:
            return {}
        cutoff = cutoff_at.astimezone(UTC)
        day_start = cutoff - timedelta(days=1)
        elapsed_half_life = extract("epoch", Vote.cast_at - cutoff) / self.score_half_life_seconds
        statement = (
            select(
                Vote.product_id,
                func.count(Vote.id),
                func.sum(func.power(2, elapsed_half_life)),
            )
            .where(
                Vote.product_id.in_(product_ids),
                Vote.cast_at >= day_start,
                Vote.cast_at < cutoff,
                or_(Vote.withdrawn_at.is_(None), Vote.withdrawn_at >= cutoff),
                or_(Vote.invalidated_at.is_(None), Vote.invalidated_at >= cutoff),
            )
            .group_by(Vote.product_id)
        )
        rows = await session.execute(statement)
        values = {
            product_id: (int(count), Decimal(str(score))) for product_id, count, score in rows
        }
        return {product_id: values.get(product_id, (0, Decimal(0))) for product_id in product_ids}

    async def create_daily_snapshot(
        self,
        session: AsyncSession,
        *,
        launch_date: date,
        cutoff_at: datetime,
        created_at: datetime,
        entries: list[tuple[UUID, int, Decimal, int]],
    ) -> UUID:
        """Insert a snapshot and all entries atomically, retaining any existing archive."""

        snapshot_id = uuid7()
        inserted_id = await session.scalar(
            pg_insert(DailyRankingSnapshot)
            .values(
                id=snapshot_id,
                launch_date=launch_date,
                cutoff_at=cutoff_at,
                created_at=created_at,
                algorithm_version=1,
            )
            .on_conflict_do_nothing(index_elements=[DailyRankingSnapshot.launch_date])
            .returning(DailyRankingSnapshot.id)
        )
        if inserted_id is None:
            existing_id = await session.scalar(
                select(DailyRankingSnapshot.id).where(
                    DailyRankingSnapshot.launch_date == launch_date
                )
            )
            if existing_id is None:
                raise RuntimeError("daily snapshot conflict did not produce an existing archive")
            return existing_id
        if entries:
            await session.execute(
                insert(cast(Table, DailyRankingEntry.__table__)),
                [
                    {
                        "id": uuid7(),
                        "snapshot_id": inserted_id,
                        "product_id": product_id,
                        "rank": rank,
                        "score": score,
                        "active_vote_count": active_vote_count,
                    }
                    for product_id, rank, score, active_vote_count in entries
                ],
            )
        return inserted_id

    async def daily_snapshot(
        self, session: AsyncSession, *, launch_date: date
    ) -> tuple[DailyRankingSnapshot, list[DailyRankingEntry]] | None:
        """Read an immutable header and its entries in their archived order."""

        snapshot = await session.scalar(
            select(DailyRankingSnapshot).where(DailyRankingSnapshot.launch_date == launch_date)
        )
        if snapshot is None:
            return None
        entries = list(
            (
                await session.scalars(
                    select(DailyRankingEntry)
                    .where(DailyRankingEntry.snapshot_id == snapshot.id)
                    .order_by(DailyRankingEntry.rank)
                )
            ).all()
        )
        return snapshot, entries

    async def daily_snapshot_page(
        self,
        session: AsyncSession,
        *,
        launch_date: date,
        limit: int,
        after_rank: int | None = None,
    ) -> tuple[DailyRankingSnapshot | None, list[DailyRankingEntry]]:
        """Read an immutable archive by its unique date and stable rank cursor."""

        snapshot = await session.scalar(
            select(DailyRankingSnapshot).where(DailyRankingSnapshot.launch_date == launch_date)
        )
        if snapshot is None:
            return None, []
        statement = select(DailyRankingEntry).where(DailyRankingEntry.snapshot_id == snapshot.id)
        if after_rank is not None:
            statement = statement.where(DailyRankingEntry.rank > after_rank)
        entries = list(
            (await session.scalars(statement.order_by(DailyRankingEntry.rank).limit(limit))).all()
        )
        return snapshot, entries

    async def daily_snapshot_entry_for_product(
        self, session: AsyncSession, *, launch_date: date, product_id: UUID
    ) -> tuple[DailyRankingSnapshot, DailyRankingEntry] | None:
        """Resolve a product's archived rank directly without walking prior ranks."""

        result = await session.execute(
            select(DailyRankingSnapshot, DailyRankingEntry)
            .join(DailyRankingEntry, DailyRankingEntry.snapshot_id == DailyRankingSnapshot.id)
            .where(
                DailyRankingSnapshot.launch_date == launch_date,
                DailyRankingEntry.product_id == product_id,
            )
        )
        row = result.one_or_none()
        return None if row is None else (row[0], row[1])

    async def active_vote_product_ids(
        self,
        session: AsyncSession,
        *,
        member_id: UUID,
        product_ids: tuple[UUID, ...],
        launch_date: date,
    ) -> set[UUID]:
        """Return only the viewer's own active votes for one launch date."""

        if not product_ids:
            return set()
        day_start = datetime.combine(launch_date, time.min, tzinfo=UTC)
        next_day = day_start + timedelta(days=1)
        return set(
            await session.scalars(
                select(Vote.product_id).where(
                    Vote.member_id == member_id,
                    Vote.product_id.in_(product_ids),
                    Vote.state == "active",
                    Vote.cast_at >= day_start,
                    Vote.cast_at < next_day,
                )
            )
        )

    async def pending_review_page(
        self,
        session: AsyncSession,
        *,
        limit: int,
        after: tuple[datetime, UUID] | None = None,
    ) -> list[tuple[VoteRiskFlag, Vote]]:
        """Page pending flags with minimal vote context, excluding network data."""

        statement = (
            select(VoteRiskFlag, Vote)
            .join(Vote, Vote.id == VoteRiskFlag.vote_id)
            .where(VoteRiskFlag.state == "pending")
        )
        if after is not None:
            statement = statement.where(tuple_(VoteRiskFlag.created_at, VoteRiskFlag.id) > after)
        rows = await session.execute(
            statement.order_by(VoteRiskFlag.created_at, VoteRiskFlag.id).limit(limit)
        )
        return [(flag, vote) for flag, vote in rows.tuples()]
