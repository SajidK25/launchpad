"""Real PostgreSQL checks for atomic member registration and verification."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest
from app.modules.auth.models import Account, EmailVerification
from app.modules.auth.service import RegistrationService
from app.modules.users.models import Profile
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.models import OutboxMessage
from conftest import IntegrationSettings
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker


def _service(codec: EmailPayloadCodec, *, now: datetime | None = None) -> RegistrationService:
    return RegistrationService(
        payload_codec=codec,
        mail_web_origin="https://launchpad.example",
        clock=lambda: now or datetime.now(UTC),
    )


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
