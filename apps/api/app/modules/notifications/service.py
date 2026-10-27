"""Application service for durable review outcome notifications."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.modules.auth.staff import AccountState
from app.modules.notifications.models import LaunchNotificationPreference, Notification
from app.modules.notifications.policies import review_notification_kind
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.schemas import (
    LAUNCH_PREFERENCE_FIELDS,
    NotificationInbox,
    NotificationItem,
    NotificationKind,
)
from app.shared.events.outbox import OutboxEvent, OutboxRepository


class ReviewDecision(Protocol):
    """Minimal review decision data needed to create founder notifications."""

    id: UUID
    outcome: str


class LaunchNoticeBooking(Protocol):
    """Minimum durable booking identity needed to create a launch inbox notice."""

    id: UUID
    founder_id: UUID
    product_id: UUID


class NotificationMemberAccess(Protocol):
    async def current_account(
        self, session: AsyncSession, account_id: UUID, *, lock: bool = False
    ) -> AccountState | None: ...


class NotificationRepositoryAccess(Protocol):
    async def find_review_notification(
        self, session: AsyncSession, review_decision_id: UUID
    ) -> Notification | None: ...

    async def add(self, session: AsyncSession, notification: Notification) -> None: ...

    async def list_for_recipient(
        self,
        session: AsyncSession,
        *,
        recipient_id: UUID,
        limit: int,
        after: tuple[datetime, UUID] | None,
    ) -> list[Notification]: ...

    async def count_unread(self, session: AsyncSession, *, recipient_id: UUID) -> int: ...

    async def get_for_recipient(
        self, session: AsyncSession, *, recipient_id: UUID, notification_id: UUID
    ) -> Notification | None: ...

    async def mark_unread(
        self,
        session: AsyncSession,
        *,
        recipient_id: UUID,
        notification_id: UUID,
        read_at: datetime,
    ) -> Notification | None: ...


class NotificationPreferenceRepositoryAccess(Protocol):
    async def find_launch_preferences(
        self, session: AsyncSession, *, account_id: UUID
    ) -> LaunchNotificationPreference | None: ...

    async def save_launch_preferences(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
        values: dict[str, bool],
        updated_at: datetime,
    ) -> dict[str, bool]: ...


class LaunchNoticeRepositoryAccess(Protocol):
    async def find_launch_notification(
        self, session: AsyncSession, *, booking_id: UUID, kind: str
    ) -> Notification | None: ...

    async def add_launch_notification(
        self, session: AsyncSession, notification: Notification
    ) -> tuple[Notification, bool]: ...


class NotificationOutboxAccess(Protocol):
    async def add(self, session: AsyncSession, event: OutboxEvent) -> UUID: ...


class IdempotentNotificationOutboxAccess(Protocol):
    async def add_once(self, session: AsyncSession, event: OutboxEvent) -> UUID: ...


class NotificationPayloadCodec(Protocol):
    def encode(self, payload: dict[str, object]) -> tuple[str, bytes]: ...


class NotificationError(ValueError):
    """Base class for safe notification read failures."""


class NotificationForbiddenError(PermissionError):
    """The account is missing or no longer allowed to read its inbox."""


class NotificationNotFoundError(NotificationError):
    """The requested notification is not owned by the current account."""


class NotificationValidationError(NotificationError):
    """The page request is malformed or outside its supported bounds."""


class NotificationService:
    """Persist inbox and dispatch intents inside the caller-owned transaction."""

    def __init__(
        self,
        *,
        repository: NotificationRepositoryAccess | None = None,
        preference_repository: NotificationPreferenceRepositoryAccess | None = None,
        launch_notice_repository: LaunchNoticeRepositoryAccess | None = None,
        outbox_repository: NotificationOutboxAccess | None = None,
        idempotent_outbox_repository: IdempotentNotificationOutboxAccess | None = None,
        payload_codec: NotificationPayloadCodec,
        member_access: NotificationMemberAccess | None = None,
        clock: Callable[[], datetime] | None = None,
        send_review_email: bool = True,
    ) -> None:
        self.repository = repository or NotificationRepository()
        self.preference_repository = preference_repository or NotificationRepository()
        self.launch_notice_repository = launch_notice_repository or NotificationRepository()
        self.outbox_repository = outbox_repository or OutboxRepository()
        self.idempotent_outbox_repository = idempotent_outbox_repository or OutboxRepository()
        self.payload_codec = payload_codec
        self.send_review_email = send_review_email
        if member_access is None:
            from app.modules.auth.staff import AuthAccessService

            self.member_access: NotificationMemberAccess = AuthAccessService()
        else:
            self.member_access = member_access
        self.clock = clock or (lambda: datetime.now(UTC))

    async def launch_preferences(self, session: AsyncSession, *, actor_id: UUID) -> dict[str, bool]:
        """Read one active account's preferences, applying enabled defaults without a write."""

        await self._require_active_account(session, actor_id)
        row = await self.preference_repository.find_launch_preferences(session, account_id=actor_id)
        if row is None:
            return {field: True for field in LAUNCH_PREFERENCE_FIELDS}
        return {field: bool(getattr(row, field)) for field in LAUNCH_PREFERENCE_FIELDS}

    async def update_launch_preferences(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        values: dict[str, bool],
    ) -> dict[str, bool]:
        """Persist provided channel choices while preserving the other five values."""

        await self._require_active_account(session, actor_id)
        if not values or any(
            key not in LAUNCH_PREFERENCE_FIELDS or type(value) is not bool
            for key, value in values.items()
        ):
            raise NotificationValidationError("invalid launch preferences")
        return await self.preference_repository.save_launch_preferences(
            session, account_id=actor_id, values=values, updated_at=self.clock()
        )

    async def record_launch_notice(
        self,
        session: AsyncSession,
        *,
        booking: LaunchNoticeBooking,
        kind: str,
    ) -> Notification | None:
        """Persist enabled launch channels atomically and deduplicate by booking and kind.

        The launch booking retains failure reason independently of these optional notices.
        """

        preference_prefix = {
            "launch_reminder": "reminder",
            "launch_live": "live",
            "launch_failed": "failure",
        }.get(kind)
        if preference_prefix is None:
            raise NotificationValidationError("invalid launch notice kind")

        existing = await self.launch_notice_repository.find_launch_notification(
            session, booking_id=booking.id, kind=kind
        )
        if existing is not None:
            return existing

        preferences = await self.preference_repository.find_launch_preferences(
            session, account_id=booking.founder_id
        )
        email_enabled = (
            True
            if preferences is None
            else bool(getattr(preferences, f"{preference_prefix}_email"))
        )
        in_site_enabled = (
            True
            if preferences is None
            else bool(getattr(preferences, f"{preference_prefix}_in_site"))
        )
        if not email_enabled and not in_site_enabled:
            return None

        now = self.clock()
        notice: Notification | None = None
        if in_site_enabled:
            candidate = Notification(
                id=uuid7(),
                recipient_account_id=booking.founder_id,
                product_id=booking.product_id,
                review_decision_id=None,
                launch_booking_id=booking.id,
                kind=kind,
                created_at=now,
                read_at=None,
            )
            notice, created = await self.launch_notice_repository.add_launch_notification(
                session, candidate
            )
            if not created:
                return notice

        if email_enabled:
            email_key, email_payload = self.payload_codec.encode(
                {
                    "recipient_account_id": booking.founder_id,
                    "launch_booking_id": booking.id,
                    "notification_id": notice.id if notice is not None else booking.id,
                    "kind": kind,
                }
            )
            await self.idempotent_outbox_repository.add_once(
                session,
                OutboxEvent(
                    event_type="launch.notice_email_requested.v1",
                    aggregate_id=booking.id,
                    id=uuid5(NAMESPACE_URL, f"launch-email:{booking.id}:{kind}"),
                    key_id=email_key,
                    encrypted_payload=email_payload,
                    available_at=now,
                ),
            )

        if notice is not None:
            live_key, live_payload = self.payload_codec.encode(
                {
                    "recipient_account_id": booking.founder_id,
                    "launch_booking_id": booking.id,
                    "notification_id": notice.id,
                    "kind": kind,
                }
            )
            await self.idempotent_outbox_repository.add_once(
                session,
                OutboxEvent(
                    event_type="notification.changed.v1",
                    aggregate_id=booking.id,
                    id=uuid5(NAMESPACE_URL, f"launch-inbox:{booking.id}:{kind}"),
                    key_id=live_key,
                    encrypted_payload=live_payload,
                    available_at=now,
                ),
            )
        return notice

    async def inbox(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        first: int = 20,
        after: str | None = None,
    ) -> NotificationInbox:
        """Return a bounded inbox page and unread count for one active account."""

        await self._require_active_account(session, actor_id)
        if not 1 <= first <= 50:
            raise NotificationValidationError("invalid page size")
        cursor = _parse_cursor(after) if after is not None else None
        rows = await self.repository.list_for_recipient(
            session, recipient_id=actor_id, limit=first + 1, after=cursor
        )
        visible = rows[:first]
        unread_count = await self.repository.count_unread(session, recipient_id=actor_id)
        return NotificationInbox(
            items=tuple(_item(row) for row in visible),
            unread_count=unread_count,
            next_cursor=(
                _cursor(visible[-1].created_at, visible[-1].id)
                if len(rows) > first and visible
                else None
            ),
        )

    async def mark_read(
        self, session: AsyncSession, *, actor_id: UUID, notification_id: UUID
    ) -> NotificationItem:
        """Mark one owned item read and enqueue one hint only on the first change."""

        await self._require_active_account(session, actor_id)
        notification = await self.repository.get_for_recipient(
            session, recipient_id=actor_id, notification_id=notification_id
        )
        if notification is None:
            raise NotificationNotFoundError("notification unavailable")
        if notification.read_at is None:
            read_at = self.clock()
            changed = await self.repository.mark_unread(
                session,
                recipient_id=actor_id,
                notification_id=notification_id,
                read_at=read_at,
            )
            if changed is not None:
                notification = changed
                key_id, payload = self.payload_codec.encode(
                    {"recipient_account_id": actor_id, "notification_id": notification_id}
                )
                await self.outbox_repository.add(
                    session,
                    OutboxEvent(
                        event_type="notification.changed.v1",
                        aggregate_id=notification_id,
                        key_id=key_id,
                        encrypted_payload=payload,
                        available_at=read_at,
                    ),
                )
            else:
                # Another request may have completed the same read while this one waited.
                notification = await self.repository.get_for_recipient(
                    session, recipient_id=actor_id, notification_id=notification_id
                )
                if notification is None:
                    raise NotificationNotFoundError("notification unavailable")
        return _item(notification)

    async def _require_active_account(self, session: AsyncSession, actor_id: UUID) -> AccountState:
        account = await self.member_access.current_account(session, actor_id)
        if account is None or account.suspended_at is not None:
            raise NotificationForbiddenError("notification access is forbidden")
        return account

    async def record_review_outcome(
        self,
        session: AsyncSession,
        *,
        decision: ReviewDecision,
        founder_id: UUID,
        product_id: UUID,
    ) -> Notification:
        """Add one durable notice and its configured encrypted outbox requests."""

        existing = await self.repository.find_review_notification(session, decision.id)
        if existing is not None:
            return existing

        notification = Notification(
            id=uuid7(),
            recipient_account_id=founder_id,
            product_id=product_id,
            review_decision_id=decision.id,
            kind=review_notification_kind(decision.outcome),
            created_at=self.clock(),
            read_at=None,
        )
        await self.repository.add(session, notification)

        if self.send_review_email:
            email_key, email_payload = self.payload_codec.encode(
                {
                    "recipient_account_id": founder_id,
                    "review_decision_id": decision.id,
                    "notification_id": notification.id,
                    "kind": notification.kind,
                }
            )
            await self.outbox_repository.add(
                session,
                OutboxEvent(
                    event_type="review.outcome_email_requested.v1",
                    aggregate_id=decision.id,
                    key_id=email_key,
                    encrypted_payload=email_payload,
                    available_at=self.clock(),
                ),
            )

        live_key, live_payload = self.payload_codec.encode(
            {
                "recipient_account_id": founder_id,
                "notification_id": notification.id,
                "kind": notification.kind,
            }
        )
        await self.outbox_repository.add(
            session,
            OutboxEvent(
                event_type="notification.changed.v1",
                aggregate_id=decision.id,
                key_id=live_key,
                encrypted_payload=live_payload,
                available_at=self.clock(),
            ),
        )
        return notification


def _item(notification: Notification) -> NotificationItem:
    return NotificationItem(
        id=notification.id,
        product_id=notification.product_id,
        kind=cast(NotificationKind, notification.kind),
        created_at=notification.created_at,
        read_at=notification.read_at,
    )


def _cursor(created_at: datetime, notification_id: UUID) -> str:
    return f"{created_at.isoformat()}|{notification_id}"


def _parse_cursor(value: str) -> tuple[datetime, UUID]:
    try:
        if len(value) > 128:
            raise ValueError("cursor too long")
        timestamp_text, notification_text = value.split("|", maxsplit=1)
        timestamp = datetime.fromisoformat(timestamp_text)
        notification_id = UUID(notification_text)
        if timestamp.tzinfo is None:
            raise ValueError("timezone required")
    except ValueError as error:
        raise NotificationValidationError("invalid cursor") from error
    return timestamp, notification_id
