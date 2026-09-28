"""Profile persistence boundary used by auth registration bootstrap."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.modules.users.models import PhotoUpload, Profile, ProfileLink


class ProfileRepository:
    """Own profile writes without depending on auth repositories."""

    async def create_private(self, session: AsyncSession, account_id: UUID) -> Profile:
        await session.execute(
            insert(Profile).values(
                account_id=account_id,
                visibility="private",
                version=0,
            )
        )
        return Profile(account_id=account_id, visibility="private", version=0)

    async def get(
        self, session: AsyncSession, account_id: UUID, *, lock: bool = False
    ) -> tuple[Profile, list[str]] | None:
        """Load one profile and its ordered links, optionally locking the row."""

        query = select(Profile).where(Profile.account_id == account_id)
        if lock:
            query = query.with_for_update()
        profile = await session.scalar(query)
        if profile is None:
            return None
        links = list(
            (
                await session.scalars(
                    select(ProfileLink.url)
                    .where(ProfileLink.account_id == account_id)
                    .order_by(ProfileLink.position, ProfileLink.id)
                )
            ).all()
        )
        return profile, links

    async def has_validated_photo(
        self,
        session: AsyncSession,
        account_id: UUID,
        photo_key: str,
        *,
        lock: bool = False,
    ) -> bool:
        """Verify that a clean photo belongs to the account and is publishable."""

        query = select(PhotoUpload.id).where(
            PhotoUpload.account_id == account_id,
            PhotoUpload.clean_key == photo_key,
            PhotoUpload.state == "cleaned",
            PhotoUpload.byte_count.is_not(None),
            PhotoUpload.byte_count > 0,
            PhotoUpload.byte_count <= 5 * 1024 * 1024,
            PhotoUpload.media_type.in_(("image/jpeg", "image/png", "image/webp")),
        )
        if lock:
            query = query.with_for_update()
        return await session.scalar(query) is not None

    async def get_validated_photo_key(
        self,
        session: AsyncSession,
        account_id: UUID,
        upload_id: UUID,
        *,
        lock: bool = False,
    ) -> str | None:
        """Resolve one owner's cleaned upload to its opaque object key."""

        query = select(PhotoUpload.clean_key).where(
            PhotoUpload.id == upload_id,
            PhotoUpload.account_id == account_id,
            PhotoUpload.state == "cleaned",
            PhotoUpload.byte_count.is_not(None),
            PhotoUpload.byte_count > 0,
            PhotoUpload.byte_count <= 5 * 1024 * 1024,
            PhotoUpload.media_type.in_(("image/jpeg", "image/png", "image/webp")),
        )
        if lock:
            query = query.with_for_update()
        return cast(str | None, await session.scalar(query))

    async def create_photo_upload(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
        upload_id: UUID,
        staging_key: str,
        expires_in: int,
        now: datetime | None = None,
    ) -> None:
        await session.execute(
            insert(PhotoUpload).values(
                id=upload_id,
                account_id=account_id,
                staging_key=staging_key,
                expires_at=(now or datetime.now(UTC)) + timedelta(seconds=expires_in),
                state="pending",
            )
        )

    async def complete_photo_upload(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
        upload_id: UUID,
        clean_key: str,
        media_type: str,
        byte_count: int,
    ) -> bool:
        result = await session.execute(
            update(PhotoUpload)
            .where(
                PhotoUpload.id == upload_id,
                PhotoUpload.account_id == account_id,
                PhotoUpload.state == "pending",
            )
            .values(
                clean_key=clean_key,
                state="cleaned",
                media_type=media_type,
                byte_count=byte_count,
            )
        )
        return cast(CursorResult[Any], result).rowcount == 1

    async def get_completed_photo(
        self, session: AsyncSession, *, account_id: UUID, upload_id: UUID
    ) -> tuple[str, str, int] | None:
        """Return completed metadata so a retried promotion is idempotent."""

        result = await session.execute(
            select(PhotoUpload.clean_key, PhotoUpload.media_type, PhotoUpload.byte_count).where(
                PhotoUpload.id == upload_id,
                PhotoUpload.account_id == account_id,
                PhotoUpload.state == "cleaned",
            )
        )
        row = result.one_or_none()
        if row is None or row.clean_key is None or row.media_type is None or row.byte_count is None:
            return None
        return row.clean_key, row.media_type, row.byte_count

    async def save(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
        expected_version: int,
        display_name: str | None,
        bio: str | None,
        photo_key: str | None,
        links: list[str],
        visibility: str,
        published_at: datetime | None,
    ) -> tuple[Profile, list[str]]:
        """Persist one complete profile edit with optimistic version protection."""

        result = await session.execute(
            update(Profile)
            .where(Profile.account_id == account_id, Profile.version == expected_version)
            .values(
                display_name=display_name,
                bio=bio,
                photo_key=photo_key,
                visibility=visibility,
                published_at=published_at,
                version=expected_version + 1,
            )
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            from app.modules.users.policies import ProfileConflictError

            raise ProfileConflictError("profile changed; reload and retry")
        await session.execute(delete(ProfileLink).where(ProfileLink.account_id == account_id))
        session.add_all(
            [
                ProfileLink(id=uuid7(), account_id=account_id, url=url, position=position)
                for position, url in enumerate(links)
            ]
        )
        await session.flush()
        loaded = await self.get(session, account_id)
        if loaded is None:
            raise RuntimeError("profile disappeared during save")
        return loaded
