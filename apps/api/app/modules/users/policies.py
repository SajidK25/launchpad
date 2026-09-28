"""Named authorization and publication rules for member profiles."""

from __future__ import annotations

from urllib.parse import urlsplit
from uuid import UUID

from app.modules.users.models import Profile


class ProfileError(RuntimeError):
    """Base profile-domain error safe to map at a transport boundary."""


class ProfileForbiddenError(ProfileError):
    """The member is not allowed to perform the requested profile action."""


class ProfileValidationError(ProfileError):
    """Profile input or publication requirements are invalid."""


class ProfileConflictError(ProfileError):
    """A profile changed after the caller read it."""


class ProfileInfrastructureError(ProfileError):
    """A dependent infrastructure operation failed transactionally."""


def require_owner(actor_id: UUID, owner_id: UUID) -> None:
    """Allow private profile operations only to the owning member."""

    if actor_id != owner_id:
        raise ProfileForbiddenError("profile access is forbidden")


def require_verified(verified: bool) -> None:
    """Require mailbox verification before public publication."""

    if not verified:
        raise ProfileForbiddenError("email verification is required")


def validate_profile_fields(
    *,
    display_name: str | None,
    bio: str | None,
    photo_key: str | None,
    links: list[str],
) -> None:
    """Validate draft values without requiring a draft to be complete."""

    if display_name is not None and len(display_name) > 200:
        raise ProfileValidationError("display name is too long")
    if bio is not None and (len(bio) > 160 or "\n" in bio or "\r" in bio):
        raise ProfileValidationError("bio must be one line and at most 160 characters")
    if photo_key is not None and not _is_clean_photo_key(photo_key):
        raise ProfileValidationError("photo is not a validated private photo")
    if len(links) > 20:
        raise ProfileValidationError("too many profile links")
    if any(not _is_public_https_url(link) for link in links):
        raise ProfileValidationError("profile links must be public HTTPS URLs")


def require_complete(
    profile: Profile,
    links: list[str],
) -> None:
    """Require all fields needed for a public profile."""

    if not profile.display_name or not profile.display_name.strip():
        raise ProfileValidationError("display name is required to publish")
    if not profile.bio or not profile.bio.strip():
        raise ProfileValidationError("bio is required to publish")
    if not profile.photo_key or not _is_clean_photo_key(profile.photo_key):
        raise ProfileValidationError("a validated photo is required to publish")
    if not links:
        raise ProfileValidationError("at least one public link is required to publish")


def is_complete(profile: Profile, links: list[str]) -> bool:
    """Return whether current persisted values satisfy publication requirements."""

    try:
        require_complete(profile, links)
    except ProfileValidationError:
        return False
    return True


def _is_public_https_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and not parsed.fragment
    )


def _is_clean_photo_key(value: str) -> bool:
    parts = value.split("/")
    return (
        len(parts) == 3
        and parts[0] == "profile-clean"
        and len(parts[1]) == 32
        and len(parts[2]) == 32
        and all(character in "0123456789abcdef" for part in parts[1:] for character in part)
    )
