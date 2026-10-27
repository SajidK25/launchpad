"""PostgreSQL migration and ownership persistence coverage for demo seeding."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from app.operations.demo_seed.repository import DemoSeedRepository, SeedOwnershipConflict
from app.shared.db.database import _alembic_config
from sqlalchemy import Connection, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


def _upgrade(connection: Connection, revision: str) -> None:
    config = _alembic_config()
    config.attributes["connection"] = connection
    command.upgrade(config, revision)


def _downgrade(connection: Connection, revision: str) -> None:
    config = _alembic_config()
    config.attributes["connection"] = connection
    command.downgrade(config, revision)


async def _open_isolated_schema() -> tuple[AsyncEngine, str]:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("PostgreSQL integration requires DATABASE_URL.")
    schema = f"test_demo_seed_{uuid4().hex}"
    base_engine = create_async_engine(
        make_url(database_url)
        .set(drivername="postgresql+asyncpg")
        .render_as_string(hide_password=False),
        poolclass=NullPool,
    )
    try:
        async with base_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    finally:
        await base_engine.dispose()
    isolated_url = (
        make_url(database_url)
        .set(drivername="postgresql+asyncpg")
        .render_as_string(hide_password=False)
    )
    engine = create_async_engine(
        isolated_url,
        connect_args={"server_settings": {"search_path": f"{schema},public"}},
        poolclass=NullPool,
    )
    async with engine.begin() as connection:
        await connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
    return engine, schema


async def _drop_isolated_schema(schema: str) -> None:
    database_url = os.environ.get("DATABASE_URL")
    if database_url is None:
        return
    engine = create_async_engine(
        make_url(database_url)
        .set(drivername="postgresql+asyncpg")
        .render_as_string(hide_password=False),
        poolclass=NullPool,
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    finally:
        await engine.dispose()


def test_migration_preserves_domain_rows_and_refuses_downgrade_with_ownership() -> None:
    async def verify() -> None:
        engine, schema = await _open_isolated_schema()
        account_id, product_id = uuid4(), uuid4()
        now = datetime.now(UTC)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda sync: _upgrade(sync, "0016_votes_and_daily_rankings")
                )
                await connection.execute(
                    text(
                        "INSERT INTO accounts (id,email_display,email_key,password_hash,"
                        "created_at,updated_at) VALUES (:id,'demo@test.invalid',"
                        "'demo@test.invalid','hash',:now,:now)"
                    ),
                    {"id": account_id, "now": now},
                )
                await connection.execute(
                    text(
                        "INSERT INTO products (id,founder_id,status,version,name,pitch,description,"
                        "website_url,website_key,launched_at,created_at,updated_at) VALUES "
                        "(:id,:owner,'launched',0,'Demo product','Pitch','Description',"
                        "'https://demo.invalid','demo.invalid',:now,:now,:now)"
                    ),
                    {"id": product_id, "owner": account_id, "now": now},
                )
                await connection.run_sync(lambda sync: _upgrade(sync, "head"))
                unchanged = (
                    await connection.execute(
                        text(
                            "SELECT a.id,p.id,p.name,p.status FROM accounts a JOIN products p "
                            "ON p.founder_id=a.id WHERE a.id=:account AND p.id=:product"
                        ),
                        {"account": account_id, "product": product_id},
                    )
                ).one()
                assert unchanged == (account_id, product_id, "Demo product", "launched")
                await connection.execute(
                    text(
                        "INSERT INTO demo_seed_datasets "
                        "(target_id,dataset_version,anchor_utc_date,created_at,updated_at) "
                        "VALUES ('ledger-test','v1','2026-10-26',:now,:now)"
                    ),
                    {"now": now},
                )
                with pytest.raises(RuntimeError, match="Downgrade refused"):
                    await connection.run_sync(
                        lambda sync: _downgrade(sync, "0016_votes_and_daily_rankings")
                    )
                assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                    "0017_demo_seed_ownership"
                )
            async with engine.begin() as connection:
                assert (
                    await connection.scalar(
                        text(
                            "SELECT count(*) FROM demo_seed_datasets WHERE target_id='ledger-test'"
                        )
                    )
                    == 1
                )
                await connection.execute(text("DELETE FROM demo_seed_datasets"))
                await connection.run_sync(
                    lambda sync: _downgrade(sync, "0016_votes_and_daily_rankings")
                )
                assert (
                    await connection.scalar(
                        text("SELECT to_regclass(:table_name)"),
                        {"table_name": f"{schema}.demo_seed_datasets"},
                    )
                    is None
                )
        finally:
            await engine.dispose()
            await _drop_isolated_schema(schema)

    asyncio.run(verify())


def test_fresh_database_migrates_to_head_with_usable_ledger_tables() -> None:
    async def verify() -> None:
        engine, schema = await _open_isolated_schema()
        try:
            async with engine.begin() as connection:
                await connection.run_sync(lambda sync: _upgrade(sync, "head"))
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
                tables = set(
                    (
                        await connection.scalars(
                            text("SELECT tablename FROM pg_tables WHERE schemaname=:schema"),
                            {"schema": schema},
                        )
                    ).all()
                )
                assert revision == "0017_demo_seed_ownership"
                assert {"demo_seed_datasets", "demo_seed_artifacts"} <= tables
        finally:
            await engine.dispose()
            await _drop_isolated_schema(schema)

    asyncio.run(verify())


def test_dataset_anchor_artifact_target_uniqueness_and_locking() -> None:
    async def verify() -> None:
        engine, schema = await _open_isolated_schema()
        repository = DemoSeedRepository()
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(UTC)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(lambda sync: _upgrade(sync, "head"))
            async with engine.connect() as connection:
                assert await connection.scalar(text("SELECT current_schema()")) == schema
                assert (
                    await connection.scalar(text("SELECT to_regclass('demo_seed_datasets')"))
                    is not None
                )
            async with sessions() as first, sessions() as second:
                first_transaction = await first.begin()
                await second.begin()
                await repository.lock_target(first, target_id="target-a")
                blocked = asyncio.create_task(repository.lock_target(second, target_id="target-a"))
                await asyncio.sleep(0.1)
                assert not blocked.done()
                await first_transaction.rollback()
                await asyncio.wait_for(blocked, timeout=2)
                await second.rollback()

            async with sessions.begin() as session:
                dataset = await repository.get_or_create_dataset(
                    session,
                    target_id="target-a",
                    dataset_version="v1",
                    anchor_utc_date=date(2026, 10, 26),
                    now=now,
                )
                assert dataset.anchor_utc_date == date(2026, 10, 26)
                artifact_id = uuid4()
                await repository.record_artifact(
                    session,
                    target_id="target-a",
                    seed_key="founder-01",
                    artifact_kind="account",
                    entity_id=artifact_id,
                    now=now,
                )
            async with sessions.begin() as session:
                again = await repository.get_or_create_dataset(
                    session,
                    target_id="target-a",
                    dataset_version="v1",
                    anchor_utc_date=date(2026, 10, 27),
                    now=now + timedelta(days=1),
                )
                assert again.anchor_utc_date == date(2026, 10, 26)
                await repository.get_or_create_dataset(
                    session,
                    target_id="target-b",
                    dataset_version="v1",
                    anchor_utc_date=date(2026, 10, 27),
                    now=now,
                )
                await repository.record_artifact(
                    session,
                    target_id="target-b",
                    seed_key="founder-01",
                    artifact_kind="account",
                    entity_id=uuid4(),
                    now=now,
                )
                with pytest.raises(SeedOwnershipConflict):
                    await repository.record_artifact(
                        session,
                        target_id="target-a",
                        seed_key="founder-01",
                        artifact_kind="account",
                        entity_id=uuid4(),
                        now=now,
                    )
                with pytest.raises(IntegrityError):
                    async with session.begin_nested():
                        await session.execute(
                            text(
                                "INSERT INTO demo_seed_artifacts "
                                "(id,target_id,seed_key,artifact_kind,entity_id,created_at) "
                                "VALUES (:id,'target-a','founder-01','account',:entity,:now)"
                            ),
                            {"id": uuid4(), "entity": uuid4(), "now": now},
                        )
        finally:
            await engine.dispose()
            await _drop_isolated_schema(schema)

    asyncio.run(verify())
