"""Transactional member vote lifecycle and idempotent command service."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.staff import AccountState
from app.modules.votes.policies import (
    VoteConflictError,
    VoteNotFoundError,
    require_open_launch_day,
    require_public_other_product,
    require_vote_reviewer,
    require_voting_member,
    validate_idempotency_key,
)
from app.modules.votes.repository import VoteRepository
from app.shared.events.outbox import OutboxEvent, OutboxRepository, PermanentEventError

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


class VoteSnapshotOutbox(Protocol):
    """Outbox interface that enqueues one stable snapshot intent per UTC date."""

    async def add_once(self, session: AsyncSession, event: OutboxEvent) -> UUID: ...


class PublicLaunchProduct(Protocol):
    id: UUID
    name: str


class PublicLaunchPage(Protocol):
    items: tuple[PublicLaunchProduct, ...]
    next_cursor: str | None


class VoteRankingProductAccess(Protocol):
    async def public_launches(
        self,
        session: AsyncSession,
        *,
        requested_date: date | None,
        first: int = 20,
        after: str | None = None,
    ) -> PublicLaunchPage: ...

    async def public_projection(
        self, session: AsyncSession, *, product_id: UUID
    ) -> object | None: ...


class RankingRedis(Protocol):
    async def zadd(self, name: str, mapping: Mapping[str, float]) -> int: ...
    async def hset(self, name: str, mapping: Mapping[str, str]) -> int: ...
    async def delete(self, *names: str) -> int: ...
    async def publish(self, channel: str, message: str) -> int: ...
    async def hgetall(self, name: str) -> dict[str, str]: ...
    async def expire(self, name: str, time: int) -> bool: ...


class VoteSnapshotScheduler(Protocol):
    async def schedule_for_launch_date(
        self, session: AsyncSession, launch_date: date
    ) -> UUID | None: ...

    async def handle_outbox_event(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        aggregate_id: UUID,
        payload: Mapping[str, object],
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class LiveRankEntry:
    product_id: UUID
    name: str
    active_vote_count: int
    score: Decimal


@dataclass(frozen=True, slots=True)
class VoteCommandResult:
    """Committed state returned to the member, without ranking internals."""

    vote_id: UUID
    product_id: UUID
    active: bool
    cast_at: datetime
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class VoteReviewResult:
    """Append-only staff decision returned after its transaction succeeds."""

    id: UUID
    flag_id: UUID
    reviewer_account_id: UUID
    outcome: str
    reason: str
    created_at: datetime


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


class VoteReviewService:
    """Resolve risk flags only through attributed, transactional staff decisions."""

    def __init__(
        self,
        *,
        member_access: VoteMemberAccess,
        product_access: VoteProductAccess,
        repository: VoteRepository | None = None,
        outbox: VoteOutbox | None = None,
        codec: VotePayloadCodec,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.member_access = member_access
        self.product_access = product_access
        self.repository = repository or VoteRepository()
        self.outbox = outbox or OutboxRepository()
        self.codec = codec
        self.clock = clock or (lambda: datetime.now(UTC))

    async def decide(
        self,
        session: AsyncSession,
        *,
        reviewer_id: UUID,
        flag_id: UUID,
        outcome: str,
        reason: str,
    ) -> VoteReviewResult:
        """Clear a flag or invalidate its vote, writing decision and outbox atomically."""

        normalized_reason = reason.strip()
        if outcome not in {"cleared", "invalidated"}:
            raise VoteConflictError("invalid vote review outcome")
        if not 1 <= len(normalized_reason) <= 2000:
            raise VoteConflictError("vote review reason must be between 1 and 2000 characters")
        now = _utc(self.clock())
        async with session.begin_nested():
            account = await self.member_access.current_account(session, reviewer_id, lock=True)
            require_vote_reviewer(account)
            flag = await self.repository.lock_risk_flag(session, flag_id=flag_id)
            if flag is None:
                raise VoteNotFoundError("vote review flag is unavailable")
            if flag.state != "pending":
                raise VoteConflictError("vote review flag has already been decided")
            vote = await self.repository.vote_by_id(session, vote_id=flag.vote_id)
            if vote is None:
                raise VoteNotFoundError("vote review flag is unavailable")
            product = await self.product_access.voting_context(
                session, product_id=vote.product_id, lock=True
            )
            if product is None:
                raise VoteNotFoundError("vote review flag is unavailable")

            await self.repository.decide_risk_flag(session, flag=flag, outcome=outcome, now=now)
            if outcome == "invalidated":
                await self.repository.invalidate_vote(session, vote=vote, now=now)
            decision = await self.repository.add_review_decision(
                session,
                flag_id=flag.id,
                reviewer_account_id=reviewer_id,
                outcome=outcome,
                reason=normalized_reason,
                now=now,
            )
            key_id, encrypted_payload = self.codec.encode(
                {
                    "product_id": str(vote.product_id),
                    "launch_date": product.launch_date.isoformat(),
                    "outcome": outcome,
                }
            )
            await self.outbox.add(
                session,
                OutboxEvent(
                    event_type="vote.review_decided.v1",
                    aggregate_id=vote.product_id,
                    key_id=key_id,
                    encrypted_payload=encrypted_payload,
                    available_at=now,
                ),
            )
            return VoteReviewResult(
                id=decision.id,
                flag_id=flag.id,
                reviewer_account_id=reviewer_id,
                outcome=outcome,
                reason=normalized_reason,
                created_at=now,
            )


class VoteRankingProjectionService:
    """Maintain a rebuildable Redis view from PostgreSQL's launched products and votes."""

    CHANNEL_PREFIX = "launchpad:votes:ranking:"
    PAGE_SIZE = 50

    def __init__(
        self,
        *,
        products: VoteRankingProductAccess,
        repository: VoteRepository | None = None,
        redis: RankingRedis,
        snapshots: VoteSnapshotScheduler | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.products = products
        self.repository = repository or VoteRepository()
        self.redis = redis
        self.snapshots = snapshots
        self.clock = clock or (lambda: datetime.now(UTC))

    async def handle_outbox_event(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        aggregate_id: UUID,
        payload: Mapping[str, object],
    ) -> None:
        """Recompute a product from PostgreSQL; replaying an event cannot double count."""

        if event_type == "vote.snapshot_due.v1":
            if self.snapshots is None:
                raise RuntimeError("vote snapshot handler is not configured")
            await self.snapshots.handle_outbox_event(
                session,
                event_type=event_type,
                aggregate_id=aggregate_id,
                payload=payload,
            )
            return
        if event_type not in {"product.launched.v1", "vote.changed.v1", "vote.review_decided.v1"}:
            raise PermanentEventError("unsupported ranking projection event")
        raw_id = payload.get("product_id")
        raw_date = payload.get("launch_date")
        try:
            product_id = UUID(str(raw_id))
            launch_date = date.fromisoformat(str(raw_date))
        except (ValueError, TypeError) as error:
            raise PermanentEventError("ranking event has invalid product or launch date") from error
        if product_id != aggregate_id:
            raise PermanentEventError("ranking event aggregate does not match payload")
        if self.snapshots is not None:
            await self.snapshots.schedule_for_launch_date(session, launch_date)
        today = self.clock().astimezone(UTC).date()
        if launch_date != today:
            return
        await self.repository.lock_projection_product(
            session, product_id=product_id, launch_date=launch_date
        )
        product = await self.products.public_projection(session, product_id=product_id)
        if product is None:
            # Product may have been removed or is not public anymore; never cache it.
            raise PermanentEventError("ranking event does not identify a public product")
        name = getattr(product, "name", None)
        launched_at = getattr(product, "launched_at", None)
        if not isinstance(name, str) or not isinstance(launched_at, datetime):
            raise PermanentEventError("public product projection is incomplete")
        if launched_at.astimezone(UTC).date() != launch_date:
            return
        await self._store_product(session, product_id, name, launch_date)
        await self._publish_invalidation(launch_date)

    async def rebuild(self, session: AsyncSession, *, launch_date: date) -> list[LiveRankEntry]:
        """Replace the selected current-day Redis projection from durable public rows."""

        if launch_date != self.clock().astimezone(UTC).date():
            raise ValueError("only the active UTC day can be rebuilt")
        await self.repository.lock_projection_rebuild(session, launch_date=launch_date)
        score_key, metadata_key = _ranking_keys(launch_date)
        await self.redis.delete(score_key, metadata_key)
        cursor: str | None = None
        entries: list[LiveRankEntry] = []
        while True:
            page = await self.products.public_launches(
                session,
                requested_date=launch_date,
                first=self.PAGE_SIZE,
                after=cursor,
            )
            values = await self.repository.ranking_values_for_products(
                session,
                product_ids=tuple(product.id for product in page.items),
                launch_date=launch_date,
            )
            for product in page.items:
                count, score = values[product.id]
                entry = LiveRankEntry(product.id, product.name, count, score)
                entries.append(entry)
                await self._write_entry(launch_date, entry)
            cursor = page.next_cursor
            if cursor is None:
                break
        entries.sort(key=_rank_sort_key)
        await self._publish_invalidation(launch_date)
        return entries

    async def read_projection(self, *, launch_date: date) -> list[LiveRankEntry]:
        """Read and deterministically order projected entries for worker-level consumers."""

        _, metadata_key = _ranking_keys(launch_date)
        rows = await self.redis.hgetall(metadata_key)
        entries = [
            LiveRankEntry(
                product_id=UUID(product_id),
                name=str(json.loads(value)["name"]),
                active_vote_count=int(json.loads(value)["active_vote_count"]),
                score=Decimal(str(json.loads(value)["score"])),
            )
            for product_id, value in rows.items()
        ]
        entries.sort(key=_rank_sort_key)
        return entries

    async def _store_product(
        self, session: AsyncSession, product_id: UUID, name: str, launch_date: date
    ) -> LiveRankEntry:
        count, score = await self.repository.ranking_values(
            session, product_id=product_id, launch_date=launch_date
        )
        entry = LiveRankEntry(product_id, name, count, score)
        await self._write_entry(launch_date, entry)
        return entry

    async def _write_entry(self, launch_date: date, entry: LiveRankEntry) -> None:
        score_key, metadata_key = _ranking_keys(launch_date)
        member = str(entry.product_id)
        await self.redis.zadd(score_key, {member: float(entry.score)})
        await self.redis.hset(
            metadata_key,
            mapping={
                member: json.dumps(
                    {
                        "name": entry.name,
                        "active_vote_count": entry.active_vote_count,
                        "score": str(entry.score),
                    },
                    separators=(",", ":"),
                )
            },
        )
        now = self.clock().astimezone(UTC)
        next_cutoff = datetime.combine(launch_date + timedelta(days=1), datetime.min.time(), UTC)
        ttl_seconds = max(1, int((next_cutoff - now).total_seconds()))
        await self.redis.expire(score_key, ttl_seconds)
        await self.redis.expire(metadata_key, ttl_seconds)

    async def _publish_invalidation(self, launch_date: date) -> None:
        await self.redis.publish(
            f"{self.CHANNEL_PREFIX}{launch_date.isoformat()}",
            json.dumps({"type": "ranking.invalidated", "date": launch_date.isoformat()}),
        )


class VoteSnapshotService:
    """Freeze an enabled UTC date's public ranking exactly once at its cutoff."""

    PAGE_SIZE = 50

    def __init__(
        self,
        *,
        products: VoteRankingProductAccess,
        repository: VoteRepository,
        outbox: VoteSnapshotOutbox,
        codec: VotePayloadCodec,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.products = products
        self.repository = repository
        self.outbox = outbox
        self.codec = codec
        self.clock = clock or (lambda: datetime.now(UTC))

    async def schedule_for_launch_date(
        self, session: AsyncSession, launch_date: date
    ) -> UUID | None:
        """Persist one durable cutoff intent for an enabled ranking date."""

        enabled_from = await self.repository.voting_enabled_from(session)
        if enabled_from is None or launch_date < enabled_from:
            return None
        event_id = _daily_snapshot_event_id(launch_date)
        cutoff_at = datetime.combine(launch_date + timedelta(days=1), datetime.min.time(), UTC)
        key_id, encrypted_payload = self.codec.encode({"launch_date": launch_date.isoformat()})
        return await self.outbox.add_once(
            session,
            OutboxEvent(
                event_type="vote.snapshot_due.v1",
                aggregate_id=event_id,
                key_id=key_id,
                encrypted_payload=encrypted_payload,
                available_at=cutoff_at,
                id=event_id,
            ),
        )

    async def handle_outbox_event(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        aggregate_id: UUID,
        payload: Mapping[str, object],
    ) -> None:
        """Persist a unique cutoff event without revising an existing archive."""

        if event_type != "vote.snapshot_due.v1":
            raise PermanentEventError("unsupported vote snapshot event")
        try:
            launch_date = date.fromisoformat(str(payload.get("launch_date")))
        except (ValueError, TypeError) as error:
            raise PermanentEventError("vote snapshot event has an invalid date") from error
        if aggregate_id != _daily_snapshot_event_id(launch_date):
            raise PermanentEventError("vote snapshot event identity does not match its date")
        now = self.clock()
        if now.tzinfo is None:
            raise PermanentEventError("vote snapshot clock must be timezone-aware")
        now = now.astimezone(UTC)
        cutoff_at = datetime.combine(launch_date + timedelta(days=1), datetime.min.time(), UTC)
        if now < cutoff_at:
            raise PermanentEventError("vote snapshot event arrived before the UTC cutoff")
        enabled_from = await self.repository.voting_enabled_from(session)
        if enabled_from is None or launch_date < enabled_from:
            return

        products: list[PublicLaunchProduct] = []
        cursor: str | None = None
        while True:
            page = await self.products.public_launches(
                session,
                requested_date=launch_date,
                first=self.PAGE_SIZE,
                after=cursor,
            )
            products.extend(page.items)
            cursor = page.next_cursor
            if cursor is None:
                break

        values = await self.repository.snapshot_values_for_products(
            session,
            product_ids=tuple(product.id for product in products),
            cutoff_at=cutoff_at,
        )
        ranked = [
            LiveRankEntry(product.id, product.name, *values[product.id]) for product in products
        ]
        ranked.sort(key=_rank_sort_key)
        await self.repository.create_daily_snapshot(
            session,
            launch_date=launch_date,
            cutoff_at=cutoff_at,
            created_at=now,
            entries=[
                (entry.product_id, rank, entry.score, entry.active_vote_count)
                for rank, entry in enumerate(ranked, start=1)
            ],
        )


def _ranking_keys(launch_date: date) -> tuple[str, str]:
    suffix = launch_date.isoformat()
    return f"launchpad:votes:ranking:{suffix}:scores", f"launchpad:votes:ranking:{suffix}:entries"


def _daily_snapshot_event_id(launch_date: date) -> UUID:
    return uuid5(NAMESPACE_URL, f"launchpad:daily-ranking:{launch_date.isoformat()}")


def _rank_sort_key(entry: LiveRankEntry) -> tuple[bool, Decimal, int, str, str]:
    return (
        entry.active_vote_count == 0,
        -entry.score,
        -entry.active_vote_count,
        entry.name.casefold(),
        str(entry.product_id),
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
