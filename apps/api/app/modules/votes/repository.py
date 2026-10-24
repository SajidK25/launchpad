"""PostgreSQL persistence for vote history and retry receipts."""

from __future__ import annotations

from datetime import date, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import insert, select, text, update
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
        return cast(Vote, saved)

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
