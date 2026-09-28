"""Integration checks for private profile-photo staging and promotion."""

from __future__ import annotations

import asyncio
import io
from datetime import UTC, datetime
from uuid import UUID, uuid4

import boto3
import pytest
from app.modules.auth.repository import AuthRepository
from app.modules.users.models import PhotoUpload, Profile
from app.modules.users.service import MemberIdentity, ProfileService
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.models import OutboxMessage
from app.shared.events.outbox import OutboxRepository
from app.shared.storage.objects import PrivateObjectStore
from app.shared.storage.provision import StorageProvisioner
from botocore import UNSIGNED
from botocore.client import BaseClient, Config
from botocore.exceptions import ClientError
from conftest import StorageCredentials
from PIL import Image
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker


def _provisioner(credentials: StorageCredentials) -> StorageProvisioner:
    return StorageProvisioner(
        endpoint_url=credentials.endpoint_url,
        bootstrap_access_key_id=credentials.bootstrap_access_key_id,
        bootstrap_secret_access_key=credentials.bootstrap_secret_access_key,
        runtime_access_key_id=credentials.runtime_access_key_id,
        runtime_secret_access_key=credentials.runtime_secret_access_key,
    )


def _png() -> bytes:
    image = Image.new("RGB", (3, 3), (1, 2, 3))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _runtime(credentials: StorageCredentials) -> BaseClient:
    return boto3.client(
        "s3",
        endpoint_url=credentials.endpoint_url,
        aws_access_key_id=credentials.runtime_access_key_id,
        aws_secret_access_key=credentials.runtime_secret_access_key,
        region_name="us-east-1",
    )


def test_valid_staging_is_cleaned_and_final_object_stays_private(
    storage_credentials: StorageCredentials,
    storage_bucket: str,
    s3_client: BaseClient,
) -> None:
    async def verify() -> None:
        await _provisioner(storage_credentials).prepare(storage_bucket)
        account_id = uuid4()
        upload_id = uuid4()
        store = PrivateObjectStore(
            endpoint_url=storage_credentials.endpoint_url,
            bucket_name=storage_bucket,
            access_key_id=storage_credentials.runtime_access_key_id,
            secret_access_key=storage_credentials.runtime_secret_access_key,
        )
        upload = await store.create_staging_upload(
            account_id=account_id,
            upload_id=upload_id,
            content_type="image/png",
            size=len(_png()),
        )
        s3_client.put_object(
            Bucket=storage_bucket,
            Key=upload.object_key,
            Body=_png(),
            ContentType="image/png",
        )
        clean = await store.finalize_staging(
            account_id=account_id,
            upload_id=upload_id,
            declared_content_type="image/png",
        )
        body, media_type = await store.get_private(object_key=clean.object_key)
        assert body and media_type == "image/png"
        with pytest.raises(ClientError):
            s3_client.get_object(Bucket=storage_bucket, Key=upload.object_key)

        anonymous = boto3.client(
            "s3",
            endpoint_url=storage_credentials.endpoint_url,
            config=Config(signature_version=UNSIGNED),
            region_name="us-east-1",
        )
        try:
            anonymous.get_object(Bucket=storage_bucket, Key=clean.object_key)
        except ClientError:
            pass
        else:
            raise AssertionError("final profile object must remain private")

    asyncio.run(verify())


def test_staging_cleanup_does_not_cross_account_prefix(
    storage_credentials: StorageCredentials,
    storage_bucket: str,
    s3_client: BaseClient,
) -> None:
    async def verify() -> None:
        await _provisioner(storage_credentials).prepare(storage_bucket)
        owner = uuid4()
        foreign = uuid4()
        owner_upload = uuid4()
        foreign_upload = uuid4()
        owner_store = PrivateObjectStore(
            endpoint_url=storage_credentials.endpoint_url,
            bucket_name=storage_bucket,
            access_key_id=storage_credentials.runtime_access_key_id,
            secret_access_key=storage_credentials.runtime_secret_access_key,
        )
        owner_key = f"profile-staging/{owner.hex}/{owner_upload.hex}"
        foreign_key = f"profile-staging/{foreign.hex}/{foreign_upload.hex}"
        s3_client.put_object(Bucket=storage_bucket, Key=owner_key, Body=b"owner")
        s3_client.put_object(Bucket=storage_bucket, Key=foreign_key, Body=b"foreign")

        assert (
            await owner_store.cleanup_staging(
                account_id=owner, object_keys=[owner_key, foreign_key]
            )
            == 1
        )
        assert (
            s3_client.get_object(Bucket=storage_bucket, Key=foreign_key)["Body"].read()
            == b"foreign"
        )

    asyncio.run(verify())


def test_runtime_cannot_list_private_bucket(
    storage_credentials: StorageCredentials,
    storage_bucket: str,
) -> None:
    async def verify() -> None:
        await _provisioner(storage_credentials).prepare(storage_bucket)

    asyncio.run(verify())
    with pytest.raises(ClientError):
        _runtime(storage_credentials).list_objects_v2(Bucket=storage_bucket)
    with pytest.raises(ClientError):
        _runtime(storage_credentials).list_objects_v2(Bucket=storage_bucket, Prefix="")


def test_published_profile_edit_is_private_and_notified_atomically(
    integration_settings_fixture,
    reset_database: None,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        now = datetime.now(UTC)
        upload_id = uuid4()
        photo_key: str
        codec = EmailPayloadCodec({"v1": b"p" * 32}, "v1")

        class Access:
            owner_id: UUID | None = None

            async def get_member(
                self, session: object, requested: object, *, lock: bool = False
            ) -> MemberIdentity | None:
                if self.owner_id is not None and requested == self.owner_id:
                    return MemberIdentity(self.owner_id, "member@example.com", True)
                return None

        access = Access()
        try:
            await database.prepare()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions.begin() as session:
                account = await AuthRepository().create_account(
                    session,
                    email_display="member@example.com",
                    email_key="member@example.com",
                    password_hash="hash",
                    now=now,
                )
                assert account.id is not None
                from app.modules.users.service import ProfileBootstrap

                await ProfileBootstrap().create_private_profile(session, account.id)
                owner_id = account.id
                photo_key = f"profile-clean/{owner_id.hex}/{upload_id.hex}"
                await session.execute(
                    insert(PhotoUpload).values(
                        id=upload_id,
                        account_id=owner_id,
                        staging_key=f"profile-staging/{owner_id.hex}/{upload_id.hex}",
                        clean_key=photo_key,
                        expires_at=now,
                        state="cleaned",
                        byte_count=128,
                        media_type="image/png",
                    )
                )
                access.owner_id = owner_id
            async with sessions.begin() as session:
                service = ProfileService(
                    member_access=access,
                    outbox_repository=OutboxRepository(),
                    payload_codec=codec,
                    mail_web_origin="https://launchpad.example",
                    clock=lambda: now,
                )
                await service.update_profile(
                    session,
                    actor_id=owner_id,
                    display_name="Member",
                    bio="Builder",
                    photo_key=photo_key,
                    links=["https://example.com"],
                )
                await service.publish(session, actor_id=owner_id)
            async with sessions.begin() as session:
                await service.update_profile(session, actor_id=owner_id, bio="")
            async with sessions() as session:
                profile = await session.get(Profile, owner_id)
                assert profile is not None and profile.visibility == "private"
                assert (
                    await session.scalar(
                        select(func.count(OutboxMessage.id)).where(
                            OutboxMessage.event_type == "users.profile_became_private.v1"
                        )
                    )
                    == 1
                )
        finally:
            await database.close()

    asyncio.run(verify())
