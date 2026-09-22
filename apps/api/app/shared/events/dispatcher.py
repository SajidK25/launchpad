"""Worker-side outbox claim, decrypt, send, and delivery state transitions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.models import OutboxMessage
from app.shared.events.outbox import OutboxRepository


class EmailSender(Protocol):
    async def send(self, payload: dict[str, object], *, message_id: str) -> None: ...


async def dispatch_due(
    session: AsyncSession,
    *,
    repository: OutboxRepository,
    codec: EmailPayloadCodec,
    sender: EmailSender,
    now: datetime | None = None,
    limit: int = 20,
) -> int:
    """Dispatch one bounded batch and return the number of completed messages."""

    current = now or datetime.now(UTC)
    completed = 0
    for event in await repository.claim_due(session, now=current, limit=limit):
        try:
            payload = codec.decode(event.key_id, event.encrypted_payload or b"")
            if _is_expired_challenge(event, payload, current):
                event.state = "dead"
                event.claimed_at = None
                event.encrypted_payload = None
                await session.flush()
                continue
            message_id = f"launchpad-{event.id}"
            await sender.send(payload, message_id=message_id)
            await repository.complete(session, event.id, message_id=message_id, sent_at=current)
            completed += 1
        except Exception:
            await repository.retry(session, event.id, now=current)
    return completed


def _is_expired_challenge(event: OutboxMessage, payload: dict[str, object], now: datetime) -> bool:
    if not event.event_type.startswith(("auth.verification_requested", "auth.password_reset")):
        return False
    expires_at = payload.get("expires_at")
    if not isinstance(expires_at, str):
        return False
    try:
        expiry = datetime.fromisoformat(expires_at)
    except ValueError:
        return True
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return expiry <= now
