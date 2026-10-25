"""Durable vote history, moderation audit, and immutable ranking mappings."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class VoteBase(DeclarativeBase):
    """Metadata owned by the votes feature."""


class Vote(VoteBase):
    """Append-only member vote history, with state timestamps for audit."""

    __tablename__ = "votes"
    __table_args__ = (
        CheckConstraint("state IN ('active', 'withdrawn', 'invalidated')", name="ck_votes_state"),
        CheckConstraint(
            "(state = 'active' AND withdrawn_at IS NULL AND invalidated_at IS NULL) OR "
            "(state = 'withdrawn' AND withdrawn_at IS NOT NULL AND invalidated_at IS NULL) OR "
            "(state = 'invalidated' AND invalidated_at IS NOT NULL)",
            name="ck_votes_state_timestamps",
        ),
        Index(
            "uq_votes_active_member_product",
            "member_id",
            "product_id",
            unique=True,
            postgresql_where=text("state = 'active'"),
        ),
        Index("ix_votes_product_cast", "product_id", "cast_at", "id"),
        Index("ix_votes_member_product", "member_id", "product_id", "cast_at"),
        Index(
            "ix_votes_active_product_cast",
            "product_id",
            "cast_at",
            "id",
            postgresql_where=text("state = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    member_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    cast_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VoteIdempotencyReceipt(VoteBase):
    """Durable response receipt preventing duplicate command effects."""

    __tablename__ = "vote_idempotency_receipts"
    __table_args__ = (
        CheckConstraint("command IN ('cast', 'withdraw')", name="ck_vote_receipts_command"),
        CheckConstraint("length(request_fingerprint) = 64", name="ck_vote_receipts_fingerprint"),
        Index("uq_vote_receipts_member_key", "member_id", "idempotency_key", unique=True),
        Index("ix_vote_receipts_vote", "vote_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    member_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    vote_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("votes.id", ondelete="RESTRICT")
    )
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VoteRiskFlag(VoteBase):
    """Categorical risk signals queued for explicit staff review."""

    __tablename__ = "vote_risk_flags"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'cleared', 'invalidated')", name="ck_vote_flags_state"
        ),
        CheckConstraint("length(signal_code) BETWEEN 1 AND 80", name="ck_vote_flags_signal"),
        Index(
            "ix_vote_flags_pending_created",
            "created_at",
            "id",
            postgresql_where=text("state = 'pending'"),
        ),
        Index("ix_vote_flags_vote", "vote_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    vote_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("votes.id", ondelete="RESTRICT"), nullable=False
    )
    member_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    signal_code: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VoteReviewDecision(VoteBase):
    """Append-only staff decision explaining a flag resolution."""

    __tablename__ = "vote_review_decisions"
    __table_args__ = (
        CheckConstraint("outcome IN ('cleared', 'invalidated')", name="ck_vote_decisions_outcome"),
        CheckConstraint("length(trim(reason)) BETWEEN 1 AND 2000", name="ck_vote_decisions_reason"),
        Index("ix_vote_decisions_flag_created", "flag_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    flag_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vote_risk_flags.id", ondelete="RESTRICT"), nullable=False
    )
    reviewer_account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DailyRankingSnapshot(VoteBase):
    """Immutable daily ranking captured at the UTC cutoff."""

    __tablename__ = "daily_ranking_snapshots"
    __table_args__ = (
        CheckConstraint("algorithm_version >= 1", name="ck_daily_snapshots_algorithm_version"),
        Index("uq_daily_ranking_snapshots_date", "launch_date", unique=True),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    launch_date: Mapped[date] = mapped_column(Date, nullable=False)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    algorithm_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class DailyRankingEntry(VoteBase):
    """Frozen rank, score, and vote count for one publicly launched product."""

    __tablename__ = "daily_ranking_entries"
    __table_args__ = (
        CheckConstraint("rank >= 1", name="ck_daily_entries_rank"),
        CheckConstraint("active_vote_count >= 0", name="ck_daily_entries_vote_count"),
        CheckConstraint("score >= 0", name="ck_daily_entries_score"),
        Index("uq_daily_entries_snapshot_product", "snapshot_id", "product_id", unique=True),
        Index("uq_daily_entries_snapshot_rank", "snapshot_id", "rank", unique=True),
        Index("ix_daily_entries_product", "product_id", "snapshot_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    snapshot_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("daily_ranking_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    active_vote_count: Mapped[int] = mapped_column(Integer, nullable=False)


class VotingFeatureState(VoteBase):
    """Persisted first-enabled UTC date, independent of the runtime write switch."""

    __tablename__ = "voting_feature_state"
    __table_args__ = (
        CheckConstraint("singleton_id = 1", name="ck_voting_feature_state_singleton"),
    )

    singleton_id: Mapped[int] = mapped_column(Integer, primary_key=True, server_default="1")
    enabled_from: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
