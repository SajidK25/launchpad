"""Resend HTTP contract tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.email.codec import EmailPayloadCodec
from app.shared.email.resend import (
    ResendEmailSender,
    ResendPermanentError,
    ResendTransientError,
)
from app.shared.events.dispatcher import dispatch_due
from app.shared.events.outbox import OutboxRepository


class _FailFirstCompletion:
    def __init__(self, event: SimpleNamespace) -> None:
        self.event = event
        self.completion_attempts = 0
        self.completed: list[UUID] = []
        self.retried: list[UUID] = []
        self.dead_lettered: list[UUID] = []

    async def claim_due(
        self, _session: AsyncSession, *, now: datetime, limit: int
    ) -> list[SimpleNamespace]:
        del now, limit
        return [self.event]

    async def complete_email(
        self,
        _session: AsyncSession,
        event_id: UUID,
        *,
        message_id: str,
        sent_at: datetime,
    ) -> None:
        del message_id, sent_at
        self.completion_attempts += 1
        if self.completion_attempts == 1:
            raise RuntimeError("simulated worker failure after provider acceptance")
        self.completed.append(event_id)

    async def retry(self, _session: AsyncSession, event_id: UUID, *, now: datetime) -> bool:
        del now
        self.retried.append(event_id)
        return False

    async def dead_letter(
        self, _session: AsyncSession, event_id: UUID, *, clear_payload: bool = False
    ) -> None:
        del clear_payload
        self.dead_lettered.append(event_id)


def _email_event(codec: EmailPayloadCodec) -> SimpleNamespace:
    payload = {
        "recipient": "founder@example.com",
        "subject": "Verification",
        "body": "Follow this private verification link.",
    }
    key_id, ciphertext = codec.encode(payload)
    return SimpleNamespace(
        id=uuid4(),
        event_type="auth.verification_requested.v1",
        aggregate_id=uuid4(),
        key_id=key_id,
        encrypted_payload=ciphertext,
    )


def test_sends_with_stable_outbox_key_and_configured_sender() -> None:
    async def verify() -> None:
        requests: list[httpx2.Request] = []

        def respond(request: httpx2.Request) -> httpx2.Response:
            requests.append(request)
            return httpx2.Response(200, json={"id": "resend-message-1"})

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
            sender = ResendEmailSender(
                api_key="re_test_secret",
                sender="Launchpad <noreply@example.com>",
                client=client,
            )
            await sender.send(
                {
                    "recipient": "founder@example.com",
                    "subject": "Review update",
                    "body": "Sign in to see the update.",
                },
                message_id="launchpad-0199-outbox-event",
            )

        assert len(requests) == 1
        request = requests[0]
        assert request.method == "POST"
        assert str(request.url) == "https://api.resend.com/emails"
        assert request.headers["Authorization"] == "Bearer re_test_secret"
        assert request.headers["Idempotency-Key"] == "launchpad-0199-outbox-event"
        assert request.read().decode() == (
            '{"from":"Launchpad <noreply@example.com>","to":["founder@example.com"],'
            '"subject":"Review update","text":"Sign in to see the update."}'
        )

    asyncio.run(verify())


@pytest.mark.parametrize("status_code", (408, 429, 503))
def test_classifies_timeout_rate_limit_and_server_errors_as_transient(status_code: int) -> None:
    async def verify() -> None:
        def respond(_request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(status_code, text="founder@example.com private feedback")

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
            sender = ResendEmailSender(
                api_key="re_provider_secret",
                sender="noreply@example.com",
                client=client,
            )
            with pytest.raises(ResendTransientError) as error:
                await sender.send(
                    {
                        "recipient": "founder@example.com",
                        "subject": "Review update",
                        "body": "private feedback",
                    },
                    message_id="launchpad-stable-outbox-id",
                )

        assert "re_provider_secret" not in str(error.value)
        assert "founder@example.com" not in str(error.value)
        assert "private feedback" not in str(error.value)

    asyncio.run(verify())


def test_classifies_http_timeout_as_transient_without_exposing_request_data() -> None:
    async def verify() -> None:
        def timeout(_request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ReadTimeout("founder@example.com private feedback re_secret")

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(timeout)) as client:
            sender = ResendEmailSender(
                api_key="re_secret",
                sender="noreply@example.com",
                client=client,
            )
            with pytest.raises(ResendTransientError) as error:
                await sender.send(
                    {
                        "recipient": "founder@example.com",
                        "subject": "Review update",
                        "body": "private feedback",
                    },
                    message_id="launchpad-stable-outbox-id",
                )

        assert "re_secret" not in str(error.value)
        assert "founder@example.com" not in str(error.value)
        assert "private feedback" not in str(error.value)

    asyncio.run(verify())


def test_classifies_nonretryable_provider_response_as_permanent() -> None:
    async def verify() -> None:
        def respond(_request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                422,
                json={"name": "validation_error", "message": "founder@example.com private data"},
            )

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
            sender = ResendEmailSender(
                api_key="re_provider_secret",
                sender="noreply@example.com",
                client=client,
            )
            with pytest.raises(ResendPermanentError) as error:
                await sender.send(
                    {
                        "recipient": "founder@example.com",
                        "subject": "Review update",
                        "body": "private data",
                    },
                    message_id="launchpad-stable-outbox-id",
                )

        assert "re_provider_secret" not in str(error.value)
        assert "founder@example.com" not in str(error.value)
        assert "private data" not in str(error.value)

    asyncio.run(verify())


def test_classifies_in_progress_idempotent_request_as_transient() -> None:
    async def verify() -> None:
        def respond(_request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                409,
                json={"name": "concurrent_idempotent_requests", "message": "try later"},
            )

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
            sender = ResendEmailSender(
                api_key="re_provider_secret",
                sender="noreply@example.com",
                client=client,
            )
            with pytest.raises(ResendTransientError):
                await sender.send(
                    {
                        "recipient": "founder@example.com",
                        "subject": "Review update",
                        "body": "private data",
                    },
                    message_id="launchpad-stable-outbox-id",
                )

    asyncio.run(verify())


def test_ambiguous_outbox_retry_reuses_resend_key_and_exact_payload() -> None:
    async def verify() -> None:
        requests: list[httpx2.Request] = []

        def respond(request: httpx2.Request) -> httpx2.Response:
            requests.append(request)
            return httpx2.Response(200, json={"id": "resend-message-deduplicated"})

        codec = EmailPayloadCodec({"test": b"d" * 32}, "test")
        event = _email_event(codec)
        repository = _FailFirstCompletion(event)
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
            sender = ResendEmailSender(
                api_key="re_test_secret",
                sender="noreply@example.com",
                client=client,
            )
            first = await dispatch_due(
                cast(AsyncSession, object()),
                repository=cast(OutboxRepository, repository),
                codec=codec,
                sender=sender,
                now=datetime(2026, 10, 1, tzinfo=UTC),
            )
            second = await dispatch_due(
                cast(AsyncSession, object()),
                repository=cast(OutboxRepository, repository),
                codec=codec,
                sender=sender,
                now=datetime(2026, 10, 1, tzinfo=UTC),
            )

        assert first == 0
        assert second == 1
        assert repository.retried == [event.id]
        assert repository.completed == [event.id]
        assert len(requests) == 2
        assert (
            requests[0].headers["Idempotency-Key"]
            == requests[1].headers["Idempotency-Key"]
            == f"launchpad-{event.id}"
        )
        assert requests[0].read() == requests[1].read()


def test_rate_limit_leaves_encrypted_outbox_event_retryable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def verify() -> None:
        codec = EmailPayloadCodec({"test": b"t" * 32}, "test")
        event = _email_event(codec)
        repository = _FailFirstCompletion(event)

        def respond(_request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(429, text="private provider response")

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
            sender = ResendEmailSender(
                api_key="re_provider_secret",
                sender="noreply@example.com",
                client=client,
            )
            completed = await dispatch_due(
                cast(AsyncSession, object()),
                repository=cast(OutboxRepository, repository),
                codec=codec,
                sender=sender,
            )

        assert completed == 0
        assert repository.retried == [event.id]
        assert repository.dead_lettered == []

    asyncio.run(verify())
    for sensitive_value in (
        "re_provider_secret",
        "founder@example.com",
        "private verification link",
        "private provider response",
    ):
        assert sensitive_value not in caplog.text


def test_nonretryable_provider_response_dead_letters_event_safely(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def verify() -> None:
        codec = EmailPayloadCodec({"test": b"p" * 32}, "test")
        event = _email_event(codec)
        repository = _FailFirstCompletion(event)

        def respond(_request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(422, text="founder@example.com private feedback")

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
            sender = ResendEmailSender(
                api_key="re_provider_secret",
                sender="noreply@example.com",
                client=client,
            )
            completed = await dispatch_due(
                cast(AsyncSession, object()),
                repository=cast(OutboxRepository, repository),
                codec=codec,
                sender=sender,
            )

        assert completed == 0
        assert repository.dead_lettered == [event.id]
        assert repository.retried == []

    asyncio.run(verify())
    assert "re_provider_secret" not in caplog.text
    assert "founder@example.com" not in caplog.text
    assert "private feedback" not in caplog.text
