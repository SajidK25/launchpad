"""PostgreSQL constraints for private product review state."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from app.shared.db.database import Database, _alembic_config, migration_head
from conftest import IntegrationSettings
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection


async def _seed_review(connection: AsyncConnection) -> tuple[UUID, UUID, UUID, UUID, datetime]:
    founder_id, reviewer_id, product_id, submission_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    for account_id in (founder_id, reviewer_id):
        await connection.execute(
            text(
                "INSERT INTO accounts "
                "(id, email_display, email_key, password_hash, created_at, updated_at) "
                "VALUES (:id, :email, :email, 'hash', :now, :now)"
            ),
            {"id": account_id, "email": f"{account_id}@example.test", "now": now},
        )
    await connection.execute(
        text(
            "INSERT INTO products "
            "(id, founder_id, status, name, pitch, description, website_url, "
            "website_key, created_at, updated_at) "
            "VALUES (:id, :founder, 'submitted', 'Review', 'Review pitch', "
            "'Review description', 'https://example.test', 'example.test', :now, :now)"
        ),
        {"id": product_id, "founder": founder_id, "now": now},
    )
    await connection.execute(
        text(
            "INSERT INTO product_submissions "
            "(id, product_id, state, submitted_at, closed_at, product_version) "
            "VALUES (:id, :product, 'approved', :now, :now, 0)"
        ),
        {"id": submission_id, "product": product_id, "now": now},
    )
    return founder_id, reviewer_id, product_id, submission_id, now


_INSERT_DECISION = text(
    "INSERT INTO product_review_decisions "
    "(id, submission_id, actor_account_id, from_status, outcome, "
    "reviewed_product_version, feedback, idempotency_key, request_fingerprint, created_at) "
    "VALUES (:id, :submission, :actor, :from_status, :outcome, 0, :feedback, :key, :hash, :now)"
)


def test_upgrade_from_0007_preserves_existing_rows(
    integration_settings_fixture: IntegrationSettings, reset_database: None
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        founder_id, product_id = uuid4(), uuid4()
        now = datetime.now(UTC)
        try:
            async with database.engine.begin() as connection:

                def upgrade_previous(sync_connection: Connection) -> None:
                    config = _alembic_config()
                    config.attributes["connection"] = sync_connection
                    command.upgrade(config, "0007_product_submission_idx")

                await connection.run_sync(upgrade_previous)
                await connection.execute(
                    text(
                        "INSERT INTO accounts "
                        "(id, email_display, email_key, password_hash, created_at, updated_at) "
                        "VALUES (:id, 'prior@example.test', 'prior@example.test', "
                        "'hash', :now, :now)"
                    ),
                    {"id": founder_id, "now": now},
                )
                await connection.execute(
                    text(
                        "INSERT INTO products (id, founder_id, created_at, updated_at) "
                        "VALUES (:id, :founder, :now, :now)"
                    ),
                    {"id": product_id, "founder": founder_id, "now": now},
                )
            assert await database.current_revision() == "0007_product_submission_idx"
            await database.prepare()
            assert await database.current_revision() == migration_head()
            async with database.engine.connect() as connection:
                row = (
                    await connection.execute(
                        text("SELECT founder_id, status FROM products WHERE id = :id"),
                        {"id": product_id},
                    )
                ).one()
                tables = (
                    await connection.execute(
                        text(
                            "SELECT to_regclass('product_review_decisions'), "
                            "to_regclass('notifications')"
                        )
                    )
                ).one()
                assert row == (founder_id, "draft")
                assert tables == ("product_review_decisions", "notifications")
        finally:
            await database.close()

    asyncio.run(verify())


def test_private_review_states_and_submission_closure(
    integration_settings_fixture: IntegrationSettings, reset_database: None
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        owner_id, product_id = uuid4(), uuid4()
        now = datetime.now(UTC)
        try:
            await database.prepare()
            async with database.engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO accounts "
                        "(id, email_display, email_key, password_hash, created_at, updated_at) "
                        "VALUES (:id, 'review-owner@example.test', 'review-owner@example.test', "
                        "'hash', :now, :now)"
                    ),
                    {"id": owner_id, "now": now},
                )
                await connection.execute(
                    text(
                        "INSERT INTO products (id, founder_id, created_at, updated_at) "
                        "VALUES (:id, :owner, :now, :now)"
                    ),
                    {"id": product_id, "owner": owner_id, "now": now},
                )
                await connection.execute(
                    text("UPDATE products SET status = 'changes_requested' WHERE id = :id"),
                    {"id": product_id},
                )
            with pytest.raises(IntegrityError):
                async with database.engine.begin() as connection:
                    await connection.execute(
                        text("UPDATE products SET status = 'submitted' WHERE id = :id"),
                        {"id": product_id},
                    )
            async with database.engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE products SET name = 'Review', pitch = 'Review pitch', "
                        "description = 'Review description', "
                        "website_url = 'https://example.test', website_key = 'example.test', "
                        "status = 'approved' WHERE id = :id"
                    ),
                    {"id": product_id},
                )
                await connection.execute(
                    text("UPDATE products SET status = 'rejected' WHERE id = :id"),
                    {"id": product_id},
                )
                await connection.execute(
                    text(
                        "INSERT INTO product_submissions "
                        "(id, product_id, state, submitted_at, closed_at, product_version) "
                        "VALUES (:id, :product, 'approved', :now, :now, 0)"
                    ),
                    {"id": uuid4(), "product": product_id, "now": now},
                )
            with pytest.raises(IntegrityError):
                async with database.engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO product_submissions "
                            "(id, product_id, state, submitted_at, product_version) "
                            "VALUES (:id, :product, 'rejected', :now, 0)"
                        ),
                        {"id": uuid4(), "product": product_id, "now": now},
                    )
        finally:
            await database.close()

    asyncio.run(verify())


def test_review_decision_cardinality_feedback_and_retention(
    integration_settings_fixture: IntegrationSettings, reset_database: None
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            await database.prepare()
            async with database.engine.begin() as connection:
                _, reviewer_id, product_id, submission_id, now = await _seed_review(connection)
                await connection.execute(
                    _INSERT_DECISION,
                    {
                        "id": uuid4(),
                        "submission": submission_id,
                        "actor": reviewer_id,
                        "from_status": "submitted",
                        "outcome": "approved",
                        "feedback": None,
                        "key": "initial-approval",
                        "hash": "a" * 64,
                        "now": now,
                    },
                )
                await connection.execute(
                    _INSERT_DECISION,
                    {
                        "id": uuid4(),
                        "submission": submission_id,
                        "actor": reviewer_id,
                        "from_status": "approved",
                        "outcome": "changes_requested",
                        "feedback": "Please correct the pitch",
                        "key": "approved-return",
                        "hash": "b" * 64,
                        "now": now,
                    },
                )
            for from_status, outcome, feedback, key in (
                ("submitted", "rejected", "Reason", "duplicate-initial"),
                ("approved", "changes_requested", "Another reason", "duplicate-return"),
            ):
                with pytest.raises(IntegrityError):
                    async with database.engine.begin() as connection:
                        await connection.execute(
                            _INSERT_DECISION,
                            {
                                "id": uuid4(),
                                "submission": submission_id,
                                "actor": reviewer_id,
                                "from_status": from_status,
                                "outcome": outcome,
                                "feedback": feedback,
                                "key": key,
                                "hash": "c" * 64,
                                "now": now,
                            },
                        )
            with pytest.raises(IntegrityError):
                async with database.engine.begin() as connection:
                    await connection.execute(
                        text("DELETE FROM products WHERE id = :id"), {"id": product_id}
                    )
            async with database.engine.begin() as connection:
                bad_period_id = uuid4()
                await connection.execute(
                    text(
                        "INSERT INTO product_submissions "
                        "(id, product_id, state, submitted_at, closed_at, product_version) "
                        "VALUES (:id, :product, 'withdrawn', :now, :now, 0)"
                    ),
                    {"id": bad_period_id, "product": product_id, "now": now},
                )
            for outcome, feedback in (
                ("rejected", ""),
                ("rejected", "needs trim "),
                ("changes_requested", "x" * 2001),
                ("approved", "unexpected"),
            ):
                with pytest.raises(IntegrityError):
                    async with database.engine.begin() as connection:
                        await connection.execute(
                            _INSERT_DECISION,
                            {
                                "id": uuid4(),
                                "submission": bad_period_id,
                                "actor": reviewer_id,
                                "from_status": "submitted",
                                "outcome": outcome,
                                "feedback": feedback,
                                "key": str(uuid4()),
                                "hash": "d" * 64,
                                "now": now,
                            },
                        )
        finally:
            await database.close()

    asyncio.run(verify())


def test_notification_uniqueness_and_read_indexes(
    integration_settings_fixture: IntegrationSettings, reset_database: None
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            await database.prepare()
            async with database.engine.begin() as connection:
                founder_id, reviewer_id, product_id, submission_id, now = await _seed_review(
                    connection
                )
                decision_id = uuid4()
                await connection.execute(
                    _INSERT_DECISION,
                    {
                        "id": decision_id,
                        "submission": submission_id,
                        "actor": reviewer_id,
                        "from_status": "submitted",
                        "outcome": "approved",
                        "feedback": None,
                        "key": "notification-decision",
                        "hash": "e" * 64,
                        "now": now,
                    },
                )
                await connection.execute(
                    text(
                        "INSERT INTO notifications "
                        "(id, recipient_account_id, product_id, review_decision_id, "
                        "kind, created_at) "
                        "VALUES (:id, :recipient, :product, :decision, 'review_approved', :now)"
                    ),
                    {
                        "id": uuid4(),
                        "recipient": founder_id,
                        "product": product_id,
                        "decision": decision_id,
                        "now": now,
                    },
                )
            with pytest.raises(IntegrityError):
                async with database.engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO notifications "
                            "(id, recipient_account_id, product_id, review_decision_id, "
                            "kind, created_at) "
                            "VALUES (:id, :recipient, :product, :decision, 'review_approved', :now)"
                        ),
                        {
                            "id": uuid4(),
                            "recipient": founder_id,
                            "product": product_id,
                            "decision": decision_id,
                            "now": now,
                        },
                    )
            async with database.engine.connect() as connection:
                indexes = dict(
                    (
                        await connection.execute(
                            text(
                                "SELECT indexname, indexdef FROM pg_indexes "
                                "WHERE tablename IN ('products', 'product_submissions', "
                                "'product_review_decisions', 'notifications')"
                            )
                        )
                    ).all()
                )
                assert {
                    "ix_product_submissions_pending_queue",
                    "ix_products_approved_updated",
                    "ix_product_review_decisions_submission_created",
                    "ix_notifications_recipient_created",
                    "ix_notifications_unread_recipient",
                } <= indexes.keys()
                assert "read_at IS NULL" in indexes["ix_notifications_unread_recipient"]
        finally:
            await database.close()

    asyncio.run(verify())
