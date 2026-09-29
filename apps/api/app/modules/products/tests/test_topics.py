"""Canonical topic and website key behavior."""

import asyncio
import os
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from app.modules.products.models import Product, Topic
from app.modules.products.repository import TopicRepository, TopicResolution
from app.modules.products.service import (
    ProductValidationError,
    canonical_topic_key,
    canonical_website_key,
    validate_topic_names,
)
from app.shared.db.database import Database
from sqlalchemy import Table, delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker


def test_topic_names_reuse_case_and_surrounding_space_variants() -> None:
    first = validate_topic_names(["AI Tools"])[0]
    second = validate_topic_names([" ai tools "])[0]

    assert first.name_key == second.name_key == canonical_topic_key("AI Tools")
    assert first.display_name == "AI Tools"
    assert second.display_name == "ai tools"


@pytest.mark.parametrize("names", [[], ["  "], ["x" * 41], ["AI", " ai "]])
def test_rejects_invalid_or_duplicate_topic_choices(names: list[str]) -> None:
    with pytest.raises(ProductValidationError) as raised:
        validate_topic_names(names)

    assert raised.value.fields == ("topics",)


def test_canonical_website_key_normalizes_host_scheme_and_default_port() -> None:
    assert canonical_website_key("HTTPS://Example.COM:443/") == "https://example.com"
    assert canonical_website_key("https://example.com") == "https://example.com"


def test_canonical_website_key_retains_meaningful_paths_and_queries() -> None:
    first = canonical_website_key("https://example.com/product?a=1")
    second = canonical_website_key("https://example.com/other?a=1")

    assert first != second
    assert first == "https://example.com/product?a=1"


def test_canonical_website_key_rejects_non_https_or_malformed_urls() -> None:
    for value in (
        "http://example.com",
        "https://",
        "https://user@example.com",
        "https://%",
    ):
        with pytest.raises(ProductValidationError) as raised:
            canonical_website_key(value)
        assert raised.value.fields == ("website_url",)


def test_duplicate_website_keys_are_indexed_but_not_unique() -> None:
    website_indexes = [
        index
        for index in cast(Table, Product.__table__).indexes
        if "website_key" in index.columns.keys()
    ]

    assert website_indexes
    assert all(not index.unique for index in website_indexes)


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_equivalent_topics_reuse_one_row_under_concurrent_creation() -> None:
    async def verify() -> None:
        database = Database.connect(os.environ["DATABASE_URL"])
        repository = TopicRepository()
        suffix = uuid4().hex[:10]
        name = f"Race {suffix}"
        key = name.casefold()
        barrier = asyncio.Barrier(2)
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)

            async def resolve(label: str) -> TopicResolution:
                async with sessions() as session, session.begin():
                    await barrier.wait()
                    return await repository.get_or_create_topic(session, label)

            first, second = await asyncio.gather(resolve(name), resolve(f" {name.upper()} "))
            assert first.topic_id == second.topic_id
            assert first.display_name == name
            assert second.display_name == name.upper()
            async with sessions() as session:
                count = await session.scalar(
                    select(func.count()).select_from(Topic).where(Topic.name_key == key)
                )
            assert count == 1
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(delete(Topic).where(Topic.name_key == key))
            await database.close()

    asyncio.run(verify())


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_general_topic_choices_hide_unlaunched_proposals() -> None:
    async def verify() -> None:
        database = Database.connect(os.environ["DATABASE_URL"])
        repository = TopicRepository()
        suffix = uuid4().hex[:10]
        private_name = f"Private {suffix}"
        launched_name = f"Launched {suffix}"
        now = datetime.now(UTC)
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                await repository.get_or_create_topic(session, private_name)
                await repository.get_or_create_topic(session, launched_name)
                launched = await session.scalar(
                    select(Topic).where(Topic.name_key == launched_name.casefold())
                )
                assert launched is not None
                launched.first_launched_at = now
            async with sessions() as session:
                choices = await repository.list_topic_choices(session)
            assert [choice.display_name for choice in choices] == [launched_name]
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(
                    delete(Topic).where(
                        Topic.name_key.in_((private_name.casefold(), launched_name.casefold()))
                    )
                )
            await database.close()

    asyncio.run(verify())
