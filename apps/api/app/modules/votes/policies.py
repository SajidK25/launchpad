"""Named member and product eligibility decisions for voting."""

from __future__ import annotations

from datetime import date

from app.modules.auth.staff import AccountState


class VoteError(ValueError):
    """Base for domain failures safe to map at transport boundaries."""


class VoteForbiddenError(VoteError):
    """The member is not allowed to vote."""


class VoteNotFoundError(VoteError):
    """The target is not publicly available for voting."""


class VoteConflictError(VoteError):
    """The request conflicts with existing vote or cutoff state."""


class VoteRateLimitError(VoteError):
    """The member exceeded a configured command velocity limit."""


class VoteChallengeError(VoteError):
    """A required risk challenge was not satisfied."""


class VoteInfrastructureError(VoteError):
    """A required persistence or ranking dependency is unavailable."""


def require_voting_member(account: AccountState | None) -> AccountState:
    """Require an existing verified member that is not suspended."""

    if (
        account is None
        or not account.verified
        or account.suspended_at is not None
        or account.role != "member"
    ):
        raise VoteForbiddenError("voting is unavailable for this account")
    return account


def require_vote_reviewer(account: AccountState | None) -> AccountState:
    """Require a verified, active reviewer or admin for explicit flag decisions."""

    if (
        account is None
        or not account.verified
        or account.suspended_at is not None
        or account.role not in {"reviewer", "admin"}
    ):
        raise VoteForbiddenError("vote review access is unavailable for this account")
    return account


def require_public_other_product(*, member_id: object, owner_id: object, launched: bool) -> None:
    """Require a publicly launched product owned by another account."""

    if not launched:
        raise VoteNotFoundError("product is unavailable for voting")
    if member_id == owner_id:
        raise VoteForbiddenError("members cannot vote for their own products")


def require_open_launch_day(*, launch_date: date, today_utc: date) -> None:
    """Permit vote changes only on the product's UTC launch day."""

    if launch_date != today_utc:
        raise VoteConflictError("voting is closed for this launch")


def validate_idempotency_key(value: str) -> str:
    """Require a bounded, whitespace-normalized idempotency key."""

    key = value.strip()
    if key != value or not 1 <= len(key) <= 255:
        raise VoteConflictError("invalid idempotency key")
    return key
