from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Insert

from app.modules.users.repository import ProfileRepository
from app.modules.users.service import (
    MemberIdentity,
    ProfileConflictError,
    ProfileForbiddenError,
    ProfileInfrastructureError,
    ProfileService,
    ProfileValidationError,
)
from app.shared.storage.objects import ObjectOperationError


class FakeRepository:
    def __init__(self, profile: SimpleNamespace, links: list[str] | None = None) -> None:
        self.profile = profile
        self.links = links or []
        self.saved: list[dict[str, object]] = []

    async def get(
        self, session: Any, account_id: object, *, lock: bool = False
    ) -> tuple[SimpleNamespace, list[str]] | None:
        if account_id != self.profile.account_id:
            return None
        return self.profile, list(self.links)

    async def save(
        self, session: Any, *, account_id: object, expected_version: int, **values: object
    ) -> tuple[SimpleNamespace, list[str]]:
        if expected_version != self.profile.version:
            raise ProfileConflictError("profile changed; reload and retry")
        self.saved.append(values)
        for key, value in values.items():
            if key == "links":
                self.links = list(cast(list[str], value))
            else:
                setattr(self.profile, key, value)
        self.profile.version += 1
        return self.profile, list(self.links)

    async def has_validated_photo(
        self, session: Any, account_id: object, photo_key: str, *, lock: bool = False
    ) -> bool:
        return bool(account_id == self.profile.account_id and photo_key == self.profile.photo_key)


@pytest.mark.anyio
async def test_profile_transfer_locks_and_rechecks_intent_before_staging_write() -> None:
    account_id = uuid4()
    upload_id = uuid4()
    intent = SimpleNamespace(
        id=upload_id,
        account_id=account_id,
        staging_key=f"profile-staging/{account_id.hex}/{upload_id.hex}",
        state="pending",
        expires_at=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
        declared_byte_count=32,
        declared_media_type="image/png",
    )

    class TransferRepository(FakeRepository):
        lock_requested = False

        async def get_photo_upload_for_transfer(
            self, session: Any, *, account_id: object, upload_id: object, lock: bool = False
        ) -> SimpleNamespace | None:
            self.lock_requested = lock
            if account_id == intent.account_id and upload_id == intent.id:
                return intent
            return None

    class StagingStorage:
        writes: list[dict[str, object]]

        def __init__(self) -> None:
            self.writes = []

        async def put_staging(self, **values: object) -> None:
            self.writes.append(values)

    repository = TransferRepository(_profile(account_id))
    storage = StagingStorage()
    service = ProfileService(
        repository=repository,
        member_access=FakeMemberAccess(MemberIdentity(account_id, "member@example.com", True)),
        outbox_repository=FakeOutbox(),
        payload_codec=FakeCodec(),
        mail_web_origin="https://launchpad.example",
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )

    await service.transfer_photo_upload(
        None,
        actor_id=account_id,
        upload_id=upload_id,
        body=b"bounded image bytes",
        content_type="image/png",
        storage=storage,
    )

    assert repository.lock_requested is True
    assert storage.writes == [
        {
            "object_key": intent.staging_key,
            "body": b"bounded image bytes",
            "content_type": "image/png",
        }
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("invalid_intent", ["absent", "expired", "completed", "legacy"])
async def test_profile_transfer_refuses_stale_or_undeclared_intents(invalid_intent: str) -> None:
    account_id = uuid4()
    upload_id = uuid4()
    intent: SimpleNamespace | None = SimpleNamespace(
        id=upload_id,
        account_id=account_id,
        staging_key=f"profile-staging/{account_id.hex}/{upload_id.hex}",
        state="pending",
        expires_at=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
        declared_byte_count=32,
        declared_media_type="image/png",
    )
    if invalid_intent == "absent":
        intent = None
    elif invalid_intent == "expired":
        assert intent is not None
        intent.expires_at = datetime(2025, 12, 31, 23, 59, tzinfo=UTC)
    elif invalid_intent == "completed":
        assert intent is not None
        intent.state = "cleaned"
    else:
        assert intent is not None
        intent.declared_byte_count = None
        intent.declared_media_type = None

    class TransferRepository(FakeRepository):
        async def get_photo_upload_for_transfer(
            self, session: Any, *, account_id: object, upload_id: object, lock: bool = False
        ) -> SimpleNamespace | None:
            if intent is None or account_id != intent.account_id or upload_id != intent.id:
                return None
            return intent

    class StagingStorage:
        writes = 0

        async def put_staging(self, **values: object) -> None:
            self.writes += 1

    storage = StagingStorage()
    service = ProfileService(
        repository=TransferRepository(_profile(account_id)),
        member_access=FakeMemberAccess(MemberIdentity(account_id, "member@example.com", True)),
        outbox_repository=FakeOutbox(),
        payload_codec=FakeCodec(),
        mail_web_origin="https://launchpad.example",
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )

    with pytest.raises(ProfileConflictError):
        await service.transfer_photo_upload(
            None,
            actor_id=account_id,
            upload_id=upload_id,
            body=b"bounded image bytes",
            content_type="image/png",
            storage=storage,
        )
    assert storage.writes == 0


@pytest.mark.anyio
async def test_transfer_rechecks_auth_and_preserves_pending_on_storage_failure() -> None:
    account_id = uuid4()
    upload_id = uuid4()
    intent = SimpleNamespace(
        id=upload_id,
        account_id=account_id,
        staging_key=f"profile-staging/{account_id.hex}/{upload_id.hex}",
        state="pending",
        expires_at=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
        declared_byte_count=32,
        declared_media_type="image/png",
    )

    class TransferRepository(FakeRepository):
        async def get_photo_upload_for_transfer(
            self, session: Any, *, account_id: object, upload_id: object, lock: bool = False
        ) -> SimpleNamespace | None:
            return intent if account_id == intent.account_id and upload_id == intent.id else None

    class MutableMemberAccess(FakeMemberAccess):
        async def get_member(
            self, session: Any, account_id: object, *, lock: bool = False
        ) -> MemberIdentity | None:
            return self.member if self.member.account_id == account_id else None

    class StagingStorage:
        async def put_staging(self, **values: object) -> None:
            raise ObjectOperationError("storage unavailable")

    access = MutableMemberAccess(MemberIdentity(account_id, "member@example.com", True))
    repository = TransferRepository(_profile(account_id))
    service = ProfileService(
        repository=repository,
        member_access=access,
        outbox_repository=FakeOutbox(),
        payload_codec=FakeCodec(),
        mail_web_origin="https://launchpad.example",
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )

    access.member = MemberIdentity(uuid4(), "changed@example.com", True)
    with pytest.raises(ProfileForbiddenError):
        await service.transfer_photo_upload(
            None,
            actor_id=account_id,
            upload_id=upload_id,
            body=b"bounded image bytes",
            content_type="image/png",
            storage=StagingStorage(),
        )

    access.member = MemberIdentity(account_id, "member@example.com", True)
    with pytest.raises(ProfileInfrastructureError):
        await service.transfer_photo_upload(
            None,
            actor_id=account_id,
            upload_id=upload_id,
            body=b"bounded image bytes",
            content_type="image/png",
            storage=StagingStorage(),
        )
    assert intent.state == "pending"


@pytest.mark.anyio
async def test_create_photo_upload_persists_declarations_separately() -> None:
    class CaptureSession:
        statement: Insert | None = None

        async def execute(self, statement: Insert) -> None:
            self.statement = statement

    session = CaptureSession()
    account_id = uuid4()
    upload_id = uuid4()

    await ProfileRepository().create_photo_upload(
        session,  # type: ignore[arg-type]
        account_id=account_id,
        upload_id=upload_id,
        staging_key=f"profile-staging/{account_id.hex}/{upload_id.hex}",
        declared_byte_count=2048,
        declared_media_type="image/png",
        expires_in=600,
    )

    assert session.statement is not None
    params = session.statement.compile(dialect=postgresql.dialect()).params  # type: ignore[no-untyped-call]
    assert params["declared_byte_count"] == 2048
    assert params["declared_media_type"] == "image/png"
    assert "byte_count" not in params
    assert "media_type" not in params


class FakeMemberAccess:
    def __init__(self, member: MemberIdentity) -> None:
        self.member = member

    async def get_member(
        self, session: Any, account_id: object, *, lock: bool = False
    ) -> MemberIdentity | None:
        return self.member if account_id == self.member.account_id else None


class FakeOutbox:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def add(self, session: Any, event: Any) -> None:
        self.events.append(event)


class FailingOutbox(FakeOutbox):
    async def add(self, session: Any, event: Any) -> None:
        raise RuntimeError("mail system unavailable")


class FakeCodec:
    def encode(self, payload: dict[str, object]) -> tuple[str, bytes]:
        return "test-v1", repr(payload).encode()


def _profile(account_id: object, *, visibility: str = "private") -> SimpleNamespace:
    return SimpleNamespace(
        account_id=account_id,
        display_name="Ada",
        bio="Builder",
        photo_key=f"profile-clean/{uuid4().hex}/{uuid4().hex}",
        visibility=visibility,
        published_at=datetime.now(UTC) if visibility == "public" else None,
        version=0,
    )


def _service(
    profile: SimpleNamespace,
    *,
    verified: bool = False,
    links: list[str] | None = None,
    outbox: FakeOutbox | None = None,
) -> tuple[ProfileService, FakeRepository, FakeOutbox]:
    repository = FakeRepository(profile, links)
    events = outbox or FakeOutbox()
    service = ProfileService(
        repository=repository,
        member_access=FakeMemberAccess(
            MemberIdentity(profile.account_id, "member@example.com", verified)
        ),
        outbox_repository=events,
        payload_codec=FakeCodec(),
        mail_web_origin="https://launchpad.example",
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )
    return service, repository, events


@pytest.mark.anyio
async def test_owner_can_edit_private_draft_before_verification() -> None:
    account_id = uuid4()
    service, repository, _ = _service(_profile(account_id))

    result = await service.update_profile(
        None,
        actor_id=account_id,
        display_name="New name",
        bio="Draft bio",
        photo_key=repository.profile.photo_key,
        links=["https://example.com/me"],
    )

    assert result.profile.display_name == "New name"
    assert result.profile.visibility == "private"
    assert repository.links == ["https://example.com/me"]


@pytest.mark.anyio
async def test_outsider_cannot_edit_or_view_private_profile() -> None:
    owner = uuid4()
    outsider = uuid4()
    service, _, _ = _service(_profile(owner))

    with pytest.raises(ProfileForbiddenError):
        await service.update_profile(None, actor_id=outsider, display_name="Nope")
    assert await service.get_public(None, account_id=owner) is None


@pytest.mark.anyio
async def test_publish_requires_verified_complete_profile() -> None:
    account_id = uuid4()
    service, _, _ = _service(_profile(account_id), links=["https://example.com"])

    with pytest.raises(ProfileForbiddenError):
        await service.publish(None, actor_id=account_id)

    verified_service, repository, _ = _service(
        _profile(account_id), verified=True, links=["https://example.com"]
    )
    result = await verified_service.publish(None, actor_id=account_id)
    assert result.profile.visibility == "public"
    assert repository.profile.published_at is not None


@pytest.mark.anyio
@pytest.mark.parametrize(
    "changes",
    [
        {"bio": "line one\nline two"},
        {"bio": "x" * 161},
        {"links": ["http://example.com"]},
        {"photo_key": "profile-staging/not-clean"},
    ],
)
async def test_invalid_profile_fields_are_rejected(changes: dict[str, object]) -> None:
    account_id = uuid4()
    service, _, _ = _service(_profile(account_id))
    with pytest.raises(ProfileValidationError):
        await service.update_profile(None, actor_id=account_id, **cast(Any, changes))


@pytest.mark.anyio
async def test_malformed_url_and_forged_photo_are_rejected() -> None:
    account_id = uuid4()
    service, _, _ = _service(_profile(account_id))
    with pytest.raises(ProfileValidationError):
        await service.update_profile(
            None,
            actor_id=account_id,
            links=["https://[not-a-host"],
        )
    with pytest.raises(ProfileValidationError):
        await service.update_profile(
            None,
            actor_id=account_id,
            photo_key=f"profile-clean/{uuid4().hex}/{uuid4().hex}",
        )


@pytest.mark.anyio
async def test_removing_required_field_makes_public_profile_private_and_emits_one_notice() -> None:
    account_id = uuid4()
    profile = _profile(account_id, visibility="public")
    service, repository, events = _service(profile, verified=True, links=["https://example.com"])

    result = await service.update_profile(None, actor_id=account_id, bio="")

    assert result.profile.visibility == "private"
    assert result.became_private is True
    assert repository.profile.bio == ""
    assert len(events.events) == 1
    assert events.events[0].event_type == "users.profile_became_private.v1"

    already_private = await service.update_profile(
        None, actor_id=account_id, display_name="Still private"
    )
    assert already_private.became_private is False
    assert len(events.events) == 1


@pytest.mark.anyio
async def test_expected_version_and_outbox_failures_are_typed() -> None:
    account_id = uuid4()
    service, repository, _ = _service(_profile(account_id))
    with pytest.raises(ProfileConflictError):
        await service.update_profile(None, actor_id=account_id, expected_version=99, bio="stale")

    failing = FailingOutbox()
    profile = _profile(account_id, visibility="public")
    service, repository, _ = _service(
        profile,
        verified=True,
        links=["https://example.com"],
        outbox=failing,
    )
    with pytest.raises(ProfileInfrastructureError):
        await service.update_profile(None, actor_id=account_id, bio="")
    assert repository.profile.visibility == "private"


@pytest.mark.anyio
async def test_manual_unpublish_then_republish_rechecks_requirements() -> None:
    account_id = uuid4()
    service, repository, events = _service(
        _profile(account_id, visibility="public"),
        verified=True,
        links=["https://example.com"],
    )

    await service.unpublish(None, actor_id=account_id)
    assert repository.profile.visibility == "private"
    assert not events.events
    repository.profile.bio = ""
    with pytest.raises(ProfileValidationError):
        await service.publish(None, actor_id=account_id)
