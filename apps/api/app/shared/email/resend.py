"""Async Resend API transport for production transactional email."""

from __future__ import annotations

import httpx2

from app.shared.events.outbox import PermanentEventError

RESEND_EMAILS_URL = "https://api.resend.com/emails"
_REQUEST_TIMEOUT_SECONDS = 10.0


class ResendEmailSender:
    """Send plain-text transactional messages through Resend."""

    def __init__(
        self,
        *,
        api_key: str,
        sender: str,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.sender = sender
        self._owns_client = client is None
        self.client = client or httpx2.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS)

    async def send(self, payload: dict[str, object], *, message_id: str) -> None:
        """Send one message, using the stable outbox identity for provider deduplication."""

        recipient = payload.get("recipient")
        subject = payload.get("subject")
        body = payload.get("body")
        if (
            not isinstance(recipient, str)
            or not isinstance(subject, str)
            or not isinstance(body, str)
        ):
            raise ResendPermanentError("email payload is invalid")
        try:
            response = await self.client.post(
                RESEND_EMAILS_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Idempotency-Key": message_id,
                },
                json={"from": self.sender, "to": [recipient], "subject": subject, "text": body},
            )
        except httpx2.RequestError:
            raise ResendTransientError("Resend request failed") from None
        if response.status_code in {408, 425, 429} or response.status_code >= 500:
            raise ResendTransientError("Resend returned a transient response")
        if response.status_code == 409 and _provider_error_code(response) == (
            "concurrent_idempotent_requests"
        ):
            raise ResendTransientError("Resend is processing this idempotent request")
        if not response.is_success:
            raise ResendPermanentError("Resend rejected the email request")

    async def aclose(self) -> None:
        """Close the internally created HTTP connection pool when the worker stops."""

        if self._owns_client:
            await self.client.aclose()


class ResendPermanentError(PermanentEventError):
    """A nonretryable provider response that should be dead-lettered safely."""


class ResendTransientError(RuntimeError):
    """A provider or network failure that should be retried by the outbox."""


def _provider_error_code(response: httpx2.Response) -> str | None:
    try:
        body: object = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    nested = body.get("error")
    if isinstance(nested, dict):
        body = nested
    if not isinstance(body, dict):
        return None
    for field in ("name", "code"):
        value = body.get(field)
        if isinstance(value, str):
            return value
    return None
