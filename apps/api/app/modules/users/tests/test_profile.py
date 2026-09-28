from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from app.modules.users.service import (
    MemberIdentity,
    ProfileConflictError,
    ProfileForbiddenError,
    ProfileInfrastructureError,
    ProfileService,
    ProfileValidationError,
)


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
