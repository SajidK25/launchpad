"""Canonical topic and website key behavior."""

import asyncio
import os
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Table, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.models import Account
from app.modules.auth.staff import AuthAccessService
from app.modules.products.models import Product, ProductTopic, Topic
from app.modules.products.policies import ProductInfrastructureError
from app.modules.products.repository import TopicRepository, TopicResolution
from app.modules.products.schemas import ProductContentInput
from app.modules.products.service import (
    ProductService,
    ProductValidationError,
    canonical_topic_key,
    canonical_website_key,
    validate_topic_names,
)
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.models import OutboxMessage
from app.shared.events.outbox import OutboxEvent, OutboxRepository


class _FailAfterOutboxWrite:
    async def add(self, session: AsyncSession, event: OutboxEvent) -> UUID:
        await OutboxRepository().add(session, event)
        raise RuntimeError("simulated product event write failure")


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
def test_draft_topic_save_replaces_order_and_preserves_omitted_selection() -> None:
    async def verify() -> None:
        database = Database.connect(os.environ["DATABASE_URL"])
        founder_id = uuid4()
        product_id = uuid4()
        suffix = uuid4().hex[:10]
        labels = [f"Alpha {suffix}", f"Beta {suffix}"]
        failed_label = f"Failed {suffix}"
        codec = EmailPayloadCodec({"topics-test": b"t" * 32}, "topics-test")
        service = ProductService(member_access=AuthAccessService(), payload_codec=codec)
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            now = datetime.now(UTC)
            async with sessions() as session, session.begin():
                session.add(
                    Account(
                        id=founder_id,
                        email_display=f"{founder_id}@example.test",
                        email_key=f"{founder_id}@example.test",
                        password_hash="integration-only-placeholder",
                        created_at=now,
                        updated_at=now,
                    )
                )
            async with sessions() as session, session.begin():
                draft = await service.create_draft(session, actor_id=founder_id)
                product_id = draft.id
            async with sessions() as session, session.begin():
                saved = await service.save_draft(
                    session,
                    actor_id=founder_id,
                    product_id=product_id,
                    expected_version=0,
                    content=ProductContentInput(),
                    topic_names=labels,
                )
                assert saved.version == 1
            async with sessions() as session, session.begin():
                unchanged = await service.save_draft(
                    session,
                    actor_id=founder_id,
                    product_id=product_id,
                    expected_version=1,
                    content=ProductContentInput(),
                )
                assert unchanged.version == 1
                reordered = await service.save_draft(
                    session,
                    actor_id=founder_id,
                    product_id=product_id,
                    expected_version=1,
                    content=ProductContentInput(),
                    topic_names=[labels[1].upper(), labels[0].upper()],
                )
                assert reordered.version == 2
            async with sessions() as session:
                selected = list(
                    await session.scalars(
                        select(Topic.name_key)
                        .join(ProductTopic, ProductTopic.topic_id == Topic.id)
                        .where(ProductTopic.product_id == product_id)
                        .order_by(ProductTopic.position)
                    )
                )
                count = await session.scalar(
                    select(func.count())
                    .select_from(Topic)
                    .where(Topic.name_key.in_(label.casefold() for label in labels))
                )
                events = list(
                    await session.scalars(
                        select(OutboxMessage.event_type).where(
                            OutboxMessage.aggregate_id == product_id
                        )
                    )
                )
            assert selected == [labels[1].casefold(), labels[0].casefold()]
            async with sessions() as session:
                selected_labels = list(
                    await session.scalars(
                        select(ProductTopic.selected_label)
                        .where(ProductTopic.product_id == product_id)
                        .order_by(ProductTopic.position)
                    )
                )
            assert selected_labels == [labels[1].upper(), labels[0].upper()]
            assert count == 2
            assert events.count("product.saved.v1") == 2
            async with sessions() as session, session.begin():
                recased = await service.save_draft(
                    session,
                    actor_id=founder_id,
                    product_id=product_id,
                    expected_version=2,
                    content=ProductContentInput(),
                    topic_names=[labels[1], labels[0]],
                )
                assert recased.version == 3
            async with sessions() as session:
                recased_labels = list(
                    await session.scalars(
                        select(ProductTopic.selected_label)
                        .where(ProductTopic.product_id == product_id)
                        .order_by(ProductTopic.position)
                    )
                )
                assert recased_labels == [labels[1], labels[0]]
            async with sessions() as session, session.begin():
                cleared = await service.save_draft(
                    session,
                    actor_id=founder_id,
                    product_id=product_id,
                    expected_version=3,
                    content=ProductContentInput(),
                    topic_names=[],
                )
                assert cleared.version == 4
            async with sessions() as session:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(ProductTopic)
                        .where(ProductTopic.product_id == product_id)
                    )
                    == 0
                )
            failing = ProductService(
                member_access=AuthAccessService(),
                payload_codec=codec,
                outbox_repository=_FailAfterOutboxWrite(),
            )
            with pytest.raises(ProductInfrastructureError):
                async with sessions() as session, session.begin():
                    await failing.save_draft(
                        session,
                        actor_id=founder_id,
                        product_id=product_id,
                        expected_version=4,
                        content=ProductContentInput(name="Not committed"),
                        topic_names=[failed_label],
                    )
            async with sessions() as session:
                product = await session.get(Product, product_id)
                assert product is not None
                assert product.version == 4
                assert product.name is None
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(ProductTopic)
                        .where(ProductTopic.product_id == product_id)
                    )
                    == 0
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(Topic)
                        .where(Topic.name_key == failed_label.casefold())
                    )
                    == 0
                )
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(
                    delete(OutboxMessage).where(OutboxMessage.aggregate_id == product_id)
                )
                await connection.execute(delete(Product).where(Product.id == product_id))
                await connection.execute(delete(Account).where(Account.id == founder_id))
                await connection.execute(
                    delete(Topic).where(
                        Topic.name_key.in_([label.casefold() for label in (*labels, failed_label)])
                    )
                )
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
