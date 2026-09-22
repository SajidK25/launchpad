"""SMTP transport for transactional email delivery."""

from __future__ import annotations

from email.message import EmailMessage
from typing import Any

import aiosmtplib


class EmailTransport:
    """Send one rendered transactional message through the configured SMTP server."""

    def __init__(
        self,
        *,
        hostname: str,
        port: int,
        sender: str,
        use_tls: bool,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.hostname = hostname
        self.port = port
        self.sender = sender
        self.use_tls = use_tls
        self.username = username
        self.password = password

    async def send(self, payload: dict[str, Any], *, message_id: str) -> None:
        """Render and send a payload without logging or returning its secrets."""

        recipient = payload.get("recipient")
        if not isinstance(recipient, str) or not recipient:
            raise ValueError("email recipient is invalid")
        subject = payload.get("subject", "Launchpad notification")
        body = payload.get("body", "")
        if not isinstance(subject, str) or not isinstance(body, str):
            raise ValueError("email payload is invalid")
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = recipient
        message["Subject"] = subject
        message["Message-ID"] = f"<{message_id}@launchpad.local>"
        message.set_content(body)
        await aiosmtplib.send(
            message,
            hostname=self.hostname,
            port=self.port,
            start_tls=self.use_tls,
            username=self.username,
            password=self.password,
        )
