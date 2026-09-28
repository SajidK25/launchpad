"""Profile domain operations with owner authorization and atomic privacy changes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import Profile
from app.modules.users.policies import (
    ProfileConflictError,
    ProfileError,
    ProfileForbiddenError,
    ProfileInfrastructureError,
    ProfileValidationError,
    is_complete,
    require_complete,
    require_owner,
    require_verified,
    validate_profile_fields,
)
from app.modules.users.repository import ProfileRepository
from app.shared.events.outbox import OutboxEvent

_UNSET = object()


@dataclass(frozen=True, slots=True)
class MemberIdentity:
    """Minimal auth-owned identity exposed to the users feature."""

    account_id: UUID
    email_display: str
    verified: bool


class MemberAccess(Protocol):
    """Named cross-module interface; users never imports the auth repository."""

    async def get_member(
        self, session: AsyncSession, account_id: UUID, *, lock: bool = False
    ) -> MemberIdentity | None: ...


@dataclass(frozen=True, slots=True)
class ProfileResult:
    """Profile data returned by domain operations."""

    profile: ProfileView
    links: list[str]
    became_private: bool = False


@dataclass(frozen=True, slots=True)
class ProfileView:
    """Explicit profile fields safe for transport mapping."""

    account_id: UUID
    display_name: str | None
    bio: str | None
    photo_key: str | None
    visibility: str
    published_at: datetime | None
    version: int


class ProfileService:
    """Own profile lifecycle decisions and transactional privacy notifications."""

    def __init__(
        self,
        *,
        repository: Any | None = None,
        member_access: MemberAccess,
        outbox_repository: Any,
        payload_codec: Any,
        mail_web_origin: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository or ProfileRepository()
        self.member_access = member_access
        self.outbox_repository = outbox_repository
        self.payload_codec = payload_codec
        self.mail_web_origin = mail_web_origin.rstrip("/")
        self.clock = clock or (lambda: datetime.now(UTC))

    async def get_owner(self, session: Any, *, actor_id: UUID, account_id: UUID) -> ProfileResult:
        """Return a profile only to its owner."""

        await self._require_member(session, actor_id)
        require_owner(actor_id, account_id)
        loaded = await self.repository.get(session, account_id)
        if loaded is None:
            raise ProfileForbiddenError("profile access is forbidden")
        profile, links = loaded
        return _result(profile, links)

    async def get_public(self, session: Any, *, account_id: UUID) -> ProfileResult | None:
        """Return public profiles; private drafts are indistinguishable from absent."""

        loaded = await self.repository.get(session, account_id)
        if loaded is None:
            return None
        profile, links = loaded
        return _result(profile, links) if profile.visibility == "public" else None

    async def update_profile(
        self,
        session: Any,
        *,
        actor_id: UUID,
        display_name: str | None | object = _UNSET,
        bio: str | None | object = _UNSET,
        photo_key: str | None | object = _UNSET,
        links: list[str] | object = _UNSET,
        expected_version: int | None = None,
    ) -> ProfileResult:
        """Save an owner edit and automatically privatize an incomplete public profile."""

        await self._require_member(session, actor_id, lock=True)
        loaded = await self.repository.get(session, actor_id, lock=True)
        if loaded is None:
            raise ProfileForbiddenError("profile access is forbidden")
        profile, current_links = loaded
        values: dict[str, object] = {
            "display_name": profile.display_name if display_name is _UNSET else display_name,
            "bio": profile.bio if bio is _UNSET else bio,
            "photo_key": profile.photo_key if photo_key is _UNSET else photo_key,
            "links": current_links if links is _UNSET else links,
        }
        if not isinstance(values["links"], list):
            raise ProfileValidationError("profile links are invalid")
        display_name_value = cast(str | None, values["display_name"])
        bio_value = cast(str | None, values["bio"])
        photo_key_value = cast(str | None, values["photo_key"])
        links_value = cast(list[str], values["links"])
        validate_profile_fields(
            display_name=display_name_value,
            bio=bio_value,
            photo_key=photo_key_value,
            links=links_value,
        )
        await self._require_validated_photo(session, actor_id, photo_key_value)
        was_public = profile.visibility == "public"
        candidate = _candidate(profile, values)
        became_private = was_public and not is_complete(candidate, links_value)
        visibility = "private" if became_private else profile.visibility
        published_at = None if became_private else profile.published_at
        saved = await self.repository.save(
            session,
            account_id=actor_id,
            expected_version=profile.version if expected_version is None else expected_version,
            display_name=display_name_value,
            bio=bio_value,
            photo_key=photo_key_value,
            links=links_value,
            visibility=visibility,
            published_at=published_at,
        )
        result = replace(_result(*saved), became_private=became_private)
        if became_private:
            await self._enqueue_privacy_notice(session, actor_id)
        return result

    async def publish(
        self, session: Any, *, actor_id: UUID, expected_version: int | None = None
    ) -> ProfileResult:
        """Publish a complete profile only after checking current verification state."""

        member = await self.member_access.get_member(session, actor_id, lock=True)
        if member is None:
            raise ProfileForbiddenError("profile access is forbidden")
        require_verified(member.verified)
        loaded = await self.repository.get(session, actor_id, lock=True)
        if loaded is None:
            raise ProfileForbiddenError("profile access is forbidden")
        profile, links = loaded
        validate_profile_fields(
            display_name=profile.display_name,
            bio=profile.bio,
            photo_key=profile.photo_key,
            links=links,
        )
        await self._require_validated_photo(session, actor_id, profile.photo_key, lock=True)
        require_complete(profile, links)
        saved = await self.repository.save(
            session,
            account_id=actor_id,
            expected_version=profile.version if expected_version is None else expected_version,
            display_name=profile.display_name,
            bio=profile.bio,
            photo_key=profile.photo_key,
            links=links,
            visibility="public",
            published_at=self.clock(),
        )
        return _result(*saved)

    async def unpublish(
        self, session: Any, *, actor_id: UUID, expected_version: int | None = None
    ) -> ProfileResult:
        """Make a profile private without sending the automatic-incompleteness notice."""

        await self._require_member(session, actor_id, lock=True)
        loaded = await self.repository.get(session, actor_id, lock=True)
        if loaded is None:
            raise ProfileForbiddenError("profile access is forbidden")
        profile, links = loaded
        saved = await self.repository.save(
            session,
            account_id=actor_id,
            expected_version=profile.version if expected_version is None else expected_version,
            display_name=profile.display_name,
            bio=profile.bio,
            photo_key=profile.photo_key,
            links=links,
            visibility="private",
            published_at=None,
        )
        return _result(*saved)

    async def resolve_photo_upload(self, session: Any, *, actor_id: UUID, upload_id: UUID) -> str:
        """Resolve an owner-scoped cleaned upload for a profile edit."""

        await self._require_member(session, actor_id)
        key = await self.repository.get_validated_photo_key(session, actor_id, upload_id)
        if key is None:
            raise ProfileValidationError("photo upload is not ready")
        return key

    async def _require_member(
        self, session: Any, account_id: UUID, *, lock: bool = False
    ) -> MemberIdentity:
        member = await self.member_access.get_member(session, account_id, lock=lock)
        if member is None or member.account_id != account_id:
            raise ProfileForbiddenError("profile access is forbidden")
        return member

    async def _require_validated_photo(
        self, session: Any, account_id: UUID, photo_key: str | None, *, lock: bool = False
    ) -> None:
        if photo_key is None:
            return
        checker = getattr(self.repository, "has_validated_photo", None)
        if checker is None or not await checker(session, account_id, photo_key, lock=lock):
            raise ProfileValidationError("photo is not a validated private photo")

    async def _enqueue_privacy_notice(self, session: Any, account_id: UUID) -> None:
        member = await self._require_member(session, account_id)
        if member is None:
            raise ProfileForbiddenError("profile access is forbidden")
        now = self.clock()
        try:
            profile_url = f"{self.mail_web_origin}/profile"
            key_id, encrypted_payload = self.payload_codec.encode(
                {
                    "recipient": member.email_display,
                    "subject": "Your profile is private",
                    "body": f"Your profile is now private. Review it at {profile_url}",
                }
            )
            await self.outbox_repository.add(
                session,
                OutboxEvent(
                    event_type="users.profile_became_private.v1",
                    aggregate_id=account_id,
                    key_id=key_id,
                    encrypted_payload=encrypted_payload,
                    available_at=now,
                ),
            )
        except ProfileError:
            raise
        except Exception as error:
            raise ProfileInfrastructureError("privacy notice could not be queued") from error


class ProfileBootstrap:
    """Create the private profile paired with a newly registered account."""

    def __init__(self, repository: ProfileRepository | None = None) -> None:
        self.repository = repository or ProfileRepository()

    async def create_private_profile(self, session: AsyncSession, account_id: UUID) -> Profile:
        return await self.repository.create_private(session, account_id)


def _candidate(profile: Profile, values: dict[str, object]) -> Profile:
    """Build a validation-only profile value without mutating the persisted row."""

    return Profile(
        account_id=profile.account_id,
        display_name=cast(str | None, values["display_name"]),
        bio=cast(str | None, values["bio"]),
        photo_key=cast(str | None, values["photo_key"]),
        visibility=profile.visibility,
        published_at=profile.published_at,
        version=profile.version,
    )


def _result(profile: Profile, links: list[str]) -> ProfileResult:
    return ProfileResult(
        ProfileView(
            account_id=profile.account_id,
            display_name=profile.display_name,
            bio=profile.bio,
            photo_key=profile.photo_key,
            visibility=profile.visibility,
            published_at=profile.published_at,
            version=profile.version,
        ),
        links,
    )


__all__ = [
    "MemberAccess",
    "MemberIdentity",
    "ProfileBootstrap",
    "ProfileConflictError",
    "ProfileError",
    "ProfileForbiddenError",
    "ProfileInfrastructureError",
    "ProfileResult",
    "ProfileView",
    "ProfileService",
    "ProfileValidationError",
]
