"""Named product access policies owned by authentication."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.auth.policies import require_founder_action, require_review_staff
from app.modules.auth.sessions import MemberContext
from app.modules.auth.staff import AccountState


def test_review_queue_requires_verified_unsuspended_staff() -> None:
    now = datetime.now(UTC)
    member = MemberContext(uuid4(), True, uuid4(), role="member")
    unverified = MemberContext(uuid4(), False, uuid4(), role="reviewer")
    suspended = MemberContext(uuid4(), True, uuid4(), role="reviewer", suspended_at=now)
    active_reviewer = MemberContext(uuid4(), True, uuid4(), role="reviewer")
    active_admin = MemberContext(uuid4(), True, uuid4(), role="admin")
    for denied in (member, unverified, suspended):
        with pytest.raises(PermissionError):
            require_review_staff(denied)
    assert require_review_staff(active_reviewer) is active_reviewer
    assert require_review_staff(active_admin) is active_admin


def test_suspended_founder_can_withdraw_but_not_mutate_otherwise() -> None:
    suspended = MemberContext(uuid4(), True, uuid4(), suspended_at=datetime.now(UTC))
    for action in ("create", "edit", "upload", "submit", "delete"):
        with pytest.raises(PermissionError):
            require_founder_action(suspended, action)
    assert require_founder_action(suspended, "withdraw") is suspended


def test_unverified_founder_can_draft_but_cannot_submit() -> None:
    unverified = MemberContext(uuid4(), False, uuid4())
    for action in ("create", "edit", "upload", "delete", "withdraw"):
        assert require_founder_action(unverified, action) is unverified
    with pytest.raises(PermissionError):
        require_founder_action(unverified, "submit")


def test_live_account_state_is_accepted_by_service_policy() -> None:
    account = AccountState(uuid4(), True, "reviewer", None)
    assert require_review_staff(account) is account
    assert require_founder_action(account, "submit") is account
