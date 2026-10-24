"""Real PostgreSQL migration coverage for voting persistence."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from app.shared.db.database import Database, _alembic_config
from conftest import IntegrationSettings
from sqlalchemy import Connection, text


def _upgrade(sync_connection: Connection, revision: str) -> None:
    config = _alembic_config()
    config.attributes["connection"] = sync_connection
    command.upgrade(config, revision)


def test_vote_migration_preserves_existing_account_and_product_rows_and_guards_downgrade(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        account_id, product_id = uuid4(), uuid4()
        now = datetime.now(UTC)
        try:
            async with database.engine.begin() as connection:
                await connection.run_sync(lambda sync: _upgrade(sync, "0015_public_catalog_search"))
                await connection.execute(
                    text(
                        "INSERT INTO accounts "
                        "(id, email_display, email_key, password_hash, created_at, updated_at) "
                        "VALUES (:id, 'vote-schema@example.test', 'vote-schema@example.test', "
                        "'hash', :now, :now)"
                    ),
                    {"id": account_id, "now": now},
                )
                await connection.execute(
                    text(
                        "INSERT INTO products "
                        "(id, founder_id, status, version, name, pitch, description, website_url, "
                        "website_key, launched_at, created_at, updated_at) "
                        "VALUES (:id, :founder, 'launched', 2, 'Vote schema item', 'Pitch', "
                        "'Description', 'https://vote-schema.example.test', "
                        "'vote-schema.example.test', :now, :now, :now)"
                    ),
                    {"id": product_id, "founder": account_id, "now": now},
                )

            async with database.engine.begin() as connection:
                await connection.run_sync(lambda sync: _upgrade(sync, "head"))
                existing_rows = (
                    await connection.execute(
                        text(
                            "SELECT a.id AS account_id, p.id AS product_id, p.name, p.status "
                            "FROM accounts a JOIN products p ON p.founder_id = a.id "
                            "WHERE a.id = :account_id AND p.id = :product_id"
                        ),
                        {"account_id": account_id, "product_id": product_id},
                    )
                ).one()
                vote_tables = set(
                    (
                        await connection.scalars(
                            text(
                                "SELECT tablename FROM pg_tables "
                                "WHERE schemaname = current_schema() AND ("
                                "tablename LIKE '%vote%' OR tablename LIKE 'daily_ranking_%' "
                                "OR tablename = 'voting_feature_state')"
                            )
                        )
                    ).all()
                )
                assert existing_rows == (account_id, product_id, "Vote schema item", "launched")
                assert {
                    "votes",
                    "vote_idempotency_receipts",
                    "vote_risk_flags",
                    "vote_review_decisions",
                    "daily_ranking_snapshots",
                    "daily_ranking_entries",
                    "voting_feature_state",
                } <= vote_tables

                await connection.execute(
                    text(
                        "INSERT INTO votes (id, member_id, product_id, cast_at, state) "
                        "VALUES (:id, :member, :product, :now, 'active')"
                    ),
                    {"id": uuid4(), "member": account_id, "product": product_id, "now": now},
                )

                with pytest.raises(RuntimeError, match="Downgrade refused"):
                    await connection.run_sync(lambda sync: _downgrade_to_previous(sync))
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
                assert revision == "0016_votes_and_daily_rankings"
        finally:
            await database.close()

    asyncio.run(verify())


def _downgrade_to_previous(sync_connection: Connection) -> None:
    config = _alembic_config()
    config.attributes["connection"] = sync_connection
    command.downgrade(config, "0015_public_catalog_search")


def test_fresh_database_migrates_to_vote_schema_head(
    integration_settings_fixture: IntegrationSettings,
    reset_database: None,
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            async with database.engine.begin() as connection:
                await connection.run_sync(lambda sync: _upgrade(sync, "head"))
                tables = set(
                    (
                        await connection.scalars(
                            text(
                                "SELECT tablename FROM pg_tables "
                                "WHERE schemaname = current_schema()"
                            )
                        )
                    ).all()
                )
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
                assert revision == "0016_votes_and_daily_rankings"
                assert {
                    "votes",
                    "vote_idempotency_receipts",
                    "vote_risk_flags",
                    "vote_review_decisions",
                    "daily_ranking_snapshots",
                    "daily_ranking_entries",
                    "voting_feature_state",
                } <= tables
        finally:
            await database.close()

    asyncio.run(verify())
