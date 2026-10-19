"""PostgreSQL persistence for independent launch notice preferences."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.auth.models import Account
from app.modules.notifications.service import NotificationService
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec


def _service() -> NotificationService:
    return NotificationService(
        payload_codec=EmailPayloadCodec({"preferences-test": b"p" * 32}, "preferences-test")
    )


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_preferences_default_on_persist_independently_and_leave_inbox_unchanged() -> None:
    async def verify() -> None:
        database = Database.connect(os.environ["DATABASE_URL"])
        account_id = uuid4()
        now = datetime(2026, 10, 17, 12, tzinfo=UTC)
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                session.add(
                    Account(
                        id=account_id,
                        email_display=f"{account_id}@example.test",
                        email_key=f"{account_id}@example.test",
                        password_hash="integration-only-placeholder",
                        verified_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )

            service = _service()
            async with sessions() as session, session.begin():
                defaults = await service.launch_preferences(session, actor_id=account_id)
                assert defaults == {
                    "reminder_email": True,
                    "reminder_in_site": True,
                    "live_email": True,
                    "live_in_site": True,
                    "failure_email": True,
                    "failure_in_site": True,
                }

            first = {
                "reminder_email": False,
                "reminder_in_site": True,
                "live_email": True,
                "live_in_site": False,
                "failure_email": False,
                "failure_in_site": True,
            }
            async with sessions() as session, session.begin():
                inbox_before = await service.inbox(session, actor_id=account_id)
            async with sessions() as session, session.begin():
                saved = await service.update_launch_preferences(
                    session, actor_id=account_id, values=first
                )
                assert saved == first
            async with sessions() as session, session.begin():
                reloaded = await service.launch_preferences(session, actor_id=account_id)
                assert reloaded == first
                changed = await service.update_launch_preferences(
                    session,
                    actor_id=account_id,
                    values={"live_email": False},
                )
                assert changed == {**first, "live_email": False}
                assert await service.inbox(session, actor_id=account_id) == inbox_before
        finally:
            async with database.engine.begin() as connection:
                from sqlalchemy import text

                await connection.execute(
                    text("DELETE FROM launch_notification_preferences WHERE account_id = :id"),
                    {"id": account_id},
                )
                await connection.execute(
                    text("DELETE FROM accounts WHERE id = :id"), {"id": account_id}
                )
            await database.close()

    asyncio.run(verify())
