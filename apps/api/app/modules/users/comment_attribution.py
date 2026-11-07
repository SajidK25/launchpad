"""Users-owned current attribution and contextual photo boundary for discussion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.repository import (
    CommentAttributionRow,
    ProfileRepository,
    ValidatedCommentPhoto,
)
from app.shared.storage.objects import ObjectNotFound


class CommentPhotoStorage(Protocol):
    async def get_private(self, *, object_key: str) -> tuple[bytes, str | None]: ...


class CommentAttributionRepository(Protocol):
    async def comment_attribution_rows(
        self, session: AsyncSession, account_ids: tuple[UUID, ...]
    ) -> list[CommentAttributionRow]: ...

    async def current_validated_comment_photo(
        self, session: AsyncSession, account_id: UUID
    ) -> ValidatedCommentPhoto | None: ...


@dataclass(frozen=True, slots=True)
class CommentAuthorAttribution:
    """Only current public-speech attribution; never private identity fields."""

    account_id: UUID
    display_name: str | None
    has_photo: bool
    public_profile_url: str | None


@dataclass(frozen=True, slots=True)
class CommentAuthorPhoto:
    """Validated contextual image bytes without its private object key."""

    body: bytes
    media_type: str


class CommentAttributionService:
    """Resolve bounded current attribution while preserving profile-link privacy."""

    MAX_BATCH = 100

    def __init__(
        self,
        *,
        repository: CommentAttributionRepository | None = None,
        storage: CommentPhotoStorage,
    ) -> None:
        self.repository = repository or ProfileRepository()
        self.storage = storage

    async def batch(
        self, session: AsyncSession, account_ids: tuple[UUID, ...]
    ) -> dict[UUID, CommentAuthorAttribution]:
        unique_ids = tuple(dict.fromkeys(account_ids))
        if not unique_ids:
            return {}
        if len(unique_ids) > self.MAX_BATCH:
            raise ValueError("comment attribution batch is too large")
        rows = await self.repository.comment_attribution_rows(session, unique_ids)
        return {
            row.account_id: CommentAuthorAttribution(
                account_id=row.account_id,
                display_name=row.display_name,
                has_photo=row.has_validated_photo,
                public_profile_url=(
                    f"/public/{row.account_id}" if row.visibility == "public" else None
                ),
            )
            for row in rows
        }

    async def read_photo(
        self, session: AsyncSession, account_id: UUID
    ) -> CommentAuthorPhoto | None:
        current = await self.repository.current_validated_comment_photo(session, account_id)
        if current is None:
            return None
        try:
            body, _stored_media_type = await self.storage.get_private(object_key=current.object_key)
        except ObjectNotFound:
            return None
        return CommentAuthorPhoto(body=body, media_type=current.media_type)
