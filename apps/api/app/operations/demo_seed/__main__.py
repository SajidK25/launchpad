"""One-shot operator entry point for controlled demo-data operations."""

from __future__ import annotations

import asyncio
import base64
import sys
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.provisioning import DemoAccountConflict, DemoAccountProvisioningService
from app.modules.auth.staff import AuthAccessService
from app.modules.launches.service import LaunchBookingService
from app.modules.notifications.service import NotificationService
from app.modules.products.service import ProductService
from app.modules.users.service import MemberIdentity, ProfileService
from app.operations.demo_seed.cli import (
    DemoSeedTargetError,
    authorize_target,
    encode_credentials,
    load_fixture_media,
    parse_args,
    resolve_credentials,
)
from app.operations.demo_seed.fixtures import FOUNDER_FIXTURES
from app.operations.demo_seed.repository import DemoSeedRepository
from app.operations.demo_seed.service import DemoSeedIdentityConflict, DemoSeedService
from app.shared.config.settings import ConfigurationError, Settings, load_settings
from app.shared.db.database import Database, DatabasePreparationError
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.outbox import OutboxRepository
from app.shared.storage.client import StorageClient
from app.shared.storage.objects import PrivateObjectStore


class _ProfileMemberAccess:
    """Adapt auth-owned identity data to the users module's named port."""

    def __init__(self, auth_access: AuthAccessService) -> None:
        self.auth_access = auth_access

    async def get_member(
        self, session: AsyncSession, account_id: UUID, *, lock: bool = False
    ) -> MemberIdentity | None:
        del lock
        identity = await self.auth_access.profile_identity_data(session, account_id)
        if identity is None:
            return None
        return MemberIdentity(*identity)


def _build_services(
    settings: Settings, storage: PrivateObjectStore
) -> tuple[DemoSeedService, AuthAccessService]:
    if settings.outbox_key is None or settings.outbox_key_id is None:
        raise ConfigurationError("Outbox encryption settings are required.")
    codec = EmailPayloadCodec(
        {
            settings.outbox_key_id: base64.b64decode(
                settings.outbox_key.get_secret_value(), validate=True
            )
        },
        settings.outbox_key_id,
    )
    member_access = AuthAccessService()
    notifications = NotificationService(
        member_access=member_access,
        outbox_repository=OutboxRepository(),
        payload_codec=codec,
        send_review_email=False,
    )
    products = ProductService(
        member_access=member_access,
        outbox_repository=OutboxRepository(),
        payload_codec=codec,
        event_storage=storage,
        review_notifications=notifications,
    )
    launches = LaunchBookingService(
        member_access=member_access,
        product_access=products,
        outbox_repository=OutboxRepository(),
        payload_codec=codec,
    )
    profiles = ProfileService(
        member_access=_ProfileMemberAccess(member_access),
        outbox_repository=OutboxRepository(),
        payload_codec=codec,
        mail_web_origin=str(settings.mail_web_origin or "http://localhost:8080"),
    )
    store = DemoSeedService(
        accounts=DemoAccountProvisioningService(),
        profiles=profiles,
        products=products,
        launches=launches,
        notifications=notifications,
        storage=storage,
        product_media={},
    )
    return store, member_access


def _build_storage_probe(settings: Settings) -> StorageClient:
    """Build the readiness client with the configured provider semantics."""

    if settings.storage_access_key_id is None or settings.storage_secret_access_key is None:
        raise ConfigurationError("Private storage settings are required.")
    return StorageClient(
        endpoint_url=str(settings.storage_endpoint_url),
        access_key_id=settings.storage_access_key_id.get_secret_value(),
        secret_access_key=settings.storage_secret_access_key.get_secret_value(),
        provider=settings.storage_provider,
        region_name=settings.storage_region,
    )


async def _execute(arguments: list[str] | None = None) -> int:
    args = parse_args(arguments)
    stage = "settings and target validation"
    try:
        settings = load_settings()
        authorize_target(
            environment=settings.environment,
            target_id=args.target_id,
            confirm_no_customer_data=args.confirm_no_customer_data,
        )
        profile_media: dict[str, bytes] = {}
        product_media: dict[str, bytes] = {}
        credentials: dict[str, str] = {}
        if args.command == "seed":
            stage = "fixture and credential preflight"
            profile_media, product_media = load_fixture_media()
            payload = sys.stdin.read(32_769)
            existing_payload = payload if payload.strip() else None
            account_keys = [fixture.seed_key for fixture in FOUNDER_FIXTURES] + ["reviewer"]
            credentials, generated = resolve_credentials(account_keys, existing_payload)
            if existing_payload is not None and generated:
                raise ValueError("saved credential manifest is incomplete")

        stage = "database compatibility check"
        database = Database.connect(str(settings.database_url))
        try:
            await database.ensure_compatible()
            if settings.storage_access_key_id is None or settings.storage_secret_access_key is None:
                raise ConfigurationError("Private storage settings are required.")
            storage = PrivateObjectStore(
                endpoint_url=str(settings.storage_endpoint_url),
                public_endpoint_url=(
                    str(settings.public_upload_endpoint_url)
                    if settings.public_upload_endpoint_url is not None
                    else None
                ),
                region_name=settings.storage_region,
                bucket_name=settings.storage_bucket,
                access_key_id=settings.storage_access_key_id.get_secret_value(),
                secret_access_key=settings.storage_secret_access_key.get_secret_value(),
            )
            stage = "object storage readiness"
            await _build_storage_probe(settings).probe(settings.storage_bucket)
            service, _ = _build_services(settings, storage)
            service.product_media = product_media
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            repository = DemoSeedRepository()
            async with database.engine.connect() as lock_connection:
                stage = "seed target lock"
                await repository.acquire_session_target_lock(
                    lock_connection, target_id=args.target_id
                )
                await lock_connection.commit()
                try:
                    if args.command == "seed":
                        now = datetime.now(UTC)
                        stage = "seed identity preflight"
                        async with sessions() as session:
                            await service.preflight_seed(session, target_id=args.target_id)
                        async with sessions() as session, session.begin():
                            dataset = await repository.get_or_create_dataset(
                                session,
                                target_id=args.target_id,
                                dataset_version="2026-10-v1",
                                anchor_utc_date=now.date(),
                                now=now,
                            )
                            anchor = dataset.anchor_utc_date
                        stage = "seed dataset reconciliation"
                        if generated:
                            sys.stdout.write(encode_credentials(credentials))
                            sys.stdout.flush()
                        stage = "account and profile provisioning"
                        account_ids = await service.seed_accounts_and_profiles(
                            sessions,
                            target_id=args.target_id,
                            passwords=credentials,
                            profile_media=profile_media,
                        )
                        founder_ids = {
                            fixture.seed_key: account_ids[fixture.seed_key]
                            for fixture in FOUNDER_FIXTURES
                        }
                        reviewer_id = account_ids["reviewer"]
                        stage = "private product workflows"
                        async with sessions() as session, session.begin():
                            private = await service.seed_private_products(
                                session,
                                target_id=args.target_id,
                                founder_ids=founder_ids,
                                reviewer_id=reviewer_id,
                            )
                        stage = "public launch workflows"
                        launched = await service.seed_public_launches(
                            sessions,
                            target_id=args.target_id,
                            anchor_utc_date=anchor,
                            founder_ids=founder_ids,
                            reviewer_id=reviewer_id,
                        )
                        print(
                            "Seed complete: "
                            f"founders={len(founder_ids)} reviewer=1 "
                            f"profiles={len(founder_ids)} "
                            f"private_products={len(private)} "
                            "private_workflows=draft:1,submitted:1,changes_requested:1,"
                            "rejected:1,approved_unscheduled:1,scheduled:1 "
                            f"launched_products={len(launched)} "
                            "notifications=review_and_launch email_requests=0",
                            file=sys.stderr,
                        )
                    elif args.command == "cleanup":
                        async with sessions() as session:
                            artifacts = await repository.list_artifacts(
                                session, target_id=args.target_id
                            )
                        accounts = {
                            artifact.seed_key.removeprefix("account:"): artifact.entity_id
                            for artifact in artifacts
                            if artifact.artifact_kind == "account"
                            and artifact.seed_key.startswith("account:")
                        }
                        founders = {
                            fixture.seed_key: accounts[fixture.seed_key]
                            for fixture in FOUNDER_FIXTURES
                            if fixture.seed_key in accounts
                        }
                        summary = await service.cleanup_unreviewed_products(
                            sessions, target_id=args.target_id, founder_ids=founders
                        )
                        print(
                            f"Cleanup complete: deleted={summary['deleted']} "
                            f"retained={summary['retained']}",
                            file=sys.stderr,
                        )
                    else:
                        new_credentials = {
                            key: __import__("secrets").token_urlsafe(32) for key in args.account_key
                        }
                        async with sessions() as session, session.begin():
                            rotated = await service.rotate_credentials(
                                session,
                                target_id=args.target_id,
                                account_keys=tuple(args.account_key),
                                passwords=new_credentials,
                            )
                        sys.stdout.write(encode_credentials(rotated))
                        sys.stdout.flush()
                        print(
                            f"Credential rotation complete: accounts={len(rotated)}",
                            file=sys.stderr,
                        )
                finally:
                    await repository.release_session_target_lock(
                        lock_connection, target_id=args.target_id
                    )
                    await lock_connection.commit()
        finally:
            await database.close()
        return 0
    except DemoSeedTargetError as error:
        print(f"Demo seed target rejected: {error}", file=sys.stderr)
        return 2
    except (DemoAccountConflict, DemoSeedIdentityConflict) as error:
        print(f"Demo seed conflict: {error}", file=sys.stderr)
        return 1
    except (ConfigurationError, DatabasePreparationError):
        print(
            "Demo seed failed: required configuration or database state is unavailable.",
            file=sys.stderr,
        )
        return 1
    except (OSError, ValueError) as error:
        print(
            "Demo seed failed during "
            f"{stage} ({type(error).__name__}); "
            "required fixture, credential, or domain data is invalid.",
            file=sys.stderr,
        )
        return 1
    except Exception as error:
        print(
            "Demo seed failed during "
            f"{stage} ({type(error).__name__}); no record details were logged.",
            file=sys.stderr,
        )
        return 1


def main() -> None:
    """Run the operator operation without exposing secrets or row contents."""

    raise SystemExit(asyncio.run(_execute()))


if __name__ == "__main__":
    main()
