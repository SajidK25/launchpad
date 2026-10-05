"""Worker email transport selection tests."""

from __future__ import annotations

import asyncio
import sys
from email.message import EmailMessage

import pytest
from app.shared.config.settings import Settings, load_settings
from app.shared.email.resend import ResendEmailSender
from app.shared.email.transport import EmailTransport

sys.path.insert(0, "apps/worker")

from worker import create_email_sender


def _settings(environment: str) -> Settings:
    values = {
        "LAUNCHPAD_ENVIRONMENT": environment,
        "LAUNCHPAD_STORAGE_ACCESS_KEY_ID": "worker-runtime-user",
        "LAUNCHPAD_STORAGE_SECRET_ACCESS_KEY": "worker-runtime-password",
        "LAUNCHPAD_MAIL_WEB_ORIGIN": (
            "https://launchpad.example" if environment == "production" else "http://web:8080"
        ),
        "LAUNCHPAD_MAIL_SENDER": "noreply@launchpad.example",
        "LAUNCHPAD_OUTBOX_KEY_ID": "worker-test-v1",
        "LAUNCHPAD_OUTBOX_KEY": "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=",
        "LAUNCHPAD_PUBLIC_UPLOAD_ENDPOINT_URL": (
            "https://uploads.example" if environment == "production" else "http://minio:9000"
        ),
        "LAUNCHPAD_TRUSTED_WEB_ORIGINS": (
            "https://launchpad.example" if environment == "production" else "http://web:8080"
        ),
        "LAUNCHPAD_RESEND_API_KEY": "re_test_key",
    }
    return load_settings(values, require_worker_mail=True)


def test_worker_selects_resend_only_in_production() -> None:
    production = create_email_sender(_settings("production"))
    assert isinstance(production, ResendEmailSender)
    assert production.sender == "noreply@launchpad.example"
    assert production.api_key == "re_test_key"

    local = create_email_sender(_settings("development"))
    check = create_email_sender(_settings("check"))
    assert isinstance(local, EmailTransport)
    assert isinstance(check, EmailTransport)
    assert local.hostname == check.hostname == "mailpit"

    async def close() -> None:
        await production.aclose()

    asyncio.run(close())


def test_check_worker_keeps_existing_auth_email_content(monkeypatch: pytest.MonkeyPatch) -> None:
    sender = create_email_sender(_settings("check"))
    assert isinstance(sender, EmailTransport)
    sent: list[tuple[EmailMessage, dict[str, object]]] = []

    async def capture(message: EmailMessage, **options: object) -> None:
        sent.append((message, options))

    monkeypatch.setattr("app.shared.email.transport.aiosmtplib.send", capture)
    body = "Use this one-time link: https://launchpad.example/verify?token=secret-value"
    asyncio.run(
        sender.send(
            {"recipient": "founder@example.com", "subject": "Verify your email", "body": body},
            message_id="launchpad-auth-event",
        )
    )

    assert len(sent) == 1
    message, options = sent[0]
    assert message["To"] == "founder@example.com"
    assert message["Subject"] == "Verify your email"
    assert message.get_content().strip() == body
    assert message["Message-ID"] == "<launchpad-auth-event@launchpad.local>"
    assert options["hostname"] == "mailpit"
