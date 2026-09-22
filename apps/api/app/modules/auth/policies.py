"""Named authorization policies for identity contexts."""

from __future__ import annotations

from uuid import UUID

from app.modules.auth.sessions import MemberContext, UnauthenticatedError


class UnverifiedMemberError(PermissionError):
    """The member is authenticated but email verification is required."""


def require_authenticated(member: MemberContext) -> MemberContext:
    if member is None:
        raise UnauthenticatedError("authentication required")
    return member


def require_owner(member: MemberContext, account_id: UUID) -> MemberContext:
    if member.account_id != account_id:
        raise PermissionError("owner access required")
    return member


def require_verified(member: MemberContext) -> MemberContext:
    if not member.verified:
        raise UnverifiedMemberError("email verification required")
    return member
