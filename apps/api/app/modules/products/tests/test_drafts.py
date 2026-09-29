"""Product draft authorization and version policies."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.modules.auth.staff import AccountState
from app.modules.products.policies import (
    ProductForbiddenError,
    ProductNotFoundError,
    require_active_founder,
    require_product_owner,
)


def test_unverified_member_may_prepare_private_draft() -> None:
    account = AccountState(account_id=uuid4(), verified=False, role="member", suspended_at=None)

    require_active_founder(account)


def test_suspended_member_cannot_create_or_edit_drafts() -> None:
    account = AccountState(account_id=uuid4(), verified=True, role="member", suspended_at=None)
    suspended = AccountState(
        account_id=account.account_id,
        verified=True,
        role="member",
        suspended_at=datetime.now(UTC),
    )

    with pytest.raises(ProductForbiddenError):
        require_active_founder(suspended)


def test_non_owner_receives_the_same_private_product_not_found_policy() -> None:
    with pytest.raises(ProductNotFoundError, match="product unavailable"):
        require_product_owner(actor_id=uuid4(), founder_id=uuid4())
