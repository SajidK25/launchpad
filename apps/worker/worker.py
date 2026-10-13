"""Durable transactional-email worker process."""

from __future__ import annotations

import asyncio
import base64
import os
import sys
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from app.modules.auth.staff import AuthAccessService
from app.modules.notifications.live import notification_channel
from app.modules.notifications.repository import NotificationRepository
from app.modules.products.service import ProductService
from app.shared.config.settings import Settings, load_settings
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.email.resend import ResendEmailSender
from app.shared.email.transport import EmailTransport
from app.shared.events.dispatcher import dispatch_claimed
from app.shared.events.outbox import OutboxRepository, PermanentEventError
from app.shared.storage.client import StorageClient
from app.shared.storage.objects import PrivateObjectStore
from health import ProgressHealth, progress_is_fresh, record_progress, redis_is_available
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

HEALTH_PATH = Path("/tmp/launchpad-worker.progress")
FRESHNESS_SECONDS = 5.0


class RedisPublisher(Protocol):
    async def publish(self, channel: str, message: str) -> int: ...


def create_email_sender(settings: Settings) -> EmailTransport | ResendEmailSender:
    """Select the production API sender or the local/check SMTP transport."""

    if settings.mail_sender is None:
        raise RuntimeError("Transactional email sender address is not configured.")
    if settings.environment == "production":
        if settings.resend_api_key is None:
            raise RuntimeError("Resend API credentials are not configured.")
        return ResendEmailSender(
            api_key=settings.resend_api_key.get_secret_value(),
            sender=str(settings.mail_sender),
        )
    if settings.smtp_host is None or settings.smtp_port is None or settings.smtp_use_tls is None:
        raise RuntimeError("Local transactional email transport is not configured.")
    return EmailTransport(
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        sender=str(settings.mail_sender),
        use_tls=settings.smtp_use_tls,
        username=settings.smtp_username.get_secret_value() if settings.smtp_username else None,
        password=settings.smtp_password.get_secret_value() if settings.smtp_password else None,
    )


class ReviewOutcomeEmailHandler:
    """Resolve a current verified recipient and render a feedback-free notice."""

    def __init__(
        self,
        *,
        member_access: AuthAccessService,
        notifications: NotificationRepository,
    ) -> None:
        self.member_access = member_access
        self.notifications = notifications

    async def prepare_email(
        self,
        session: AsyncSession,
        *,
        aggregate_id: UUID,
        payload: dict[str, object],
    ) -> dict[str, object]:
        recipient_id = _event_uuid(payload, "recipient_account_id")
        decision_id = _event_uuid(payload, "review_decision_id")
        notification_id = _event_uuid(payload, "notification_id")
        if decision_id != aggregate_id:
            raise PermanentEventError("review email aggregate does not match payload")
        notification = await self.notifications.get_for_recipient(
            session, recipient_id=recipient_id, notification_id=notification_id
        )
        if (
            notification is None
            or notification.review_decision_id != decision_id
            or notification.kind != payload.get("kind")
        ):
            raise PermanentEventError("review email payload does not match its notification")
        recipient = await self.member_access.verified_recipient_email(session, recipient_id)
        if recipient is None:
            raise PermanentEventError("review email recipient is no longer verified")

        subjects = {
            "review_approved": "Your product review is complete",
            "review_rejected": "Your product review is complete",
            "review_changes_requested": "Your product needs an update",
        }
        subject = subjects.get(notification.kind)
        if subject is None:
            raise PermanentEventError("review email notification kind is invalid")
        return {
            "recipient": recipient,
            "subject": subject,
            "body": "A review update is available in your Launchpad account. "
            "Sign in to view the outcome and any feedback.",
        }


class NotificationChangedPublisher:
    """Publish only a generic hint to the verified notification owner's channel."""

    def __init__(self, *, redis: RedisPublisher, notifications: NotificationRepository) -> None:
        self.redis = redis
        self.notifications = notifications

    async def publish_changed(
        self,
        session: AsyncSession,
        *,
        aggregate_id: UUID,
        payload: dict[str, object],
    ) -> None:
        del aggregate_id
        recipient_id = _event_uuid(payload, "recipient_account_id")
        notification_id = _event_uuid(payload, "notification_id")
        notification = await self.notifications.get_for_recipient(
            session, recipient_id=recipient_id, notification_id=notification_id
        )
        if notification is None:
            raise PermanentEventError("notification event recipient does not own the item")
        decision_value = payload.get("review_decision_id")
        if decision_value is not None:
            decision_id = _event_uuid(payload, "review_decision_id")
            if notification.review_decision_id != decision_id:
                raise PermanentEventError("notification event decision does not match the item")
        kind = payload.get("kind")
        if kind is not None and kind != notification.kind:
            raise PermanentEventError("notification event kind does not match the item")
        await self.redis.publish(notification_channel(recipient_id), "notifications_changed")


def _event_uuid(payload: dict[str, object], field: str) -> UUID:
    value = payload.get(field)
    if not isinstance(value, str):
        raise PermanentEventError(f"notification event {field} is invalid")
    try:
        return UUID(value)
    except ValueError as error:
        raise PermanentEventError(f"notification event {field} is invalid") from error


def is_healthy() -> bool:
    """Check real worker-loop progress and Redis availability."""
    return progress_is_fresh(HEALTH_PATH, FRESHNESS_SECONDS) and redis_is_available(
        os.environ.get("LAUNCHPAD_REDIS_URL", "redis://redis:6379/0")
    )


async def run_worker(health: ProgressHealth) -> None:
    settings = load_settings(require_worker_mail=True)
    database = Database.connect(str(settings.database_url))
    if settings.outbox_key is None or settings.outbox_key_id is None:
        raise RuntimeError("Outbox encryption configuration is required.")
    key = base64.b64decode(settings.outbox_key.get_secret_value(), validate=True)
    codec = EmailPayloadCodec({settings.outbox_key_id: key}, settings.outbox_key_id)
    if settings.storage_access_key_id is None or settings.storage_secret_access_key is None:
        raise RuntimeError("Storage runtime credentials are required.")
    storage_client = StorageClient(
        str(settings.storage_endpoint_url),
        settings.storage_access_key_id.get_secret_value(),
        settings.storage_secret_access_key.get_secret_value(),
        provider=settings.storage_provider,
        region_name=settings.storage_region,
    )
    product_storage = PrivateObjectStore(
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
        client_factory=storage_client._client,
    )
    email_sender = create_email_sender(settings)
    repository = OutboxRepository()
    notification_repository = NotificationRepository()
    member_access = AuthAccessService()
    redis = Redis.from_url(str(settings.redis_url), decode_responses=True)
    product_service = ProductService(
        member_access=member_access,
        outbox_repository=repository,
        payload_codec=codec,
        event_storage=product_storage,
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    try:
        await database.ensure_compatible()
        while True:
            try:
                async with sessions.begin() as session:
                    await repository.release_expired_claims(session)
                    claimed = await repository.claim_due(session, limit=20)
                for event in claimed:
                    async with sessions.begin() as session:
                        await dispatch_claimed(
                            session,
                            events=[event],
                            repository=repository,
                            codec=codec,
                            sender=email_sender,
                            product_handler=product_service,
                            review_email_handler=ReviewOutcomeEmailHandler(
                                member_access=member_access,
                                notifications=notification_repository,
                            ),
                            notification_handler=NotificationChangedPublisher(
                                redis=cast(RedisPublisher, redis),
                                notifications=notification_repository,
                            ),
                        )
                health.tick()
                record_progress(HEALTH_PATH)
            except Exception:
                # A stale progress file makes the container unhealthy while the
                # next iteration retries the durable database work.
                pass
            await asyncio.sleep(1)
    finally:
        if isinstance(email_sender, ResendEmailSender):
            await email_sender.aclose()
        await redis.aclose()
        await database.close()


def main() -> None:
    if "--health" in sys.argv:
        raise SystemExit(0 if is_healthy() else 1)

    health = ProgressHealth(
        connections=(
            lambda: redis_is_available(
                os.environ.get("LAUNCHPAD_REDIS_URL", "redis://redis:6379/0")
            ),
        )
    )
    asyncio.run(run_worker(health))


if __name__ == "__main__":
    main()
