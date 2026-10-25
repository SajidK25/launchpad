"""PostgreSQL repository checks for vote history and command receipts."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from app.modules.votes.repository import VoteRepository
from app.shared.db.database import Database, _alembic_config
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker


def _upgrade(sync_connection: Connection) -> None:
    config = _alembic_config()
    config.attributes["connection"] = sync_connection
    command.upgrade(config, "head")


def test_repository_persists_votes_and_database_rejects_duplicate_active_vote_and_receipt(
    integration_settings_fixture: Any,
    reset_database: None,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        member_id, owner_id, product_id = uuid4(), uuid4(), uuid4()
        now = datetime.now(UTC)
        try:
            async with database.engine.begin() as connection:
                await connection.run_sync(_upgrade)
                for account_id, email in ((member_id, "voter"), (owner_id, "owner")):
                    await connection.execute(
                        text(
                            "INSERT INTO accounts "
                            "(id,email_display,email_key,password_hash,verified_at,role,"
                            "created_at,updated_at) "
                            "VALUES (:id,:email,:email,'hash',:now,'member',:now,:now)"
                        ),
                        {"id": account_id, "email": f"{email}@vote.test", "now": now},
                    )
                await connection.execute(
                    text(
                        "INSERT INTO products (id,founder_id,status,version,name,pitch,description,"
                        "website_url,website_key,launched_at,created_at,updated_at) "
                        "VALUES (:id,:owner,'launched',0,'Vote target','Pitch','Description',"
                        "'https://vote.test','vote.test',:now,:now,:now)"
                    ),
                    {"id": product_id, "owner": owner_id, "now": now},
                )

            session_factory = async_sessionmaker(database.engine, expire_on_commit=False)
            repository = VoteRepository()
            async with session_factory() as session:
                async with session.begin():
                    vote = await repository.create_vote(
                        session, member_id=member_id, product_id=product_id, cast_at=now
                    )
                    assert (
                        await repository.active_vote(
                            session, member_id=member_id, product_id=product_id
                        )
                        == vote
                    )
                    with pytest.raises(IntegrityError):
                        async with session.begin_nested():
                            await repository.create_vote(
                                session, member_id=member_id, product_id=product_id, cast_at=now
                            )
                    await repository.add_receipt(
                        session,
                        member_id=member_id,
                        idempotency_key="repo-key",
                        request_fingerprint="a" * 64,
                        command="cast",
                        vote_id=vote.id,
                        outcome="active",
                        now=now,
                    )
                    with pytest.raises(IntegrityError):
                        async with session.begin_nested():
                            await repository.add_receipt(
                                session,
                                member_id=member_id,
                                idempotency_key="repo-key",
                                request_fingerprint="a" * 64,
                                command="cast",
                                vote_id=vote.id,
                                outcome="active",
                                now=now,
                            )
        finally:
            await database.close()

    asyncio.run(verify())
