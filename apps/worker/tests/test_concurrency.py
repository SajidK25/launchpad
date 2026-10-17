"""Bounded concurrency and session isolation for claimed event work."""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from app.shared.events.models import OutboxMessage
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, "apps/worker")

from worker import process_claimed_events


class _Session:
    pass


class _Sessions:
    def __init__(self) -> None:
        self.created: list[_Session] = []

    @asynccontextmanager
    async def begin(self):
        session = _Session()
        self.created.append(session)
        yield session


def test_event_processing_is_bounded_isolated_and_email_capped() -> None:
    async def verify() -> None:
        sessions = _Sessions()
        events = [
            cast(
                OutboxMessage,
                SimpleNamespace(
                    id=uuid4(),
                    event_type=(
                        "launch.notice_email_requested.v1"
                        if index < 10
                        else "launch.publish_requested.v1"
                    ),
                ),
            )
            for index in range(20)
        ]
        active = 0
        max_active = 0
        active_email = 0
        max_active_email = 0
        session_ids: set[int] = set()

        async def dispatch(session: AsyncSession, event: OutboxMessage) -> None:
            nonlocal active, max_active, active_email, max_active_email
            active += 1
            max_active = max(max_active, active)
            session_ids.add(id(session))
            is_email = event.event_type.endswith("email_requested.v1")
            if is_email:
                active_email += 1
                max_active_email = max(max_active_email, active_email)
            await asyncio.sleep(0.01)
            if is_email:
                active_email -= 1
            active -= 1

        await process_claimed_events(
            events,
            sessions=cast(Any, sessions),
            dispatch=dispatch,
            concurrency=6,
            email_concurrency=2,
        )

        assert max_active == 6
        assert max_active_email == 2
        assert len(session_ids) == len(events) == len(sessions.created)

    asyncio.run(verify())


def test_event_processor_rejects_unbounded_or_zero_limits() -> None:
    async def verify() -> None:
        with pytest.raises(ValueError, match="positive"):
            await process_claimed_events(
                [],
                sessions=cast(Any, _Sessions()),
                dispatch=lambda _session, _event: asyncio.sleep(0),
                concurrency=0,
                email_concurrency=1,
            )

    asyncio.run(verify())
