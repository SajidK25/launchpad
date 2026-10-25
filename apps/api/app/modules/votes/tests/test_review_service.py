"""Explicit staff review behavior for flagged votes."""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.staff import AccountState
from app.modules.votes.policies import VoteConflictError, VoteForbiddenError
from app.modules.votes.service import VoteReviewService


class _Transaction(AbstractAsyncContextManager[None]):
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Session:
    def begin_nested(self) -> _Transaction:
        return _Transaction()


class _Members:
    def __init__(self, *, role: str = "reviewer", verified: bool = True) -> None:
        self.account_id = uuid4()
        self.role = role
        self.verified = verified
        self.suspended_at: datetime | None = None

    async def current_account(
        self, _session: AsyncSession, account_id: UUID, *, lock: bool = False
    ) -> AccountState | None:
        if account_id != self.account_id:
            return None
        return AccountState(account_id, self.verified, self.role, self.suspended_at)


class _Repository:
    def __init__(self) -> None:
        self.vote = SimpleNamespace(id=uuid4(), state="active", product_id=uuid4())
        self.flag = SimpleNamespace(
            id=uuid4(), vote_id=self.vote.id, member_id=uuid4(), state="pending"
        )
        self.decisions: list[Any] = []

    async def lock_risk_flag(self, _session: AsyncSession, *, flag_id: UUID) -> Any | None:
        if flag_id != self.flag.id:
            return None
        return self.flag

    async def vote_by_id(self, _session: AsyncSession, *, vote_id: UUID) -> Any | None:
        return self.vote if vote_id == self.vote.id else None

    async def decide_risk_flag(
        self, _session: AsyncSession, *, flag: Any, outcome: str, now: datetime
    ) -> Any:
        flag.state = outcome
        flag.resolved_at = now
        return flag

    async def add_review_decision(self, _session: AsyncSession, **values: Any) -> Any:
        decision = SimpleNamespace(id=uuid4(), **values)
        self.decisions.append(decision)
        return decision

    async def invalidate_vote(self, _session: AsyncSession, *, vote: Any, now: datetime) -> Any:
        vote.state = "invalidated"
        vote.invalidated_at = now
        return vote


class _Products:
    async def voting_context(
        self, _session: AsyncSession, *, product_id: UUID, lock: bool = False
    ) -> Any:
        return SimpleNamespace(product_id=product_id, launch_date=date(2026, 10, 24), launched=True)


class _Outbox:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def add(self, _session: AsyncSession, event: Any) -> UUID:
        self.events.append(event)
        return cast(UUID, event.id) if event.id is not None else uuid4()


class _Codec:
    def encode(self, payload: Any) -> tuple[str, bytes]:
        return "test", repr(sorted(payload.items())).encode()


def _build(role: str = "reviewer") -> tuple[VoteReviewService, _Members, _Repository, _Outbox]:
    members, repository, outbox = _Members(role=role), _Repository(), _Outbox()
    service = VoteReviewService(
        member_access=cast(Any, members),
        product_access=cast(Any, _Products()),
        repository=cast(Any, repository),
        outbox=cast(Any, outbox),
        codec=cast(Any, _Codec()),
        clock=lambda: datetime(2026, 10, 25, tzinfo=UTC),
    )
    return service, members, repository, outbox


def test_flagged_vote_remains_counted_until_staff_explicitly_invalidates() -> None:
    async def verify() -> None:
        service, reviewer, repository, outbox = _build()
        assert repository.vote.state == "active"
        await service.decide(
            cast(AsyncSession, _Session()),
            reviewer_id=reviewer.account_id,
            flag_id=repository.flag.id,
            outcome="invalidated",
            reason="Confirmed coordinated voting.",
        )
        assert repository.vote.state == "invalidated"
        assert repository.flag.state == "invalidated"
        assert repository.decisions[0].reviewer_account_id == reviewer.account_id
        assert repository.decisions[0].reason == "Confirmed coordinated voting."
        assert len(outbox.events) == 1
        assert outbox.events[0].event_type == "vote.review_decided.v1"

    asyncio.run(verify())


def test_only_verified_unsuspended_review_staff_can_decide() -> None:
    async def verify() -> None:
        service, member, repository, outbox = _build(role="member")
        with pytest.raises(VoteForbiddenError):
            await service.decide(
                cast(AsyncSession, _Session()),
                reviewer_id=member.account_id,
                flag_id=repository.flag.id,
                outcome="cleared",
                reason="Not suspicious.",
            )
        assert repository.flag.state == "pending"
        assert repository.decisions == []
        assert outbox.events == []

    asyncio.run(verify())


def test_second_decision_for_resolved_flag_conflicts_without_new_audit() -> None:
    async def verify() -> None:
        service, reviewer, repository, outbox = _build()
        repository.flag.state = "cleared"
        with pytest.raises(VoteConflictError):
            await service.decide(
                cast(AsyncSession, _Session()),
                reviewer_id=reviewer.account_id,
                flag_id=repository.flag.id,
                outcome="invalidated",
                reason="Conflict.",
            )
        assert repository.decisions == []
        assert outbox.events == []

    asyncio.run(verify())
