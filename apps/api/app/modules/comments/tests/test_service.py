"""Transactional discussion policy and command behavior."""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from app.modules.auth.staff import AccountState
from app.modules.comments.policies import (
    CommentConflictError,
    CommentForbiddenError,
    CommentInfrastructureError,
    CommentNotFoundError,
    CommentRateLimitError,
    CommentValidationError,
    normalize_comment_body,
)
from app.modules.comments.service import CommentService

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


class _Transaction(AbstractAsyncContextManager[None]):
    def __init__(self, repository: _Repository) -> None:
        self.repository = repository
        self.snapshot: tuple[list[Any], dict[tuple[UUID, str], Any], list[Any]] | None = None

    async def __aenter__(self) -> None:
        self.snapshot = (
            list(self.repository.entries),
            dict(self.repository.receipts),
            list(self.repository.outbox.events),
        )
        return None

    async def __aexit__(self, exc_type: object, *_args: object) -> None:
        if exc_type is not None and self.snapshot is not None:
            self.repository.entries, self.repository.receipts, self.repository.outbox.events = (
                self.snapshot
            )


class _Session:
    def __init__(self, repository: _Repository) -> None:
        self.repository = repository

    def begin_nested(self) -> _Transaction:
        return _Transaction(self.repository)


class _Accounts:
    def __init__(self) -> None:
        self.account_id = uuid4()
        self.verified = True
        self.role = "member"
        self.suspended_at: datetime | None = None

    async def current_account(
        self, _session: Any, account_id: UUID, *, lock: bool = False
    ) -> AccountState | None:
        if account_id != self.account_id:
            return None
        return AccountState(account_id, self.verified, self.role, self.suspended_at)


class _Attribution:
    def __init__(self, accounts: _Accounts) -> None:
        self.accounts = accounts
        self.display_name: str | None = "Ada"
        self.has_photo = True

    async def batch(self, _session: Any, account_ids: tuple[UUID, ...]) -> dict[UUID, Any]:
        if self.accounts.account_id not in account_ids:
            return {}
        return {
            self.accounts.account_id: SimpleNamespace(
                account_id=self.accounts.account_id,
                display_name=self.display_name,
                has_photo=self.has_photo,
                public_profile_url=None,
            )
        }


class _Products:
    def __init__(self) -> None:
        self.product_id = uuid4()
        self.visible = True

    async def discussion_context(
        self, _session: Any, *, product_id: UUID, lock: bool = False
    ) -> Any | None:
        if product_id != self.product_id or not self.visible:
            return None
        return SimpleNamespace(product_id=product_id)


class _Outbox:
    def __init__(self) -> None:
        self.events: list[Any] = []
        self.fail = False

    async def add(self, _session: Any, event: Any) -> UUID:
        if self.fail:
            raise RuntimeError("outbox unavailable")
        self.events.append(event)
        return event.id or uuid4()


class _Codec:
    def encode(self, payload: Any) -> tuple[str, bytes]:
        return "test", repr(sorted(payload.items())).encode()


class _Repository:
    def __init__(self, outbox: _Outbox) -> None:
        self.entries: list[Any] = []
        self.receipts: dict[tuple[UUID, str], Any] = {}
        self.outbox = outbox

    async def lock_idempotency_key(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def get_receipt(
        self, _session: Any, *, author_id: UUID, idempotency_key: str
    ) -> Any | None:
        return self.receipts.get((author_id, idempotency_key))

    async def comment_by_id(self, _session: Any, *, comment_id: UUID) -> Any | None:
        return next((entry for entry in self.entries if entry.id == comment_id), None)

    async def visible_root(self, _session: Any, *, product_id: UUID, parent_id: UUID) -> Any | None:
        return next(
            (
                entry
                for entry in self.entries
                if entry.id == parent_id
                and entry.product_id == product_id
                and entry.depth == 0
                and entry.moderation_status == "visible"
            ),
            None,
        )

    async def author_activity(
        self, _session: Any, *, author_id: UUID, since: datetime
    ) -> tuple[datetime, ...]:
        return tuple(
            sorted(
                entry.created_at
                for entry in self.entries
                if entry.author_account_id == author_id and entry.created_at >= since
            )
        )

    async def has_recent_duplicate(
        self,
        _session: Any,
        *,
        author_id: UUID,
        product_id: UUID,
        body_fingerprint: str,
        since: datetime,
    ) -> bool:
        return any(
            entry.author_account_id == author_id
            and entry.product_id == product_id
            and entry.body_fingerprint == body_fingerprint
            and entry.created_at >= since
            for entry in self.entries
        )

    async def create_comment(self, _session: Any, **values: Any) -> Any:
        author_id = values.pop("author_id")
        entry = SimpleNamespace(
            id=uuid4(),
            author_account_id=author_id,
            moderation_status="visible",
            parent_depth=0 if values["depth"] else None,
            **values,
        )
        self.entries.append(entry)
        return entry

    async def add_receipt(self, _session: Any, **values: Any) -> Any:
        author_id = values.pop("author_id")
        values["author_account_id"] = author_id
        receipt = SimpleNamespace(id=uuid4(), **values)
        self.receipts[(receipt.author_account_id, receipt.idempotency_key)] = receipt
        return receipt

    async def list_roots(self, *_args: Any, **_kwargs: Any) -> tuple[tuple[Any, ...], str | None]:
        roots = tuple(entry for entry in reversed(self.entries) if entry.depth == 0)
        return roots, None

    async def reply_summaries(self, *_args: Any, **_kwargs: Any) -> dict[UUID, Any]:
        return {}

    async def list_replies(
        self, _session: Any, *, product_id: UUID, parent_id: UUID, **_kwargs: Any
    ) -> tuple[tuple[Any, ...], str | None]:
        replies = tuple(
            entry
            for entry in self.entries
            if entry.product_id == product_id and entry.parent_id == parent_id
        )
        return replies, None


def _build() -> tuple[CommentService, _Accounts, _Attribution, _Products, _Repository, _Outbox]:
    accounts, products, outbox = _Accounts(), _Products(), _Outbox()
    attribution = _Attribution(accounts)
    repository = _Repository(outbox)
    service = CommentService(
        account_access=cast(Any, accounts),
        attribution_access=cast(Any, attribution),
        product_access=cast(Any, products),
        repository=cast(Any, repository),
        outbox=cast(Any, outbox),
        codec=cast(Any, _Codec()),
        writes_enabled=lambda: True,
        clock=lambda: NOW,
    )
    return service, accounts, attribution, products, repository, outbox


def test_body_normalization_is_plain_text_bounded_and_stable() -> None:
    assert normalize_comment_body("  hello <b>world</b>  ") == "hello <b>world</b>"
    for body in ("   ", "x" * 2001):
        with pytest.raises(CommentValidationError):
            normalize_comment_body(body)


@pytest.mark.parametrize(
    "failure", ["missing", "unverified", "suspended", "staff", "name", "photo"]
)
def test_only_verified_active_community_accounts_with_attribution_can_post(failure: str) -> None:
    async def verify() -> None:
        service, accounts, attribution, products, repository, _ = _build()
        actor_id = accounts.account_id
        if failure == "missing":
            actor_id = uuid4()
        elif failure == "unverified":
            accounts.verified = False
        elif failure == "suspended":
            accounts.suspended_at = NOW
        elif failure == "staff":
            accounts.role = "reviewer"
        elif failure == "name":
            attribution.display_name = None
        else:
            attribution.has_photo = False
        with pytest.raises(CommentForbiddenError):
            await service.create_root(
                cast(Any, _Session(repository)),
                author_id=actor_id,
                product_id=products.product_id,
                body="Hello",
                idempotency_key="post-1",
            )
        assert repository.entries == []

    asyncio.run(verify())


def test_post_rechecks_visibility_and_reply_parent_without_disclosure() -> None:
    async def verify() -> None:
        service, accounts, _, products, repository, _ = _build()
        session = cast(Any, _Session(repository))
        products.visible = False
        with pytest.raises(CommentNotFoundError):
            await service.create_root(
                session,
                author_id=accounts.account_id,
                product_id=products.product_id,
                body="Hidden",
                idempotency_key="hidden",
            )
        products.visible = True
        with pytest.raises(CommentNotFoundError):
            await service.create_reply(
                session,
                author_id=accounts.account_id,
                product_id=products.product_id,
                parent_id=uuid4(),
                body="No parent",
                idempotency_key="bad-parent",
            )

    asyncio.run(verify())


def test_exact_replay_returns_original_and_changed_request_conflicts() -> None:
    async def verify() -> None:
        service, accounts, _, products, repository, outbox = _build()
        session = cast(Any, _Session(repository))
        original = await service.create_root(
            session,
            author_id=accounts.account_id,
            product_id=products.product_id,
            body="First",
            idempotency_key="same",
        )
        replay = await service.create_root(
            session,
            author_id=accounts.account_id,
            product_id=products.product_id,
            body="First",
            idempotency_key="same",
        )
        assert replay.entry.id == original.entry.id and replay.replayed is True
        with pytest.raises(CommentConflictError):
            await service.create_root(
                session,
                author_id=accounts.account_id,
                product_id=products.product_id,
                body="Changed",
                idempotency_key="same",
            )
        assert len(repository.entries) == len(repository.receipts) == len(outbox.events) == 1

    asyncio.run(verify())


def test_duplicate_limits_and_outbox_failure_leave_no_partial_post() -> None:
    async def verify() -> None:
        service, accounts, _, products, repository, outbox = _build()
        session = cast(Any, _Session(repository))
        await service.create_root(
            session,
            author_id=accounts.account_id,
            product_id=products.product_id,
            body="Repeat",
            idempotency_key="first",
        )
        with pytest.raises(CommentConflictError):
            await service.create_root(
                session,
                author_id=accounts.account_id,
                product_id=products.product_id,
                body=" Repeat ",
                idempotency_key="duplicate",
            )
        for index in range(4):
            await service.create_root(
                session,
                author_id=accounts.account_id,
                product_id=products.product_id,
                body=f"Allowed {index}",
                idempotency_key=f"allowed-{index}",
            )
        with pytest.raises(CommentRateLimitError) as limited:
            await service.create_root(
                session,
                author_id=accounts.account_id,
                product_id=products.product_id,
                body="Sixth",
                idempotency_key="sixth",
            )
        assert limited.value.retry_at == NOW + timedelta(seconds=60)
        service.clock = lambda: NOW + timedelta(minutes=2)
        outbox.fail = True
        with pytest.raises(CommentInfrastructureError):
            await service.create_root(
                session,
                author_id=accounts.account_id,
                product_id=products.product_id,
                body="Atomic",
                idempotency_key="atomic",
            )
        assert all(entry.body != "Atomic" for entry in repository.entries)
        assert (accounts.account_id, "atomic") not in repository.receipts

    asyncio.run(verify())


def test_daily_limit_and_duplicate_window_expiry_are_exact() -> None:
    async def verify() -> None:
        service, accounts, _, products, repository, _ = _build()
        session = cast(Any, _Session(repository))
        repository.entries = [
            SimpleNamespace(
                id=uuid4(),
                product_id=products.product_id,
                author_account_id=accounts.account_id,
                depth=0,
                parent_id=None,
                body=f"History {index}",
                body_fingerprint=f"{index:064x}",
                moderation_status="visible",
                created_at=NOW - timedelta(hours=1) + timedelta(seconds=index),
            )
            for index in range(100)
        ]
        with pytest.raises(CommentRateLimitError) as limited:
            await service.create_root(
                session,
                author_id=accounts.account_id,
                product_id=products.product_id,
                body="Daily excess",
                idempotency_key="daily-excess",
            )
        assert limited.value.retry_at == NOW + timedelta(hours=23)

        repository.entries.clear()
        await service.create_root(
            session,
            author_id=accounts.account_id,
            product_id=products.product_id,
            body="May repeat later",
            idempotency_key="duplicate-window-first",
        )
        service.clock = lambda: NOW + timedelta(minutes=5, microseconds=1)
        repeated = await service.create_root(
            session,
            author_id=accounts.account_id,
            product_id=products.product_id,
            body=" May repeat later ",
            idempotency_key="duplicate-window-later",
        )
        assert repeated.entry.body == "May repeat later"

    asyncio.run(verify())


def test_public_reads_require_current_visibility_and_validate_parent() -> None:
    async def verify() -> None:
        service, _, _, products, repository, _ = _build()
        session = cast(Any, _Session(repository))
        products.visible = False
        with pytest.raises(CommentNotFoundError):
            await service.discussion(session, product_id=products.product_id)
        products.visible = True
        with pytest.raises(CommentNotFoundError):
            await service.replies(session, product_id=products.product_id, parent_id=uuid4())

    asyncio.run(verify())
