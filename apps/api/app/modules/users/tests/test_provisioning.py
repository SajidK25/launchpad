"""Tests for safe publication of synthetic demo profiles and photos."""

from __future__ import annotations

import asyncio
import io
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from PIL import Image, UnidentifiedImageError
from uuid6 import uuid7

from app.modules.users.service import (
    MemberIdentity,
    ProfileForbiddenError,
    ProfileService,
    ProfileValidationError,
)
from app.shared.storage.objects import CleanPhoto, ObjectValidationError


class FakeSession:
    """Minimal session surface used by the profile service."""

    async def flush(self) -> None:
        return None


class FakeMemberAccess:
    def __init__(self, account_id: UUID, verified: bool = True) -> None:
        self.account_id = account_id
        self.verified = verified

    async def get_member(
        self, session: Any, account_id: UUID, *, lock: bool = False
    ) -> MemberIdentity | None:
        if account_id != self.account_id:
            return None
        return MemberIdentity(account_id, "demo@example.com", self.verified)


class FakeProfileRepository:
    def __init__(self, account_id: UUID) -> None:
        self.account_id = account_id
        self.profile: SimpleNamespace | None = None
        self.links: list[str] = []
        self.uploads: dict[UUID, dict[str, Any]] = {}
        self.validated_photos: dict[str, UUID] = {}
        self.profile_creations = 0

    async def get(
        self, session: Any, account_id: UUID, *, lock: bool = False
    ) -> tuple[SimpleNamespace, list[str]] | None:
        if account_id != self.account_id or self.profile is None:
            return None
        return self.profile, list(self.links)

    async def create_private(self, session: Any, account_id: UUID) -> SimpleNamespace:
        self.profile_creations += 1
        self.profile = SimpleNamespace(
            account_id=account_id,
            display_name=None,
            bio=None,
            photo_key=None,
            visibility="private",
            published_at=None,
            version=0,
        )
        return self.profile

    async def save(
        self,
        session: Any,
        *,
        account_id: UUID,
        expected_version: int,
        **values: object,
    ) -> tuple[SimpleNamespace, list[str]]:
        assert self.profile is not None
        assert self.profile.version == expected_version
        for key, value in values.items():
            if key == "links":
                self.links = list(cast(list[str], value))
            else:
                setattr(self.profile, key, value)
        self.profile.version += 1
        return self.profile, list(self.links)

    async def has_validated_photo(
        self, session: Any, account_id: UUID, photo_key: str, *, lock: bool = False
    ) -> bool:
        return self.validated_photos.get(photo_key) == account_id

    async def get_validated_photo_key(
        self, session: Any, account_id: UUID, upload_id: UUID, *, lock: bool = False
    ) -> str | None:
        upload = self.uploads.get(upload_id)
        if upload is None or upload["account_id"] != account_id or upload["state"] != "cleaned":
            return None
        return str(upload["clean_key"])

    async def get_completed_photo(
        self, session: Any, *, account_id: UUID, upload_id: UUID
    ) -> tuple[str, str, int] | None:
        upload = self.uploads.get(upload_id)
        if upload is None or upload["account_id"] != account_id or upload["state"] != "cleaned":
            return None
        return str(upload["clean_key"]), "image/png", int(upload["byte_count"])

    async def get_photo_upload_for_transfer(
        self, session: Any, *, account_id: UUID, upload_id: UUID, lock: bool = False
    ) -> SimpleNamespace | None:
        upload = self.uploads.get(upload_id)
        if upload is None or upload["account_id"] != account_id:
            return None
        return SimpleNamespace(**upload)

    async def create_photo_upload(
        self,
        session: Any,
        *,
        account_id: UUID,
        upload_id: UUID,
        staging_key: str,
        declared_byte_count: int,
        declared_media_type: str,
        expires_in: int,
        now: datetime,
    ) -> None:
        self.uploads[upload_id] = {
            "id": upload_id,
            "account_id": account_id,
            "staging_key": staging_key,
            "declared_byte_count": declared_byte_count,
            "declared_media_type": declared_media_type,
            "expires_at": now,
            "state": "pending",
        }

    async def complete_photo_upload(
        self,
        session: Any,
        *,
        account_id: UUID,
        upload_id: UUID,
        clean_key: str,
        media_type: str,
        byte_count: int,
    ) -> bool:
        upload = self.uploads[upload_id]
        if upload["account_id"] != account_id or upload["state"] != "pending":
            return False
        upload.update(
            state="cleaned", clean_key=clean_key, media_type=media_type, byte_count=byte_count
        )
        self.validated_photos[clean_key] = account_id
        return True


class FakePrivateStorage:
    """Exercise the users service's stage/finalize path with private in-memory bytes."""

    def __init__(self) -> None:
        self.staging: dict[str, tuple[bytes, str]] = {}
        self.create_calls = 0
        self.finalize_calls = 0

    async def create_staging_upload(
        self, *, account_id: UUID, upload_id: UUID, content_type: str, size: int
    ) -> SimpleNamespace:
        self.create_calls += 1
        return SimpleNamespace(object_key=f"profile-staging/{account_id.hex}/{upload_id.hex}")

    async def put_staging(self, *, object_key: str, body: bytes, content_type: str) -> None:
        self.staging[object_key] = (body, content_type)

    async def finalize_staging(
        self,
        *,
        account_id: UUID,
        upload_id: UUID,
        declared_content_type: str,
    ) -> CleanPhoto:
        self.finalize_calls += 1
        staging_key = f"profile-staging/{account_id.hex}/{upload_id.hex}"
        body, content_type = self.staging[staging_key]
        if content_type != declared_content_type:
            raise ObjectValidationError("unsupported image type")
        try:
            with Image.open(io.BytesIO(body)) as image:
                image.verify()
        except (UnidentifiedImageError, OSError) as error:
            raise ObjectValidationError("invalid image") from error
        return CleanPhoto(
            object_key=f"profile-clean/{account_id.hex}/{upload_id.hex}",
            media_type=content_type,
            byte_count=len(body),
        )


class FakeOutbox:
    async def add(self, session: Any, event: Any) -> None:
        return None


class FakeCodec:
    def encode(self, payload: dict[str, str]) -> tuple[str, bytes]:
        return "test-key", b"encrypted"


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color=(40, 120, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


def _service(
    account_id: UUID, repository: FakeProfileRepository, *, verified: bool = True
) -> ProfileService:
    return ProfileService(
        repository=repository,
        member_access=FakeMemberAccess(account_id, verified=verified),
        outbox_repository=FakeOutbox(),
        payload_codec=FakeCodec(),
        mail_web_origin="https://launchpad.example",
        clock=lambda: datetime(2026, 10, 26, tzinfo=UTC),
    )


def test_publishes_complete_profile_with_validated_private_photo() -> None:
    async def verify() -> None:
        account_id = uuid7()
        repository = FakeProfileRepository(account_id)
        storage = FakePrivateStorage()
        service = _service(account_id, repository)
        result = await service.provision_demo_profile(
            FakeSession(),
            actor_id=account_id,
            seed_key="founder-01",
            display_name="Mira Chen",
            bio="Building simple data tools for small teams.",
            links=["https://mira.example.com"],
            photo_bytes=_png_bytes(),
            content_type="image/png",
            storage=storage,
        )
        assert result.profile.visibility == "public"
        assert result.profile.display_name == "Mira Chen"
        assert result.profile.photo_key is not None
        assert result.profile.photo_key.startswith(f"profile-clean/{account_id.hex}/")
        assert result.links == ["https://mira.example.com"]
        assert repository.validated_photos[result.profile.photo_key] == account_id
        assert storage.create_calls == storage.finalize_calls == 1

    asyncio.run(verify())


@pytest.mark.parametrize(
    ("photo_bytes", "content_type"),
    [
        (b"not an image", "image/png"),
        (_png_bytes() + (b"x" * (5 * 1024 * 1024)), "image/png"),
        (_png_bytes(), "image/gif"),
    ],
    ids=["malformed", "oversized", "unsupported"],
)
def test_rejects_invalid_or_unsupported_photo_without_publication(
    photo_bytes: bytes, content_type: str
) -> None:
    async def verify() -> None:
        account_id = uuid7()
        repository = FakeProfileRepository(account_id)
        service = _service(account_id, repository)
        with pytest.raises(ProfileValidationError):
            await service.provision_demo_profile(
                FakeSession(),
                actor_id=account_id,
                seed_key="founder-invalid-photo",
                display_name="Demo Founder",
                bio="A fictional founder profile.",
                links=["https://demo.example.com"],
                photo_bytes=photo_bytes,
                content_type=content_type,
                storage=FakePrivateStorage(),
            )
        assert repository.profile is None or repository.profile.visibility == "private"

    asyncio.run(verify())


def test_rerun_reuses_owned_profile_photo_without_duplicate_upload() -> None:
    async def verify() -> None:
        account_id = uuid7()
        repository = FakeProfileRepository(account_id)
        storage = FakePrivateStorage()
        service = _service(account_id, repository)
        first = await service.provision_demo_profile(
            FakeSession(),
            actor_id=account_id,
            seed_key="founder-01",
            display_name="Mira Chen",
            bio="Building simple data tools for small teams.",
            links=["https://mira.example.com"],
            photo_bytes=_png_bytes(),
            content_type="image/png",
            storage=storage,
        )
        second = await service.provision_demo_profile(
            FakeSession(),
            actor_id=account_id,
            seed_key="founder-01",
            display_name="Mira Chen",
            bio="Building simple data tools for small teams.",
            links=["https://mira.example.com"],
            photo_bytes=_png_bytes(),
            content_type="image/png",
            storage=storage,
        )
        assert second.profile.photo_key == first.profile.photo_key
        assert storage.create_calls == 1
        assert storage.finalize_calls == 1
        assert repository.profile_creations == 1
        assert len(repository.uploads) == 1

    asyncio.run(verify())


def test_cannot_publish_a_photo_owned_by_another_account() -> None:
    async def verify() -> None:
        account_a, account_b = uuid7(), uuid7()
        repository = FakeProfileRepository(account_b)
        await repository.create_private(FakeSession(), account_b)
        foreign_key = f"profile-clean/{account_a.hex}/foreign-photo"
        repository.validated_photos[foreign_key] = account_a
        assert repository.profile is not None
        repository.profile.photo_key = foreign_key
        service = _service(account_b, repository)
        with pytest.raises(ProfileValidationError, match="validated private photo"):
            await service.publish(FakeSession(), actor_id=account_b)

    asyncio.run(verify())


def test_unverified_account_cannot_provision_a_public_profile() -> None:
    async def verify() -> None:
        account_id = uuid7()
        repository = FakeProfileRepository(account_id)
        service = _service(account_id, repository, verified=False)
        with pytest.raises(ProfileForbiddenError, match="verification"):
            await service.provision_demo_profile(
                FakeSession(),
                actor_id=account_id,
                seed_key="founder-unverified",
                display_name="Demo Founder",
                bio="A fictional founder profile.",
                links=["https://demo.example.com"],
                photo_bytes=_png_bytes(),
                content_type="image/png",
                storage=FakePrivateStorage(),
            )
        assert repository.profile is None

    asyncio.run(verify())
