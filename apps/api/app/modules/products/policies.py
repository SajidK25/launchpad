"""Named product owner, suspension, state, and version policies."""

from __future__ import annotations

from uuid import UUID

from app.modules.auth.staff import AccountState


class ProductError(ValueError):
    """Base class for typed, safely mappable product domain failures."""


class ProductForbiddenError(ProductError):
    """The current account cannot perform this product action."""


class ProductNotFoundError(ProductError):
    """A private product is unavailable to this caller."""


class ProductConflictError(ProductError):
    """The product changed or entered a state that rejects this operation."""


class ProductQuotaError(ProductError):
    """The founder reached an active product limit."""


class ProductInfrastructureError(ProductError):
    """A dependency required to complete the product operation failed."""


def require_active_founder(account: AccountState | None) -> AccountState:
    """Require a current, unsuspended account; verification is not needed for private drafts."""

    if account is None:
        raise ProductForbiddenError("product access is forbidden")
    if account.suspended_at is not None:
        raise ProductForbiddenError("product access is forbidden")
    return account


def require_product_owner(*, actor_id: UUID, founder_id: UUID) -> None:
    """Hide a private product from anyone except its founder."""

    if actor_id != founder_id:
        raise ProductNotFoundError("product unavailable")


def require_draft_status(status: str) -> None:
    """Permit draft-only operations only while the product remains a draft."""

    if status != "draft":
        raise ProductConflictError("product is no longer an editable draft")


def require_expected_version(*, current: int, expected: int) -> None:
    """Reject stale writes without replacing newer content."""

    if current != expected:
        raise ProductConflictError("product changed; reload and retry")
