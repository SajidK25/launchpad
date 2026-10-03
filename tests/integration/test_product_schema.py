"""PostgreSQL verification for the additive private-product schema."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from app.shared.db.database import (
    Database,
    MigrationCompatibilityError,
    _alembic_config,
    migration_head,
)
from conftest import IntegrationSettings
from sqlalchemy import Connection, inspect, text
from sqlalchemy.exc import IntegrityError


def test_upgrade_preserves_identity_and_requires_exact_head(
    integration_settings_fixture: IntegrationSettings, reset_database: None
) -> None:
    """A 0004 database is incompatible until upgraded; identity data survives."""

    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        account_id = uuid4()
        now = datetime.now(UTC)
        try:
            async with database.engine.begin() as connection:

                def upgrade_old(sync_connection: Connection) -> None:
                    config = _alembic_config()
                    config.attributes["connection"] = sync_connection
                    command.upgrade(config, "0004_profile_link_query")

                await connection.run_sync(upgrade_old)
                await connection.execute(
                    text(
                        "INSERT INTO accounts "
                        "(id, email_display, email_key, password_hash, created_at, updated_at) "
                        "VALUES (:id, 'old@example.test', 'old@example.test', 'hash', :now, :now)"
                    ),
                    {"id": account_id, "now": now},
                )
                await connection.execute(
                    text("INSERT INTO profiles (account_id) VALUES (:id)"), {"id": account_id}
                )
            assert await database.current_revision() == "0004_profile_link_query"
            with pytest.raises(MigrationCompatibilityError):
                await database.ensure_compatible()
            await database.prepare()
            assert await database.current_revision() == migration_head()
            async with database.engine.connect() as connection:
                row = (
                    await connection.execute(
                        text(
                            "SELECT a.role, a.suspended_at, p.visibility FROM accounts a "
                            "JOIN profiles p ON p.account_id = a.id WHERE a.id = :id"
                        ),
                        {"id": account_id},
                    )
                ).one()
                assert row == ("member", None, "private")
        finally:
            await database.close()

    asyncio.run(verify())


def test_submission_history_and_topic_asset_constraints(
    integration_settings_fixture: IntegrationSettings, reset_database: None
) -> None:
    """Database rejects duplicate active periods and malformed private records."""

    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        account_id, product_id, topic_id = uuid4(), uuid4(), uuid4()
        now = datetime.now(UTC)
        try:
            await database.prepare()
            async with database.engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO accounts "
                        "(id, email_display, email_key, password_hash, created_at, updated_at) "
                        "VALUES (:id, 'new@example.test', 'new@example.test', 'hash', :now, :now)"
                    ),
                    {"id": account_id, "now": now},
                )
                await connection.execute(
                    text(
                        "INSERT INTO products (id, founder_id, created_at, updated_at) "
                        "VALUES (:id, :founder, :now, :now)"
                    ),
                    {"id": product_id, "founder": account_id, "now": now},
                )
                await connection.execute(
                    text(
                        "INSERT INTO product_submissions "
                        "(id, product_id, state, submitted_at, product_version) "
                        "VALUES (:id, :product, 'pending', :now, 0)"
                    ),
                    {"id": uuid4(), "product": product_id, "now": now},
                )
                await connection.execute(
                    text(
                        "INSERT INTO product_submissions "
                        "(id, product_id, state, submitted_at, closed_at, product_version) "
                        "VALUES (:id, :product, 'withdrawn', :now, :now, 0)"
                    ),
                    {"id": uuid4(), "product": product_id, "now": now},
                )
                await connection.execute(
                    text(
                        "INSERT INTO topics (id, display_name, name_key) "
                        "VALUES (:id, 'Design', 'design')"
                    ),
                    {"id": topic_id},
                )
            with pytest.raises(IntegrityError):
                async with database.engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO product_submissions "
                            "(id, product_id, state, submitted_at, product_version) "
                            "VALUES (:id, :product, 'pending', :now, 0)"
                        ),
                        {"id": uuid4(), "product": product_id, "now": now},
                    )
            with pytest.raises(IntegrityError):
                async with database.engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO topics (id, display_name, name_key) "
                            "VALUES (:id, 'DESIGN', 'design')"
                        ),
                        {"id": uuid4()},
                    )
            for kind, media_type, byte_count, position in (
                ("logo", "image/png", 5242881, None),
                ("logo", "image/svg+xml", 100, None),
                ("screenshot", "image/png", 100, 11),
            ):
                with pytest.raises(IntegrityError):
                    async with database.engine.begin() as connection:
                        await connection.execute(
                            text(
                                "INSERT INTO product_assets "
                                "(id, product_id, kind, state, staging_key, media_type, "
                                "byte_count, position) VALUES "
                                "(:id, :product, :kind, 'pending', :key, :media, :size, :position)"
                            ),
                            {
                                "id": uuid4(),
                                "product": product_id,
                                "kind": kind,
                                "key": str(uuid4()),
                                "media": media_type,
                                "size": byte_count,
                                "position": position,
                            },
                        )
            with pytest.raises(IntegrityError):
                async with database.engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO product_topics "
                            "(product_id, topic_id, position, selected_label) "
                            "VALUES (:product, :topic, 4, 'Design')"
                        ),
                        {"product": product_id, "topic": topic_id},
                    )
            for selected_label in ("", " Design", "x" * 41):
                with pytest.raises(IntegrityError):
                    async with database.engine.begin() as connection:
                        await connection.execute(
                            text(
                                "INSERT INTO product_topics "
                                "(product_id, topic_id, position, selected_label) "
                                "VALUES (:product, :topic, 1, :label)"
                            ),
                            {"product": product_id, "topic": topic_id, "label": selected_label},
                        )
            with pytest.raises(IntegrityError):
                async with database.engine.begin() as connection:
                    await connection.execute(
                        text("UPDATE products SET name = :name WHERE id = :id"),
                        {"name": "x" * 81, "id": product_id},
                    )
            async with database.engine.connect() as connection:
                indexes = await connection.run_sync(
                    lambda sync: {
                        table: {index["name"] for index in inspect(sync).get_indexes(table)}
                        for table in ("products", "product_submissions", "topics", "product_assets")
                    }
                )
                assert {"ix_products_founder_status_updated", "ix_products_website_key"} <= indexes[
                    "products"
                ]
                assert {
                    "uq_product_submissions_pending_product",
                    "ix_product_submissions_pending_queue",
                    "ix_product_submissions_product_id",
                } <= indexes["product_submissions"]
                assert "uq_topics_name_key" in indexes["topics"]
                assert "ix_product_assets_pending_expiry" in indexes["product_assets"]
        finally:
            await database.close()

    asyncio.run(verify())


def test_selected_topic_labels_backfill_from_private_normalized_keys(
    integration_settings_fixture: IntegrationSettings, reset_database: None
) -> None:
    """Legacy shared topics must not copy the first founder's private display casing."""

    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        founder_ids = (uuid4(), uuid4())
        product_ids = (uuid4(), uuid4())
        topic_id = uuid4()
        now = datetime.now(UTC)
        try:
            async with database.engine.begin() as connection:

                def upgrade_legacy(sync_connection: Connection) -> None:
                    config = _alembic_config()
                    config.attributes["connection"] = sync_connection
                    command.upgrade(config, "0005_product_drafts_submission")

                await connection.run_sync(upgrade_legacy)
                for founder_id, product_id in zip(founder_ids, product_ids, strict=True):
                    await connection.execute(
                        text(
                            "INSERT INTO accounts "
                            "(id, email_display, email_key, password_hash, created_at, updated_at) "
                            "VALUES (:id, :email, :email, 'hash', :now, :now)"
                        ),
                        {"id": founder_id, "email": f"{founder_id}@example.com", "now": now},
                    )
                    await connection.execute(
                        text(
                            "INSERT INTO products (id, founder_id, created_at, updated_at) "
                            "VALUES (:id, :founder, :now, :now)"
                        ),
                        {"id": product_id, "founder": founder_id, "now": now},
                    )
                await connection.execute(
                    text(
                        "INSERT INTO topics (id, display_name, name_key) "
                        "VALUES (:id, 'AI Tools', 'ai tools')"
                    ),
                    {"id": topic_id},
                )
                for product_id in product_ids:
                    await connection.execute(
                        text(
                            "INSERT INTO product_topics (product_id, topic_id, position) "
                            "VALUES (:product, :topic, 1)"
                        ),
                        {"product": product_id, "topic": topic_id},
                    )
            assert await database.current_revision() == "0005_product_drafts_submission"
            await database.prepare()
            assert await database.current_revision() == "0007_product_submission_idx"
            async with database.engine.connect() as connection:
                rows = (
                    await connection.execute(
                        text(
                            "SELECT product_id, topic_id, position, selected_label "
                            "FROM product_topics ORDER BY product_id"
                        )
                    )
                ).all()
            assert len(rows) == 2
            assert {row.product_id for row in rows} == set(product_ids)
            assert all(
                row.topic_id == topic_id and row.position == 1 and row.selected_label == "ai tools"
                for row in rows
            )
        finally:
            await database.close()

    asyncio.run(verify())
