"""Transactional member vote lifecycle and idempotent command service."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.staff import AccountState
from app.modules.votes.policies import (
    VoteConflictError,
    VoteNotFoundError,
    require_open_launch_day,
    require_public_other_product,
    require_voting_member,
    validate_idempotency_key,
)
from app.modules.votes.repository import VoteRepository
from app.shared.events.outbox import OutboxEvent, OutboxRepository

_RISK_SIGNAL = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


class VoteMemberAccess(Protocol):
    """Auth-owned member state lookup used by the vote service."""

    async def current_account(
        self, session: AsyncSession, account_id: UUID, *, lock: bool = False
    ) -> AccountState | None: ...


class ProductVotingContext(Protocol):
    """Named product-service port exposing only voting eligibility fields."""

    product_id: UUID
    owner_account_id: UUID
    launch_date: date
    launched: bool


class VoteProductAccess(Protocol):
    """Products-owned read boundary; the votes module never imports its repository."""

    async def voting_context(
        self, session: AsyncSession, *, product_id: UUID, lock: bool = False
    ) -> ProductVotingContext | None: ...


class VotePayloadCodec(Protocol):
    """Encrypt minimal internal outbox payloads with the configured key ring."""

    def encode(self, payload: Mapping[str, object]) -> tuple[str, bytes]: ...


class VoteOutbox(Protocol):
    """Transactional outbox interface using the command's database session."""

    async def add(self, session: AsyncSession, event: OutboxEvent) -> UUID: ...


@dataclass(frozen=True, slots=True)
class VoteCommandResult:
    """Committed state returned to the member, without ranking internals."""

    vote_id: UUID
    product_id: UUID
    active: bool
    cast_at: datetime
    replayed: bool = False


class VoteService:
    """Apply vote state, receipt, optional risk audit, and outbox events atomically."""

    def __init__(
        self,
        *,
        member_access: VoteMemberAccess,
        product_access: VoteProductAccess,
        repository: VoteRepository | None = None,
        outbox: VoteOutbox | None = None,
        codec: VotePayloadCodec,
        writes_enabled: Callable[[], bool],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.member_access = member_access
        self.product_access = product_access
        self.repository = repository or VoteRepository()
        self.outbox = outbox or OutboxRepository()
        self.codec = codec
        self.writes_enabled = writes_enabled
        self.clock = clock or (lambda: datetime.now(UTC))

    async def cast(
        self,
        session: AsyncSession,
        *,
        member_id: UUID,
        product_id: UUID,
        idempotency_key: str,
        risk_signal: str | None = None,
    ) -> VoteCommandResult:
        """Cast one vote, replay a prior command, or reject without partial writes."""

        return await self._command(
            session,
            command="cast",
            member_id=member_id,
            product_id=product_id,
            idempotency_key=idempotency_key,
            risk_signal=risk_signal,
        )

    async def withdraw(
        self,
        session: AsyncSession,
        *,
        member_id: UUID,
        product_id: UUID,
        idempotency_key: str,
        risk_signal: str | None = None,
    ) -> VoteCommandResult:
        """Withdraw only the actor's current vote before the UTC launch-day cutoff."""

        return await self._command(
            session,
            command="withdraw",
            member_id=member_id,
            product_id=product_id,
            idempotency_key=idempotency_key,
            risk_signal=risk_signal,
        )

    async def _command(
        self,
        session: AsyncSession,
        *,
        command: str,
        member_id: UUID,
        product_id: UUID,
        idempotency_key: str,
        risk_signal: str | None,
    ) -> VoteCommandResult:
        now = _utc(self.clock())
        key = validate_idempotency_key(idempotency_key)
        fingerprint = _fingerprint(command, product_id)
        async with session.begin_nested():
            account = await self.member_access.current_account(session, member_id, lock=True)
            require_voting_member(account)
            await self.repository.lock_idempotency_key(
                session, member_id=member_id, idempotency_key=key
            )
            await self.repository.lock_member_product(
                session, member_id=member_id, product_id=product_id
            )
            previous = await self.repository.get_receipt(
                session, member_id=member_id, idempotency_key=key
            )
            if previous is not None:
                if previous.request_fingerprint != fingerprint:
                    raise VoteConflictError("idempotency key was used for a different command")
                vote = await self.repository.vote_by_id(session, vote_id=previous.vote_id)
                if vote is None:
                    raise VoteConflictError("original vote command is unavailable")
                return _result(vote, replayed=True)

            if not self.writes_enabled():
                raise VoteConflictError("voting is not currently enabled")
            context = await self.product_access.voting_context(
                session, product_id=product_id, lock=True
            )
            if context is None:
                raise VoteNotFoundError("product is unavailable for voting")
            require_public_other_product(
                member_id=member_id,
                owner_id=context.owner_account_id,
                launched=context.launched,
            )
            require_open_launch_day(launch_date=context.launch_date, today_utc=now.date())
            if risk_signal is not None and not _RISK_SIGNAL.fullmatch(risk_signal):
                raise VoteConflictError("invalid risk signal")
            await self.repository.ensure_voting_enabled_from(
                session, enabled_from=now.date(), now=now
            )

            if command == "cast":
                existing = await self.repository.active_vote(
                    session, member_id=member_id, product_id=product_id, lock=True
                )
                if existing is not None:
                    raise VoteConflictError("member already voted for this product")
                vote = await self.repository.create_vote(
                    session, member_id=member_id, product_id=product_id, cast_at=now
                )
                active = True
            else:
                vote = await self.repository.active_vote(
                    session, member_id=member_id, product_id=product_id, lock=True
                )
                if vote is None:
                    raise VoteConflictError("no active vote is available to withdraw")
                vote = await self.repository.withdraw_vote(session, vote=vote, now=now)
                active = False

            await self.repository.add_receipt(
                session,
                member_id=member_id,
                idempotency_key=key,
                request_fingerprint=fingerprint,
                command=command,
                vote_id=vote.id,
                outcome="active" if active else "withdrawn",
                now=now,
            )
            await self._emit(
                session,
                event_type="vote.changed.v1",
                aggregate_id=product_id,
                payload={
                    "vote_id": str(vote.id),
                    "product_id": str(product_id),
                    "launch_date": context.launch_date.isoformat(),
                    "action": command,
                },
                now=now,
            )
            if risk_signal is not None:
                flag = await self.repository.add_risk_flag(
                    session,
                    vote_id=vote.id,
                    member_id=member_id,
                    signal_code=risk_signal,
                    now=now,
                )
                await self._emit(
                    session,
                    event_type="vote.flagged.v1",
                    aggregate_id=product_id,
                    payload={"flag_id": str(flag.id), "product_id": str(product_id)},
                    now=now,
                )
            return VoteCommandResult(
                vote_id=vote.id,
                product_id=product_id,
                active=active,
                cast_at=vote.cast_at,
            )

    async def _emit(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        aggregate_id: UUID,
        payload: Mapping[str, object],
        now: datetime,
    ) -> None:
        key_id, encrypted_payload = self.codec.encode(payload)
        await self.outbox.add(
            session,
            OutboxEvent(
                event_type=event_type,
                aggregate_id=aggregate_id,
                key_id=key_id,
                encrypted_payload=encrypted_payload,
                available_at=now,
            ),
        )


def _fingerprint(command: str, product_id: UUID) -> str:
    payload = json.dumps(
        {"command": command, "product_id": str(product_id)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise VoteConflictError("vote clock must be timezone-aware")
    return value.astimezone(UTC)


def _result(vote: object, *, replayed: bool) -> VoteCommandResult:
    return VoteCommandResult(
        vote_id=getattr(vote, "id"),
        product_id=getattr(vote, "product_id"),
        active=getattr(vote, "state") == "active",
        cast_at=getattr(vote, "cast_at"),
        replayed=replayed,
    )
