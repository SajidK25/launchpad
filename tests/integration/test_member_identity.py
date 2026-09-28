"""Real PostgreSQL checks for atomic member registration and verification."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest
from app.main import create_app
from app.modules.auth.models import Account, EmailVerification, PasswordReset, Session
from app.modules.auth.service import PasswordResetService, RegistrationService
from app.modules.auth.sessions import AuthenticationError, SessionService, UnauthenticatedError
from app.modules.users.models import Profile
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.models import OutboxMessage
from app.shared.security.passwords import verify_password
from conftest import IntegrationSettings
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker


def _service(codec: EmailPayloadCodec, *, now: datetime | None = None) -> RegistrationService:
    return RegistrationService(
        payload_codec=codec,
        mail_web_origin="https://launchpad.example",
        clock=lambda: now or datetime.now(UTC),
    )


@pytest.mark.parametrize(
    "origin_value",
    ["http://web:8080", "http://localhost:8080", "http://127.0.0.1:8080"],
)
def test_auth_http_login_session_and_logout_use_one_transaction(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
    origin_value: str,
) -> None:
    prepared = asyncio.run(_database(integration_settings_fixture))
    asyncio.run(prepared.close())
    with TestClient(create_app()) as client:
        origin = {"Origin": origin_value}
        email_tag = origin_value.split("//", 1)[1].replace(".", "-").replace(":", "-")
        payload = {
            "email": f"http-member-{email_tag}@example.com",
            "password": "a secure password!",
        }

        registration = client.post("/api/v1/auth/register", json=payload, headers=origin)
        assert registration.status_code == 202

        login = client.post("/api/v1/auth/login", json=payload, headers=origin)
        assert login.status_code == 200
        session_cookie = login.cookies.get("__Host-launchpad_session")
        assert session_cookie is not None
        csrf_token = login.json()["csrf_token"]

        current = client.get(
            "/api/v1/auth/session",
            cookies={"__Host-launchpad_session": session_cookie},
        )
        assert current.status_code == 200
        assert current.headers["cache-control"] == "no-store"

        if origin_value == "http://localhost:8080":
            verification_request = client.post(
                "/api/v1/auth/verification-requests",
                headers={**origin, "X-CSRF-Token": csrf_token},
                cookies={"__Host-launchpad_session": session_cookie},
            )
            assert verification_request.status_code == 202

            recovery_request = client.post(
                "/api/v1/auth/password-reset-requests",
                json={"email": payload["email"]},
                headers=origin,
            )
            assert recovery_request.status_code == 202

        profile_update = client.patch(
            "/api/v1/me/profile",
            json={"version": 0, "bio": "Private member bio"},
            headers={**origin, "X-CSRF-Token": csrf_token},
            cookies={"__Host-launchpad_session": session_cookie},
        )
        assert profile_update.status_code == 200
        assert profile_update.json()["bio"] == "Private member bio"

        logout = client.post(
            "/api/v1/auth/logout",
            headers={**origin, "X-CSRF-Token": csrf_token},
            cookies={"__Host-launchpad_session": session_cookie},
        )
        assert logout.status_code == 204


def test_rejected_http_identity_actions_leave_database_state_unchanged(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    prepared = asyncio.run(_database(integration_settings_fixture))
    asyncio.run(prepared.close())
    rejected = {"Origin": "http://evil.example:8080"}
    payload = {"email": "rejected-state@example.com", "password": "a secure password!"}

    with TestClient(create_app()) as client:
        registration = client.post(
            "/api/v1/auth/register",
            json=payload,
            headers=rejected,
        )
        assert registration.status_code == 403
        assert registration.json() == {"detail": "request rejected"}

        async def empty_counts() -> tuple[int, int, int, int, int]:
            database = await _database(integration_settings_fixture)
            try:
                sessions = async_sessionmaker(database.engine, expire_on_commit=False)
                async with sessions() as session:
                    return (
                        await session.scalar(select(func.count(Account.id))) or 0,
                        await session.scalar(select(func.count(Session.id))) or 0,
                        await session.scalar(select(func.count(EmailVerification.id))) or 0,
                        await session.scalar(select(func.count(Profile.account_id))) or 0,
                        await session.scalar(select(func.count(OutboxMessage.id))) or 0,
                    )
            finally:
                await database.close()

        assert asyncio.run(empty_counts()) == (0, 0, 0, 0, 0)

        async def create_member() -> None:
            database = await _database(integration_settings_fixture)
            try:
                sessions = async_sessionmaker(database.engine, expire_on_commit=False)
                codec = EmailPayloadCodec({"v1": b"q" * 32}, "v1")
                async with sessions.begin() as session:
                    await _service(codec).register(
                        session, email=payload["email"], password=payload["password"]
                    )
            finally:
                await database.close()

        asyncio.run(create_member())

        before = asyncio.run(_identity_state(integration_settings_fixture))

        recovery = client.post(
            "/api/v1/auth/password-reset-requests",
            json={"email": payload["email"]},
            headers=rejected,
        )
        assert recovery.status_code == 403
        assert recovery.json() == {"detail": "request rejected"}

        profile = client.patch(
            "/api/v1/me/profile",
            json={"version": 0, "bio": "must not persist"},
            headers=rejected,
        )
        assert profile.status_code == 403
        assert profile.json() == {"detail": "request rejected"}
        assert asyncio.run(_identity_state(integration_settings_fixture)) == before


async def _identity_state(settings: IntegrationSettings) -> tuple[int, int, int, str | None, int]:
    database = await _database(settings)
    try:
        sessions = async_sessionmaker(database.engine, expire_on_commit=False)
        async with sessions() as session:
            profile = await session.scalar(select(Profile))
            return (
                await session.scalar(select(func.count(Account.id))) or 0,
                await session.scalar(select(func.count(Session.id))) or 0,
                await session.scalar(select(func.count(PasswordReset.id))) or 0,
                profile.bio if profile is not None else None,
                await session.scalar(select(func.count(OutboxMessage.id))) or 0,
            )
    finally:
        await database.close()


async def _database(settings: IntegrationSettings) -> Database:
    database = Database.connect(settings.database_url)
    await database.prepare()
    return database


def test_registration_creates_atomic_private_unverified_member(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    async def verify() -> None:
        database = await _database(integration_settings_fixture)
        codec = EmailPayloadCodec({"v1": b"f" * 32}, "v1")
        try:
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions.begin() as session:
                result = await _service(codec).register(
                    session, email="Member@Example.com", password="a secure password!"
                )
                assert result.accepted
            async with sessions() as session:
                account = await session.scalar(select(Account))
                profile = await session.scalar(select(Profile))
                challenge = await session.scalar(select(EmailVerification))
                event = await session.scalar(select(OutboxMessage))
                assert account is not None and account.verified_at is None
                assert account.email_key == "member@example.com"
                assert profile is not None and profile.visibility == "private"
                assert challenge is not None
                assert event is not None and event.encrypted_payload is not None
                payload = codec.decode(event.key_id, event.encrypted_payload)
                assert "raw" not in payload["body"]
                assert payload["recipient"] == "Member@Example.com"
        finally:
            await database.close()

    asyncio.run(verify())


def test_duplicate_registration_is_generic_and_does_not_change_account(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    async def verify() -> None:
        database = await _database(integration_settings_fixture)
        codec = EmailPayloadCodec({"v1": b"g" * 32}, "v1")
        try:
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions.begin() as session:
                await _service(codec).register(
                    session, email="member@example.com", password="a secure password!"
                )
            async with sessions() as session:
                before = await session.scalar(select(Account))
                assert before is not None
                before_hash = before.password_hash
            async with sessions.begin() as session:
                result = await _service(codec).register(
                    session, email="MEMBER@example.com", password="different password!"
                )
                assert result.accepted
            async with sessions() as session:
                assert await session.scalar(select(func.count(Account.id))) == 1
                after = await session.scalar(select(Account))
                assert after is not None and after.password_hash == before_hash
                assert await session.scalar(select(func.count(Profile.account_id))) == 1
                assert await session.scalar(select(func.count(OutboxMessage.id))) == 1
        finally:
            await database.close()

    asyncio.run(verify())


def test_malformed_registration_does_not_create_account(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    async def verify() -> None:
        database = await _database(integration_settings_fixture)
        codec = EmailPayloadCodec({"v1": b"j" * 32}, "v1")
        try:
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            with pytest.raises(ValueError):
                async with sessions.begin() as session:
                    await _service(codec).register(
                        session, email="not-an-email", password="a secure password!"
                    )
            with pytest.raises(ValueError):
                async with sessions.begin() as session:
                    await _service(codec).register(
                        session, email="member@example.com", password="short"
                    )
            async with sessions() as session:
                assert await session.scalar(select(func.count(Account.id))) == 0
        finally:
            await database.close()

    asyncio.run(verify())


def test_concurrent_equivalent_registration_creates_one_member(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    async def verify() -> None:
        database = await _database(integration_settings_fixture)
        codec = EmailPayloadCodec({"v1": b"h" * 32}, "v1")
        try:
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)

            async def register(address: str) -> None:
                async with sessions.begin() as session:
                    await _service(codec).register(
                        session, email=address, password="a secure password!"
                    )

            await asyncio.gather(register("member@example.com"), register("MEMBER@example.com"))
            async with sessions() as session:
                assert await session.scalar(select(func.count(Account.id))) == 1
                assert await session.scalar(select(func.count(Profile.account_id))) == 1
                assert await session.scalar(select(func.count(EmailVerification.id))) == 1
                assert await session.scalar(select(func.count(OutboxMessage.id))) == 1
        finally:
            await database.close()

    asyncio.run(verify())


def test_verification_is_one_use_and_resend_supersedes_previous_link(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    async def verify() -> None:
        database = await _database(integration_settings_fixture)
        codec = EmailPayloadCodec({"v1": b"i" * 32}, "v1")
        try:
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            service = _service(codec)
            async with sessions.begin() as session:
                await service.register(
                    session, email="member@example.com", password="a secure password!"
                )
            async with sessions() as session:
                first_event = await session.scalar(select(OutboxMessage))
                account = await session.scalar(select(Account))
                assert first_event is not None and account is not None
                first_payload = codec.decode(
                    first_event.key_id, first_event.encrypted_payload or b""
                )
                first_token = parse_qs(urlparse(str(first_payload["body"])).query)["token"][0]
                account_id = account.id
            async with sessions.begin() as session:
                await service.resend_verification(session, account_id=account_id)
            async with sessions() as session:
                events = list(
                    (await session.scalars(select(OutboxMessage).order_by(OutboxMessage.id))).all()
                )
                assert len(events) == 2
                latest_payload = codec.decode(
                    events[-1].key_id, events[-1].encrypted_payload or b""
                )
                latest_token = parse_qs(urlparse(str(latest_payload["body"])).query)["token"][0]
            async with sessions.begin() as session:
                assert (await service.verify(session, token=first_token)).verified is False
                assert (
                    await service.verify(session, token=f"{latest_token}tampered")
                ).verified is False
            async with sessions.begin() as session:
                assert (await service.verify(session, token=latest_token)).verified is True
            async with sessions.begin() as session:
                assert (await service.verify(session, token=latest_token)).verified is False
            async with sessions() as session:
                account = await session.get(Account, account_id)
                assert account is not None and account.verified_at is not None
        finally:
            await database.close()

    asyncio.run(verify())


def test_password_reset_changes_hash_and_ends_all_sessions(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    async def verify() -> None:
        database = await _database(integration_settings_fixture)
        codec = EmailPayloadCodec({"v1": b"r" * 32}, "v1")
        try:
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            registration = _service(codec)
            recovery = PasswordResetService(
                payload_codec=codec,
                mail_web_origin="https://launchpad.example",
                clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
            )
            async with sessions.begin() as session:
                await registration.register(
                    session, email="member@example.com", password="old password!"
                )
            async with sessions.begin() as session:
                await recovery.request(session, email="member@example.com")
            async with sessions() as session:
                first_reset_event = await session.scalar(
                    select(OutboxMessage).order_by(OutboxMessage.id.desc())
                )
                assert first_reset_event is not None
                first_reset_payload = codec.decode(
                    first_reset_event.key_id, first_reset_event.encrypted_payload or b""
                )
                assert urlparse(str(first_reset_payload["body"])).path == "/reset"
                first_reset_token = parse_qs(urlparse(str(first_reset_payload["body"])).query)[
                    "token"
                ][0]
            async with sessions.begin() as session:
                await recovery.request(session, email="MEMBER@example.com")
            async with sessions() as session:
                account = await session.scalar(select(Account))
                events = list(
                    (await session.scalars(select(OutboxMessage).order_by(OutboxMessage.id))).all()
                )
                assert account is not None and len(events) == 3
                payload = codec.decode(events[-1].key_id, events[-1].encrypted_payload or b"")
                assert urlparse(str(payload["body"])).path == "/reset"
                reset_token = parse_qs(urlparse(str(payload["body"])).query)["token"][0]
                account_id = account.id
            async with sessions.begin() as session:
                first = await SessionService(
                    clock=lambda: datetime(2026, 1, 1, tzinfo=UTC)
                ).sign_in(session, email="member@example.com", password="old password!")
            async with sessions.begin() as session:
                second = await SessionService(
                    clock=lambda: datetime(2026, 1, 1, tzinfo=UTC)
                ).sign_in(session, email="member@example.com", password="old password!")
            async with sessions.begin() as session:
                stale = await recovery.reset(
                    session, token=first_reset_token, new_password="new password!"
                )
                assert stale.reset is False
            async with sessions.begin() as session:
                result = await recovery.reset(
                    session, token=reset_token, new_password="new password!"
                )
                assert result.reset
            async with sessions.begin() as session:
                assert (
                    await recovery.reset(session, token=reset_token, new_password="third password!")
                ).reset is False
            async with sessions() as session:
                account = await session.get(Account, account_id)
                assert account is not None and account.verified_at is None
                assert verify_password("new password!", account.password_hash)
                assert (
                    await session.scalar(
                        select(Session.revoked_at).where(Session.account_id == account_id)
                    )
                    is not None
                )
            async with sessions.begin() as session:
                with pytest.raises(UnauthenticatedError):
                    await SessionService(clock=lambda: datetime(2026, 1, 1, tzinfo=UTC)).resolve(
                        session, session_secret=first.session_secret
                    )
                with pytest.raises(UnauthenticatedError):
                    await SessionService(clock=lambda: datetime(2026, 1, 1, tzinfo=UTC)).resolve(
                        session, session_secret=second.session_secret
                    )
        finally:
            await database.close()

    asyncio.run(verify())


def test_password_reset_notice_failure_rolls_back_account_and_challenge(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    async def verify() -> None:
        database = await _database(integration_settings_fixture)
        codec = EmailPayloadCodec({"v1": b"s" * 32}, "v1")

        class FailingOutbox:
            async def add(self, session: object, event: object) -> None:
                raise RuntimeError("notice unavailable")

        try:
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            recovery = PasswordResetService(
                payload_codec=codec,
                outbox_repository=FailingOutbox(),  # type: ignore[arg-type]
                mail_web_origin="https://launchpad.example",
                clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
            )
            async with sessions.begin() as session:
                await _service(codec).register(
                    session, email="member@example.com", password="old password!"
                )
            async with sessions.begin() as session:
                await PasswordResetService(
                    payload_codec=codec,
                    mail_web_origin="https://launchpad.example",
                    clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
                ).request(session, email="member@example.com")
            async with sessions() as session:
                event = await session.scalar(
                    select(OutboxMessage).order_by(OutboxMessage.id.desc())
                )
                assert event is not None
                payload = codec.decode(event.key_id, event.encrypted_payload or b"")
                token = parse_qs(urlparse(str(payload["body"])).query)["token"][0]
            with pytest.raises(RuntimeError):
                async with sessions.begin() as session:
                    await recovery.reset(session, token=token, new_password="new password!")
            async with sessions() as session:
                account = await session.scalar(select(Account))
                challenge = await session.scalar(select(PasswordReset))
                assert account is not None and challenge is not None
                assert verify_password("old password!", account.password_hash)
                assert account.session_epoch == 0
                assert challenge.consumed_at is None
        finally:
            await database.close()

    asyncio.run(verify())


def test_password_reset_racing_old_password_login_leaves_no_usable_session(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    async def verify() -> None:
        database = await _database(integration_settings_fixture)
        codec = EmailPayloadCodec({"v1": b"t" * 32}, "v1")
        recovery = PasswordResetService(
            payload_codec=codec,
            mail_web_origin="https://launchpad.example",
            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        )
        try:
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions.begin() as session:
                await _service(codec).register(
                    session, email="member@example.com", password="old password!"
                )
            async with sessions.begin() as session:
                await recovery.request(session, email="member@example.com")
            async with sessions() as session:
                event = await session.scalar(
                    select(OutboxMessage).order_by(OutboxMessage.id.desc())
                )
                assert event is not None
                payload = codec.decode(event.key_id, event.encrypted_payload or b"")
                token = parse_qs(urlparse(str(payload["body"])).query)["token"][0]

            async def reset() -> None:
                async with sessions.begin() as session:
                    await recovery.reset(session, token=token, new_password="new password!")

            async def old_login() -> str | None:
                try:
                    async with sessions.begin() as session:
                        result = await SessionService(
                            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC)
                        ).sign_in(session, email="member@example.com", password="old password!")
                        return result.session_secret
                except AuthenticationError:
                    return None

            _, old_secret = await asyncio.gather(reset(), old_login())
            if old_secret is not None:
                async with sessions.begin() as session:
                    with pytest.raises(UnauthenticatedError):
                        await SessionService(
                            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC)
                        ).resolve(session, session_secret=old_secret)
        finally:
            await database.close()

    asyncio.run(verify())
