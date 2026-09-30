"""Named product owner, suspension, state, and version policies."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from uuid import UUID

from app.modules.auth.staff import AccountState

PRODUCT_MEDIA_URL_TTL_SECONDS = 300


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


def create_product_media_signature(session_secret: str, path: str, expires_at: int) -> str:
    """Sign a canonical media path and expiry with the opaque current session secret."""

    payload = f"launchpad-product-media-v1\n{path}\n{expires_at}".encode()
    return hmac.new(session_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def verify_product_media_signature(
    session_secret: str,
    path: str,
    expires_at: int,
    signature: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Verify session binding, exact path/expiry, and the bounded validity window."""

    current = now or datetime.now(UTC)
    remaining = expires_at - current.timestamp()
    if remaining <= 0 or remaining > PRODUCT_MEDIA_URL_TTL_SECONDS:
        return False
    expected = create_product_media_signature(session_secret, path, expires_at)
    return hmac.compare_digest(expected, signature)


def require_active_founder(account: AccountState | None) -> AccountState:
    """Require a current, unsuspended account; verification is not needed for private drafts."""

    if account is None:
        raise ProductForbiddenError("product access is forbidden")
    if account.suspended_at is not None:
        raise ProductForbiddenError("product access is forbidden")
    return account


def require_staff_reviewer(account: AccountState | None) -> AccountState:
    """Require live, verified, unsuspended reviewer or admin access."""

    if (
        account is None
        or not account.verified
        or account.suspended_at is not None
        or account.role not in {"reviewer", "admin"}
    ):
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
