"""Mapping contracts for durable voting and daily ranking records."""

from typing import cast

from sqlalchemy import CheckConstraint, Table

from app.modules.votes.models import (
    DailyRankingEntry,
    DailyRankingSnapshot,
    Vote,
    VoteIdempotencyReceipt,
    VoteReviewDecision,
    VoteRiskFlag,
    VotingFeatureState,
)


def test_vote_feature_mappings_have_expected_fields_and_audit_indexes() -> None:
    expected = {
        Vote: {
            "id",
            "member_id",
            "product_id",
            "cast_at",
            "state",
            "withdrawn_at",
            "invalidated_at",
        },
        VoteIdempotencyReceipt: {
            "id",
            "member_id",
            "idempotency_key",
            "request_fingerprint",
            "command",
            "vote_id",
            "outcome",
            "created_at",
        },
        VoteRiskFlag: {
            "id",
            "vote_id",
            "member_id",
            "signal_code",
            "state",
            "created_at",
            "resolved_at",
        },
        VoteReviewDecision: {
            "id",
            "flag_id",
            "reviewer_account_id",
            "outcome",
            "reason",
            "created_at",
        },
        DailyRankingSnapshot: {"id", "launch_date", "cutoff_at", "created_at", "algorithm_version"},
        DailyRankingEntry: {
            "id",
            "snapshot_id",
            "product_id",
            "rank",
            "score",
            "active_vote_count",
        },
        VotingFeatureState: {"singleton_id", "enabled_from", "created_at"},
    }
    for model, columns in expected.items():
        assert columns <= set(cast(Table, model.__table__).columns.keys())

    assert {
        "uq_votes_active_member_product",
        "ix_votes_product_cast",
        "ix_votes_active_product_cast",
    } <= {index.name for index in cast(Table, Vote.__table__).indexes}
    assert "uq_vote_receipts_member_key" in {
        index.name for index in cast(Table, VoteIdempotencyReceipt.__table__).indexes
    }


def test_daily_snapshot_and_entries_enforce_unique_dates_products_and_ranks() -> None:
    snapshot_indexes = {index.name for index in cast(Table, DailyRankingSnapshot.__table__).indexes}
    entry_indexes = {index.name for index in cast(Table, DailyRankingEntry.__table__).indexes}
    assert "uq_daily_ranking_snapshots_date" in snapshot_indexes
    assert {
        "uq_daily_entries_snapshot_product",
        "uq_daily_entries_snapshot_rank",
    } <= entry_indexes
    assert all(
        isinstance(constraint, CheckConstraint)
        for model in (Vote, VoteRiskFlag, VoteReviewDecision, DailyRankingEntry, VotingFeatureState)
        for constraint in cast(Table, model.__table__).constraints
        if isinstance(constraint, CheckConstraint)
    )


def test_vote_state_and_review_mappings_do_not_store_raw_risk_identifiers() -> None:
    flag_columns = set(cast(Table, VoteRiskFlag.__table__).columns.keys())
    assert not {"ip_address", "raw_ip", "device_fingerprint", "turnstile_token"} & flag_columns
    assert "reason" in cast(Table, VoteReviewDecision.__table__).columns
