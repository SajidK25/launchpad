"""Named authorization policies for identity contexts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from app.modules.auth.sessions import MemberContext, UnauthenticatedError


class UnverifiedMemberError(PermissionError):
    """The member is authenticated but email verification is required."""


class AuthorizationState(Protocol):
    """Fields shared by live session and locked account snapshots."""

    @property
    def verified(self) -> bool: ...

    @property
    def role(self) -> str: ...

    @property
    def suspended_at(self) -> datetime | None: ...


def require_authenticated(member: MemberContext) -> MemberContext:
    if member is None:
        raise UnauthenticatedError("authentication required")
    return member


def require_owner(member: MemberContext, account_id: UUID) -> MemberContext:
    if member.account_id != account_id:
        raise PermissionError("owner access required")
    return member


def require_verified[StateT: AuthorizationState](member: StateT) -> StateT:
    if not member.verified:
        raise UnverifiedMemberError("email verification required")
    return member


def require_review_staff[StateT: AuthorizationState](member: StateT) -> StateT:
    """Permit current verified reviewer/admin access to pending review only."""

    if (
        not member.verified
        or member.suspended_at is not None
        or member.role
        not in {
            "reviewer",
            "admin",
        }
    ):
        raise PermissionError("review staff access required")
    return member


FounderAction = Literal["create", "edit", "upload", "submit", "delete", "withdraw"]


def require_founder_action[StateT: AuthorizationState](
    member: StateT, action: FounderAction
) -> StateT:
    """Suspension blocks product changes except an explicit withdrawal."""

    if member.suspended_at is not None and action != "withdraw":
        raise PermissionError("founder action unavailable")
    if action == "submit":
        require_verified(member)
    return member
