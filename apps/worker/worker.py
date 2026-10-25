"""Durable transactional-email worker process."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, cast
from uuid import UUID

from app.modules.auth.staff import AuthAccessService
from app.modules.launches.repository import LaunchBookingRepository
from app.modules.launches.service import LaunchBookingService
from app.modules.notifications.live import notification_channel
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.service import NotificationService
from app.modules.products.service import ProductService
from app.modules.votes.repository import VoteRepository
from app.modules.votes.service import (
    RankingRedis,
    VoteRankingProjectionService,
    VoteSnapshotService,
)
from app.shared.config.settings import Settings, load_settings
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.email.resend import ResendEmailSender
from app.shared.email.transport import EmailTransport
from app.shared.events.dispatcher import (
    EMAIL_EVENT_TYPES,
    LAUNCH_EMAIL_EVENT_TYPES,
    REVIEW_EMAIL_EVENT_TYPES,
    dispatch_claimed,
)
from app.shared.events.models import OutboxMessage
from app.shared.events.outbox import OutboxRepository, PermanentEventError
from app.shared.storage.client import StorageClient
from app.shared.storage.objects import PrivateObjectStore
from health import ProgressHealth, progress_is_fresh, record_progress, redis_is_available
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

HEALTH_PATH = Path("/tmp/launchpad-worker.progress")
FRESHNESS_SECONDS = 5.0
logger = logging.getLogger(__name__)


class RedisPublisher(Protocol):
    async def publish(self, channel: str, message: str) -> int: ...


async def process_claimed_events(
    events: list[OutboxMessage],
    *,
    sessions: async_sessionmaker[AsyncSession],
    dispatch: Callable[[AsyncSession, OutboxMessage], Awaitable[None]],
    concurrency: int,
    email_concurrency: int,
    on_progress: Callable[[], None] | None = None,
) -> None:
    """Dispatch independent events with isolated transactions and bounded fan-out."""

    if concurrency < 1 or email_concurrency < 1:
        raise ValueError("worker concurrency limits must be positive")
    event_slots = asyncio.Semaphore(concurrency)
    email_slots = asyncio.Semaphore(email_concurrency)
    email_types = EMAIL_EVENT_TYPES | REVIEW_EMAIL_EVENT_TYPES | LAUNCH_EMAIL_EVENT_TYPES

    async def run_one(event: OutboxMessage) -> None:
        async with event_slots:
            try:
                if event.event_type in email_types:
                    async with email_slots:
                        async with sessions.begin() as session:
                            await dispatch(session, event)
                else:
                    async with sessions.begin() as session:
                        await dispatch(session, event)
            except Exception:
                logger.exception(
                    "Outbox event transaction failed",
                    extra={"event_id": str(event.id), "event_type": event.event_type},
                )
            finally:
                if on_progress is not None:
                    on_progress()

    await asyncio.gather(*(run_one(event) for event in events))


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


class LaunchEventWorker:
    """Recheck booking, product, and founder state before reminder or publication work."""

    def __init__(
        self,
        *,
        bookings: LaunchBookingService,
        products: ProductService,
        notifications: NotificationService,
        member_access: AuthAccessService,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.bookings = bookings
        self.products = products
        self.notifications = notifications
        self.member_access = member_access
        self.clock = clock or (lambda: datetime.now(UTC))

    async def handle_launch_event(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        aggregate_id: UUID,
        payload: dict[str, object],
    ) -> None:
        booking_id = _event_uuid(payload, "launch_booking_id")
        product_id = _event_uuid(payload, "product_id")
        if booking_id != aggregate_id:
            raise PermanentEventError("launch event aggregate does not match booking")
        # Take an unlocked snapshot only to discover the founder/product. All
        # contending launch/review paths then lock account -> product -> booking.
        snapshot = await self.bookings.booking_by_id(session, booking_id=booking_id)
        if snapshot is None or snapshot.product_id != product_id:
            raise PermanentEventError("launch event does not identify a booking")
        if snapshot.state != "scheduled":
            return

        account = await self.member_access.current_account(session, snapshot.founder_id, lock=True)
        product = await self.products.get_scheduled_product(
            session,
            founder_id=snapshot.founder_id,
            product_id=snapshot.product_id,
            lock=True,
        )
        booking = await self.bookings.booking_by_id(session, booking_id=booking_id, lock=True)
        if (
            booking is None
            or booking.product_id != snapshot.product_id
            or booking.founder_id != snapshot.founder_id
        ):
            raise PermanentEventError("launch booking changed identity")
        if booking.state != "scheduled":
            return
        if product is None:
            # For example, review may have returned the product for changes
            # while this worker waited for its product lock.
            return
        now = self.clock().astimezone(UTC)

        if event_type == "launch.reminder_requested.v1":
            if now >= booking.launch_at.astimezone(UTC):
                return
            if product is None or account is None or account.suspended_at is not None:
                return
            await self.notifications.record_launch_notice(
                session, booking=booking, kind="launch_reminder"
            )
            return

        if event_type != "launch.publish_requested.v1":
            raise PermanentEventError("unrecognized launch event")

        product = await self.products.publish_scheduled_product(
            session,
            product_id=booking.product_id,
            launch_at=booking.launch_at,
            now=now,
        )
        if product.status == "launched":
            outcome = "launched"
            notice_kind = "launch_live"
        elif product.launch_failure_reason in {"missed_day", "suspension_blocked"}:
            outcome = product.launch_failure_reason
            notice_kind = "launch_failed"
        else:
            raise PermanentEventError("launch product returned an invalid outcome")

        closed = await self.bookings.record_publication_outcome(
            session,
            booking_id=booking.id,
            outcome=cast(Literal["launched", "missed_day", "suspension_blocked"], outcome),
            now=now,
        )
        if closed is None:
            raise PermanentEventError("launch booking disappeared during publication")
        await self.notifications.record_launch_notice(session, booking=closed, kind=notice_kind)


class LaunchNoticeEmailHandler:
    """Prepare only still-relevant launch email for the current verified recipient."""

    def __init__(
        self,
        *,
        bookings: LaunchBookingService,
        member_access: AuthAccessService,
        notifications: NotificationRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.bookings = bookings
        self.member_access = member_access
        self.notifications = notifications
        self.clock = clock or (lambda: datetime.now(UTC))

    async def prepare_email(
        self,
        session: AsyncSession,
        *,
        aggregate_id: UUID,
        payload: dict[str, object],
    ) -> dict[str, object]:
        booking_id = _event_uuid(payload, "launch_booking_id")
        recipient_id = _event_uuid(payload, "recipient_account_id")
        notification_id = _event_uuid(payload, "notification_id")
        kind = payload.get("kind")
        if booking_id != aggregate_id or kind not in {
            "launch_reminder",
            "launch_live",
            "launch_failed",
        }:
            raise PermanentEventError("launch email metadata is invalid")
        booking = await self.bookings.booking_by_id(session, booking_id=booking_id)
        if booking is None or booking.founder_id != recipient_id:
            raise PermanentEventError("launch email recipient does not own the booking")
        prefix = {
            "launch_reminder": "reminder",
            "launch_live": "live",
            "launch_failed": "failure",
        }[kind]
        preference = await self.notifications.find_launch_preferences(
            session, account_id=recipient_id
        )
        if preference is not None and not bool(getattr(preference, f"{prefix}_email")):
            raise PermanentEventError("launch email channel is disabled")
        now = self.clock().astimezone(UTC)
        if kind == "launch_reminder" and (
            booking.state != "scheduled" or now >= booking.launch_at.astimezone(UTC)
        ):
            raise PermanentEventError("launch reminder is no longer relevant")
        if kind == "launch_live" and booking.state != "launched":
            raise PermanentEventError("launch notice is no longer relevant")
        if kind == "launch_failed" and (
            booking.state not in {"missed_day", "suspension_blocked"}
            or booking.failure_reason != booking.state
        ):
            raise PermanentEventError("launch failure notice is no longer relevant")
        if notification_id != booking.id:
            notification = await self.notifications.get_for_recipient(
                session, recipient_id=recipient_id, notification_id=notification_id
            )
            if (
                notification is None
                or notification.launch_booking_id != booking.id
                or notification.kind != kind
            ):
                raise PermanentEventError("launch email notification is no longer available")
        recipient = await self.member_access.verified_recipient_email(session, recipient_id)
        if recipient is None:
            raise PermanentEventError("launch email recipient is no longer verified")
        subjects = {
            "launch_reminder": "Your Launchpad launch is coming up",
            "launch_live": "Your product is live on Launchpad",
            "launch_failed": "There is an update about your launch",
        }
        body = {
            "launch_reminder": "Your scheduled launch is coming up. Sign in to review its status.",
            "launch_live": "Your product is now live. Sign in to view your launch dashboard.",
            "launch_failed": "Your launch could not be completed. Sign in to view the reason.",
        }
        return {"recipient": recipient, "subject": subjects[kind], "body": body[kind]}


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
        booking_value = payload.get("launch_booking_id")
        if booking_value is not None:
            booking_id = _event_uuid(payload, "launch_booking_id")
            if booking_id != aggregate_id or notification.launch_booking_id != booking_id:
                raise PermanentEventError("notification event booking does not match the item")
        elif notification.launch_booking_id is not None:
            raise PermanentEventError("launch notification event is missing its booking")
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
    launch_bookings = LaunchBookingService(
        member_access=member_access,
        product_access=product_service,
        repository=LaunchBookingRepository(),
        outbox_repository=repository,
        payload_codec=codec,
    )
    notification_service = NotificationService(
        outbox_repository=repository,
        payload_codec=codec,
        member_access=member_access,
    )
    launch_event_handler = LaunchEventWorker(
        bookings=launch_bookings,
        products=product_service,
        notifications=notification_service,
        member_access=member_access,
    )
    vote_repository = VoteRepository(score_half_life_seconds=settings.vote_score_half_life_seconds)
    vote_snapshot_service = VoteSnapshotService(
        products=product_service,
        repository=vote_repository,
        outbox=repository,
        codec=codec,
    )
    vote_ranking_handler = VoteRankingProjectionService(
        products=product_service,
        repository=vote_repository,
        redis=cast(RankingRedis, redis),
        snapshots=vote_snapshot_service,
    )
    launch_email_handler = LaunchNoticeEmailHandler(
        bookings=launch_bookings,
        member_access=member_access,
        notifications=notification_repository,
    )
    sessions = async_sessionmaker(database.engine, expire_on_commit=False)

    async def dispatch_event(session: AsyncSession, event: OutboxMessage) -> None:
        await dispatch_claimed(
            session,
            events=[event],
            repository=repository,
            codec=codec,
            sender=email_sender,
            product_handler=product_service,
            launch_email_handler=launch_email_handler,
            launch_event_handler=launch_event_handler,
            review_email_handler=ReviewOutcomeEmailHandler(
                member_access=member_access,
                notifications=notification_repository,
            ),
            notification_handler=NotificationChangedPublisher(
                redis=cast(RedisPublisher, redis),
                notifications=notification_repository,
            ),
            vote_ranking_handler=vote_ranking_handler,
        )

    def record_worker_progress() -> None:
        health.tick()
        record_progress(HEALTH_PATH)

    try:
        await database.ensure_compatible()
        while True:
            try:
                async with sessions.begin() as session:
                    await repository.release_expired_claims(session)
                    claimed = await repository.claim_due(
                        session, limit=min(settings.worker_concurrency * 4, 512)
                    )
                await process_claimed_events(
                    claimed,
                    sessions=sessions,
                    dispatch=dispatch_event,
                    concurrency=settings.worker_concurrency,
                    email_concurrency=settings.worker_email_concurrency,
                    on_progress=record_worker_progress,
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
