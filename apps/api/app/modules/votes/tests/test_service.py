"""Domain behavior for member voting and vote withdrawal."""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from app.modules.auth.staff import AccountState
from app.modules.votes.policies import VoteConflictError, VoteForbiddenError, VoteNotFoundError
from app.modules.votes.service import VoteService


class _Transaction(AbstractAsyncContextManager[None]):
    def __init__(self, repository: Any | None = None) -> None:
        self.repository = repository
        self.snapshot: tuple[list[Any], dict[Any, Any], list[Any], list[Any]] | None = None

    async def __aenter__(self) -> None:
        if self.repository is not None:
            self.snapshot = (
                list(self.repository.votes),
                dict(self.repository.receipts),
                list(self.repository.flags),
                list(self.repository.enabled_dates),
            )
        return None

    async def __aexit__(self, exc_type: object, *args: object) -> None:
        if exc_type is not None and self.repository is not None and self.snapshot is not None:
            (
                self.repository.votes,
                self.repository.receipts,
                self.repository.flags,
                self.repository.enabled_dates,
            ) = self.snapshot


class _Session:
    def __init__(self, repository: Any | None = None) -> None:
        self.repository = repository

    def begin_nested(self) -> _Transaction:
        return _Transaction(self.repository)


class _Accounts:
    def __init__(self) -> None:
        self.account_id = uuid4()
        self.verified = True
        self.suspended_at: datetime | None = None

    async def current_account(
        self, session: Any, account_id: UUID, *, lock: bool = False
    ) -> AccountState | None:
        if account_id != self.account_id:
            return None
        return AccountState(account_id, self.verified, "member", self.suspended_at)


class _Products:
    def __init__(self) -> None:
        self.product_id = uuid4()
        self.owner_id = uuid4()
        self.launch_date = date(2026, 10, 24)
        self.launched = True

    async def voting_context(
        self, session: Any, *, product_id: UUID, lock: bool = False
    ) -> Any | None:
        if product_id != self.product_id or not self.launched:
            return None
        return SimpleNamespace(
            product_id=self.product_id,
            owner_account_id=self.owner_id,
            launch_date=self.launch_date,
            launched=True,
        )


class _Repository:
    def __init__(self) -> None:
        self.votes: list[Any] = []
        self.receipts: dict[tuple[UUID, str], Any] = {}
        self.flags: list[Any] = []
        self.enabled_dates: list[date] = []

    async def lock_member_product(self, session: Any, *, member_id: UUID, product_id: UUID) -> None:
        return None

    async def lock_idempotency_key(
        self, session: Any, *, member_id: UUID, idempotency_key: str
    ) -> None:
        return None

    async def get_receipt(
        self, session: Any, *, member_id: UUID, idempotency_key: str
    ) -> Any | None:
        return self.receipts.get((member_id, idempotency_key))

    async def ensure_voting_enabled_from(
        self, session: Any, *, enabled_from: date, now: datetime
    ) -> None:
        self.enabled_dates.append(enabled_from)

    async def create_vote(self, session: Any, **values: Any) -> Any:
        vote = SimpleNamespace(id=uuid4(), state="active", **values)
        self.votes.append(vote)
        return vote

    async def active_vote(
        self, session: Any, *, member_id: UUID, product_id: UUID, lock: bool = False
    ) -> Any | None:
        return next(
            (
                v
                for v in self.votes
                if v.member_id == member_id and v.product_id == product_id and v.state == "active"
            ),
            None,
        )

    async def vote_by_id(self, session: Any, *, vote_id: UUID | None) -> Any | None:
        return next((vote for vote in self.votes if vote.id == vote_id), None)

    async def withdraw_vote(self, session: Any, *, vote: Any, now: datetime) -> Any:
        vote.state = "withdrawn"
        vote.withdrawn_at = now
        return vote

    async def add_receipt(self, session: Any, **values: Any) -> Any:
        receipt = SimpleNamespace(id=uuid4(), **values)
        self.receipts[(receipt.member_id, receipt.idempotency_key)] = receipt
        return receipt

    async def add_risk_flag(self, session: Any, **values: Any) -> Any:
        flag = SimpleNamespace(id=uuid4(), state="pending", **values)
        self.flags.append(flag)
        return flag


class _Codec:
    def encode(self, payload: Any) -> tuple[str, bytes]:
        return "test", repr(sorted(payload.items())).encode()


class _Outbox:
    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[Any] = []
        self.fail = fail

    async def add(self, session: Any, event: Any) -> UUID:
        if self.fail:
            raise RuntimeError("outbox unavailable")
        self.events.append(event)
        return event.id or uuid4()


def _build(
    *, now: datetime | None = None
) -> tuple[VoteService, _Accounts, _Products, _Repository, _Outbox]:
    accounts, products, repository, outbox = _Accounts(), _Products(), _Repository(), _Outbox()
    service = VoteService(
        member_access=cast(Any, accounts),
        product_access=cast(Any, products),
        repository=cast(Any, repository),
        outbox=cast(Any, outbox),
        codec=cast(Any, _Codec()),
        writes_enabled=lambda: True,
        clock=lambda: now or datetime(2026, 10, 24, 12, tzinfo=UTC),
    )
    return service, accounts, products, repository, outbox


def test_eligible_member_can_vote_once_and_receipt_and_event_are_created() -> None:
    async def verify() -> None:
        service, accounts, products, repository, outbox = _build()
        result = await service.cast(
            cast(Any, _Session()),
            member_id=accounts.account_id,
            product_id=products.product_id,
            idempotency_key="vote-1",
        )
        assert result.active is True
        assert len(repository.votes) == len(repository.receipts) == len(outbox.events) == 1
        assert repository.enabled_dates == [date(2026, 10, 24)]

    asyncio.run(verify())


@pytest.mark.parametrize(
    "failure", ["unverified", "suspended", "self", "unlaunched", "writes_off", "wrong_day"]
)
def test_ineligible_vote_is_rejected_without_persisted_state(failure: str) -> None:
    async def verify() -> None:
        service, accounts, products, repository, outbox = _build()
        if failure == "unverified":
            accounts.verified = False
        elif failure == "suspended":
            accounts.suspended_at = datetime(2026, 10, 23, tzinfo=UTC)
        elif failure == "self":
            products.owner_id = accounts.account_id
        elif failure == "unlaunched":
            products.launched = False
        elif failure == "writes_off":
            service.writes_enabled = lambda: False
        elif failure == "wrong_day":
            products.launch_date = date(2026, 10, 23)
        with pytest.raises((VoteForbiddenError, VoteNotFoundError, VoteConflictError)):
            await service.cast(
                cast(Any, _Session()),
                member_id=accounts.account_id,
                product_id=products.product_id,
                idempotency_key="reject-me",
            )
        assert repository.votes == []
        assert repository.receipts == {}
        assert repository.flags == []
        assert outbox.events == []

    asyncio.run(verify())


def test_vote_retry_replays_receipt_and_changed_fingerprint_conflicts() -> None:
    async def verify() -> None:
        service, accounts, products, repository, outbox = _build()
        session = cast(Any, _Session())
        original = await service.cast(
            session,
            member_id=accounts.account_id,
            product_id=products.product_id,
            idempotency_key="same-key",
        )
        replay = await service.cast(
            session,
            member_id=accounts.account_id,
            product_id=products.product_id,
            idempotency_key="same-key",
        )
        assert replay.vote_id == original.vote_id
        assert replay.active is True and replay.replayed is True
        assert len(repository.votes) == len(repository.receipts) == len(outbox.events) == 1
        with pytest.raises(VoteConflictError):
            await service.withdraw(
                session,
                member_id=accounts.account_id,
                product_id=uuid4(),
                idempotency_key="same-key",
            )

    asyncio.run(verify())


def test_withdrawal_preserves_vote_history_and_risk_flag_does_not_remove_vote() -> None:
    async def verify() -> None:
        service, accounts, products, repository, outbox = _build()
        session = cast(Any, _Session())
        await service.cast(
            session,
            member_id=accounts.account_id,
            product_id=products.product_id,
            idempotency_key="cast",
            risk_signal="velocity_threshold",
        )
        assert repository.votes[0].state == "active"
        assert repository.flags[0].state == "pending"
        result = await service.withdraw(
            session,
            member_id=accounts.account_id,
            product_id=products.product_id,
            idempotency_key="withdraw",
        )
        assert result.active is False
        assert repository.votes[0].state == "withdrawn"
        assert len(repository.receipts) == 2 and len(outbox.events) == 3

    asyncio.run(verify())


def test_vote_commands_close_exactly_at_utc_midnight() -> None:
    async def verify() -> None:
        cutoff = datetime(2026, 10, 25, 0, 0, tzinfo=UTC)
        service, accounts, products, repository, _outbox = _build(
            now=cutoff - timedelta(microseconds=1)
        )
        session = cast(Any, _Session())
        await service.cast(
            session,
            member_id=accounts.account_id,
            product_id=products.product_id,
            idempotency_key="just-before-cutoff",
        )

        service.clock = lambda: cutoff
        with pytest.raises(VoteConflictError):
            await service.withdraw(
                session,
                member_id=accounts.account_id,
                product_id=products.product_id,
                idempotency_key="at-cutoff",
            )
        assert repository.votes[0].state == "active"

        closed_service, closed_accounts, closed_products, closed_repository, _ = _build(now=cutoff)
        with pytest.raises(VoteConflictError):
            await closed_service.cast(
                cast(Any, _Session()),
                member_id=closed_accounts.account_id,
                product_id=closed_products.product_id,
                idempotency_key="at-cutoff-cast",
            )
        assert closed_repository.votes == []

    asyncio.run(verify())


def test_suspension_preserves_existing_vote_until_explicit_review() -> None:
    async def verify() -> None:
        service, accounts, products, repository, _outbox = _build()
        session = cast(Any, _Session())
        await service.cast(
            session,
            member_id=accounts.account_id,
            product_id=products.product_id,
            idempotency_key="cast-before-suspension",
        )
        accounts.suspended_at = datetime(2026, 10, 24, 13, tzinfo=UTC)
        with pytest.raises(VoteForbiddenError):
            await service.withdraw(
                session,
                member_id=accounts.account_id,
                product_id=products.product_id,
                idempotency_key="suspended-withdrawal",
            )
        assert repository.votes[0].state == "active"

    asyncio.run(verify())


def test_outbox_failure_does_not_leave_vote_or_receipt() -> None:
    async def verify() -> None:
        service, accounts, products, repository, _ = _build()
        failing_outbox = _Outbox(fail=True)
        service.outbox = cast(Any, failing_outbox)
        with pytest.raises(RuntimeError, match="outbox unavailable"):
            await service.cast(
                cast(Any, _Session(repository)),
                member_id=accounts.account_id,
                product_id=products.product_id,
                idempotency_key="retryable",
            )
        assert repository.votes == []
        assert repository.receipts == {}

    asyncio.run(verify())
