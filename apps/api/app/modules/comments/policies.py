"""Named validation and authorization decisions for public discussion."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.modules.auth.staff import AccountState


class CommentError(ValueError):
    """Base for typed discussion failures safe for transport mapping."""


class CommentValidationError(CommentError):
    """A body, key, cursor, or page argument is malformed."""


class CommentForbiddenError(CommentError):
    """The current account may read but may not publish discussion."""


class CommentNotFoundError(CommentError):
    """The product or requested thread is not currently public."""


class CommentConflictError(CommentError):
    """The command conflicts with immutable discussion state."""


class CommentRateLimitError(CommentError):
    """The author exceeded an authoritative rolling publication limit."""

    def __init__(self, message: str, *, retry_at: datetime) -> None:
        super().__init__(message)
        self.retry_at = retry_at


class CommentInfrastructureError(CommentError):
    """A required transactional dependency could not record the command."""


class AuthorAttribution(Protocol):
    """Minimum current attribution required for public speech."""

    display_name: str | None
    has_photo: bool


def require_comment_author(
    account: AccountState | None, attribution: AuthorAttribution | None
) -> AccountState:
    """Permit verified active community accounts with complete attribution."""

    if (
        account is None
        or not account.verified
        or account.suspended_at is not None
        or account.role != "member"
        or attribution is None
        or not isinstance(attribution.display_name, str)
        or not attribution.display_name.strip()
        or not attribution.has_photo
    ):
        raise CommentForbiddenError("discussion posting is unavailable for this account")
    return account


def normalize_comment_body(value: str) -> str:
    """Trim surrounding Unicode whitespace and enforce the plain-text bound."""

    body = value.strip()
    if not 1 <= len(body) <= 2_000:
        raise CommentValidationError("comment body must be between 1 and 2000 characters")
    return body


def validate_idempotency_key(value: str) -> str:
    """Require an opaque bounded key without silently changing it."""

    if value != value.strip() or not 1 <= len(value) <= 255:
        raise CommentValidationError("invalid idempotency key")
    return value


def validate_page_size(value: int) -> int:
    """Keep every public discussion page within the approved bound."""

    if not 1 <= value <= 20:
        raise CommentValidationError("discussion page size must be between 1 and 20")
    return value
