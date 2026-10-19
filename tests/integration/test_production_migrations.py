"""Production migration command checks using the disposable integration database."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from app.migrate import main, migrate
from app.shared.db.database import (
    Database,
    DatabasePreparationError,
    _alembic_config,
    migration_head,
)
from conftest import IntegrationSettings
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError


def _production_database_env(monkeypatch: pytest.MonkeyPatch, database_url: str) -> None:
    monkeypatch.setenv("LAUNCHPAD_ENVIRONMENT", "production")
    monkeypatch.setenv("LAUNCHPAD_DATABASE_URL", database_url)
    for name in (
        "LAUNCHPAD_STORAGE_PROVIDER",
        "LAUNCHPAD_STORAGE_REGION",
        "LAUNCHPAD_STORAGE_ENDPOINT_URL",
        "LAUNCHPAD_STORAGE_ACCESS_KEY_ID",
        "LAUNCHPAD_STORAGE_SECRET_ACCESS_KEY",
        "LAUNCHPAD_BOOTSTRAP_STORAGE_ACCESS_KEY_ID",
        "LAUNCHPAD_BOOTSTRAP_STORAGE_SECRET_ACCESS_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_production_migration_needs_only_database_configuration(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _production_database_env(monkeypatch, integration_settings_fixture.database_url)

    asyncio.run(migrate())

    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            assert await database.current_revision() == migration_head()
        finally:
            await database.close()

    asyncio.run(verify())


def test_concurrent_production_migrations_share_the_database_lock(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _production_database_env(monkeypatch, integration_settings_fixture.database_url)

    async def run() -> None:
        await asyncio.gather(migrate(), migrate())

    asyncio.run(run())

    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            assert await database.current_revision() == migration_head()
        finally:
            await database.close()

    asyncio.run(verify())


def test_launch_migration_preserves_review_notice_and_allows_only_scheduled_changes(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        founder_id, product_id, submission_id, decision_id = (uuid4() for _ in range(4))
        now = datetime.now(UTC)
        try:
            async with database.engine.begin() as connection:

                def upgrade_to_previous(sync_connection: Connection) -> None:
                    config = _alembic_config()
                    config.attributes["connection"] = sync_connection
                    command.upgrade(config, "0011_profile_upload_declarations")

                await connection.run_sync(upgrade_to_previous)
                await connection.execute(
                    text(
                        "INSERT INTO accounts "
                        "(id, email_display, email_key, password_hash, created_at, updated_at) "
                        "VALUES (:id, 'launch-migration@example.test', "
                        "'launch-migration@example.test', 'hash', :now, :now)"
                    ),
                    {"id": founder_id, "now": now},
                )
                await connection.execute(
                    text(
                        "INSERT INTO products "
                        "(id, founder_id, status, name, pitch, description, website_url, "
                        "website_key, created_at, updated_at) "
                        "VALUES (:id, :founder, 'approved', 'Launch', 'Launch pitch', "
                        "'Launch description', 'https://example.test', 'example.test', :now, :now)"
                    ),
                    {"id": product_id, "founder": founder_id, "now": now},
                )
                await connection.execute(
                    text(
                        "INSERT INTO product_submissions "
                        "(id, product_id, state, submitted_at, closed_at, product_version) "
                        "VALUES (:id, :product, 'approved', :now, :now, 1)"
                    ),
                    {"id": submission_id, "product": product_id, "now": now},
                )
                await connection.execute(
                    text(
                        "INSERT INTO product_review_decisions "
                        "(id, submission_id, actor_account_id, from_status, outcome, "
                        "reviewed_product_version, idempotency_key, "
                        "request_fingerprint, created_at) "
                        "VALUES (:id, :submission, :actor, 'submitted', 'approved', 1, "
                        "'prior-review-key', :fingerprint, :now)"
                    ),
                    {
                        "id": decision_id,
                        "submission": submission_id,
                        "actor": founder_id,
                        "fingerprint": "a" * 64,
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

            await database.prepare()
            assert await database.current_revision() == "0013_launch_history_index"
            async with database.engine.begin() as connection:
                history_index = await connection.scalar(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = current_schema() "
                        "AND tablename = 'launch_bookings' "
                        "AND indexname = 'ix_launch_bookings_founder_created'"
                    )
                )
                assert history_index == "ix_launch_bookings_founder_created"
                old_notice = (
                    await connection.execute(
                        text(
                            "SELECT review_decision_id, launch_booking_id, kind FROM notifications "
                            "WHERE review_decision_id = :decision"
                        ),
                        {"decision": decision_id},
                    )
                ).one()
                assert old_notice == (decision_id, None, "review_approved")

                preference = (
                    await connection.execute(
                        text(
                            "INSERT INTO launch_notification_preferences (account_id, updated_at) "
                            "VALUES (:account, :now) RETURNING reminder_email, reminder_in_site, "
                            "live_email, live_in_site, failure_email, failure_in_site"
                        ),
                        {"account": founder_id, "now": now},
                    )
                ).one()
                assert preference == (True, True, True, True, True, True)

                scheduled_submission = uuid4()
                await connection.execute(
                    text(
                        "INSERT INTO product_submissions "
                        "(id, product_id, state, submitted_at, closed_at, product_version) "
                        "VALUES (:id, :product, 'approved', :now, :now, 2)"
                    ),
                    {"id": scheduled_submission, "product": product_id, "now": now},
                )
                await connection.execute(
                    text(
                        "INSERT INTO product_review_decisions "
                        "(id, submission_id, actor_account_id, from_status, outcome, "
                        "reviewed_product_version, feedback, idempotency_key, "
                        "request_fingerprint, created_at) "
                        "VALUES (:id, :submission, :actor, 'scheduled', 'changes_requested', "
                        "2, 'Please update this', 'scheduled-change-key', :fingerprint, :now)"
                    ),
                    {
                        "id": uuid4(),
                        "submission": scheduled_submission,
                        "actor": founder_id,
                        "fingerprint": "b" * 64,
                        "now": now,
                    },
                )

            invalid_submission = uuid4()
            async with database.engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO product_submissions "
                        "(id, product_id, state, submitted_at, closed_at, product_version) "
                        "VALUES (:id, :product, 'approved', :now, :now, 2)"
                    ),
                    {"id": invalid_submission, "product": product_id, "now": now},
                )
            with pytest.raises(IntegrityError):
                async with database.engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO product_review_decisions "
                            "(id, submission_id, actor_account_id, from_status, outcome, "
                            "reviewed_product_version, feedback, idempotency_key, "
                            "request_fingerprint, created_at) "
                            "VALUES (:id, :submission, :actor, 'scheduled', 'rejected', "
                            "2, 'Not allowed', 'scheduled-reject-key', :fingerprint, :now)"
                        ),
                        {
                            "id": uuid4(),
                            "submission": invalid_submission,
                            "actor": founder_id,
                            "fingerprint": "c" * 64,
                            "now": now,
                        },
                    )
        finally:
            await database.close()

    asyncio.run(verify())


def test_migration_failure_exits_nonzero_without_storage_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _production_database_env(monkeypatch, "postgresql://test:test@localhost/test")

    class FailingDatabase:
        async def prepare(self) -> None:
            raise DatabasePreparationError("database migration failed")

        async def close(self) -> None:
            return None

    monkeypatch.setattr(Database, "connect", lambda _: FailingDatabase())

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 1
    assert capsys.readouterr().err == "Production migration failed: database migration failed\n"
