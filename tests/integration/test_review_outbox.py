"""Database and Redis integration for typed review outbox dispatch."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from uuid import uuid4

from app.modules.auth.models import Account
from app.modules.auth.staff import AuthAccessService
from app.modules.notifications.live import notification_channel
from app.modules.notifications.models import Notification
from app.modules.notifications.repository import NotificationRepository
from app.modules.products.models import Product, ProductReviewDecision, ProductSubmission
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.dispatcher import dispatch_due
from app.shared.events.models import EmailDelivery, OutboxMessage
from app.shared.events.outbox import OutboxEvent, OutboxRepository
from conftest import IntegrationSettings
from redis.asyncio import Redis
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker

sys.path.insert(0, "apps/worker")

from worker import NotificationChangedPublisher, ReviewOutcomeEmailHandler


class _Sender:
    def __init__(self) -> None:
        self.sent: list[tuple[dict[str, object], str]] = []

    async def send(self, payload: dict[str, object], *, message_id: str) -> None:
        self.sent.append((payload, message_id))


def test_review_outbox_dispatches_private_email_and_owner_scoped_hint(
    integration_settings_fixture: IntegrationSettings,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        redis = Redis.from_url(integration_settings_fixture.redis_url, decode_responses=True)
        sessions = async_sessionmaker(database.engine, expire_on_commit=False)
        now = datetime.now(UTC)
        staff_id, owner_id, other_id = uuid4(), uuid4(), uuid4()
        product_id, submission_id, decision_id, notification_id = (
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
        )
        feedback = "private feedback must not appear in email or Redis"
        codec = EmailPayloadCodec({"review-test": b"q" * 32}, "review-test")
        email_payload = {
            "recipient_account_id": str(owner_id),
            "review_decision_id": str(decision_id),
            "notification_id": str(notification_id),
            "kind": "review_changes_requested",
        }
        live_payload = {
            "recipient_account_id": str(owner_id),
            "notification_id": str(notification_id),
            "review_decision_id": str(decision_id),
            "kind": "review_changes_requested",
        }
        wrong_owner_payload = {
            "recipient_account_id": str(other_id),
            "notification_id": str(notification_id),
            "review_decision_id": str(decision_id),
            "kind": "review_changes_requested",
        }
        pubsub = redis.pubsub()
        await database.ensure_compatible()
        try:
            await pubsub.subscribe(notification_channel(owner_id))
            subscribed = await pubsub.get_message(ignore_subscribe_messages=False, timeout=1)
            assert subscribed is not None
            assert subscribed["type"] == "subscribe"
            async with sessions() as session, session.begin():
                for account_id, email, role in (
                    (staff_id, f"{staff_id}@example.com", "reviewer"),
                    (owner_id, "founder@example.com", "member"),
                    (other_id, "other@example.com", "member"),
                ):
                    await session.execute(
                        insert(Account).values(
                            id=account_id,
                            email_display=email,
                            email_key=email.lower(),
                            password_hash="integration-only-not-a-real-hash",
                            verified_at=now,
                            role=role,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                await session.execute(
                    insert(Product).values(
                        id=product_id,
                        founder_id=owner_id,
                        status="changes_requested",
                        version=2,
                        name="Private product title",
                        pitch="Private pitch",
                        description="Private description",
                        website_url="https://private.example.com/product",
                        website_key="https://private.example.com/product",
                        created_at=now,
                        updated_at=now,
                    )
                )
                await session.execute(
                    insert(ProductSubmission).values(
                        id=submission_id,
                        product_id=product_id,
                        state="changes_requested",
                        submitted_at=now,
                        closed_at=now,
                        product_version=2,
                    )
                )
                await session.execute(
                    insert(ProductReviewDecision).values(
                        id=decision_id,
                        submission_id=submission_id,
                        actor_account_id=staff_id,
                        from_status="submitted",
                        outcome="changes_requested",
                        reviewed_product_version=2,
                        feedback=feedback,
                        idempotency_key=f"review-outbox-{decision_id}",
                        request_fingerprint="c" * 64,
                        created_at=now,
                    )
                )
                await session.execute(
                    insert(Notification).values(
                        id=notification_id,
                        recipient_account_id=owner_id,
                        product_id=product_id,
                        review_decision_id=decision_id,
                        kind="review_changes_requested",
                        created_at=now,
                        read_at=None,
                    )
                )
                repository = OutboxRepository()
                email_key, email_ciphertext = codec.encode(email_payload)
                email_id = await repository.add(
                    session,
                    OutboxEvent(
                        event_type="review.outcome_email_requested.v1",
                        aggregate_id=decision_id,
                        key_id=email_key,
                        encrypted_payload=email_ciphertext,
                        available_at=now,
                    ),
                )
                live_key, live_ciphertext = codec.encode(live_payload)
                live_id = await repository.add(
                    session,
                    OutboxEvent(
                        event_type="notification.changed.v1",
                        aggregate_id=decision_id,
                        key_id=live_key,
                        encrypted_payload=live_ciphertext,
                        available_at=now,
                    ),
                )
                wrong_key, wrong_ciphertext = codec.encode(wrong_owner_payload)
                wrong_owner_id = await repository.add(
                    session,
                    OutboxEvent(
                        event_type="notification.changed.v1",
                        aggregate_id=decision_id,
                        key_id=wrong_key,
                        encrypted_payload=wrong_ciphertext,
                        available_at=now,
                    ),
                )
                sender = _Sender()
                delivered = await dispatch_due(
                    session,
                    repository=repository,
                    codec=codec,
                    sender=sender,
                    review_email_handler=ReviewOutcomeEmailHandler(
                        member_access=AuthAccessService(),
                        notifications=NotificationRepository(),
                    ),
                    notification_handler=NotificationChangedPublisher(
                        redis=redis,
                        notifications=NotificationRepository(),
                    ),
                    now=now,
                )
                assert delivered == 2
                assert len(sender.sent) == 1
                sent_payload, message_id = sender.sent[0]
                assert sent_payload["recipient"] == "founder@example.com"
                assert sent_payload["subject"] == "Your product needs an update"
                assert feedback not in str(sent_payload)
                assert "Private product title" not in str(sent_payload)
                assert message_id == f"launchpad-{email_id}"
                states = {
                    row.id: row.state
                    for row in (
                        await session.scalars(
                            select(OutboxMessage).where(
                                OutboxMessage.id.in_((email_id, live_id, wrong_owner_id))
                            )
                        )
                    ).all()
                }
                assert states[email_id] == states[live_id] == "completed"
                assert states[wrong_owner_id] == "dead"
                assert await session.get(EmailDelivery, email_id) is not None

            hint = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1)
            assert hint is not None
            assert hint["channel"] == notification_channel(owner_id)
            assert hint["data"] == "notifications_changed"
            assert feedback not in str(hint)
            assert "Private product title" not in str(hint)
        finally:
            await pubsub.unsubscribe(notification_channel(owner_id))
            await pubsub.aclose()
            async with sessions.begin() as session:
                await session.execute(
                    delete(EmailDelivery).where(
                        EmailDelivery.event_id.in_(
                            select(OutboxMessage.id).where(
                                OutboxMessage.aggregate_id == decision_id,
                                OutboxMessage.event_type.in_(
                                    ("review.outcome_email_requested.v1", "notification.changed.v1")
                                ),
                            )
                        )
                    )
                )
                await session.execute(
                    delete(OutboxMessage).where(
                        OutboxMessage.aggregate_id == decision_id,
                        OutboxMessage.event_type.in_(
                            ("review.outcome_email_requested.v1", "notification.changed.v1")
                        ),
                    )
                )
                await session.execute(
                    delete(Notification).where(Notification.id == notification_id)
                )
                await session.execute(
                    delete(ProductReviewDecision).where(ProductReviewDecision.id == decision_id)
                )
                await session.execute(
                    delete(ProductSubmission).where(ProductSubmission.id == submission_id)
                )
                await session.execute(delete(Product).where(Product.id == product_id))
                await session.execute(
                    delete(Account).where(Account.id.in_((staff_id, owner_id, other_id)))
                )
            await redis.aclose()
            await database.close()

    asyncio.run(verify())
