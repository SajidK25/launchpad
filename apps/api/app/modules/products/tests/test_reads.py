"""Private owner read projections never reveal another founder's draft or labels."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Table, delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.models import Account
from app.modules.auth.staff import AuthAccessService
from app.modules.products.models import Product, ProductAsset, ProductTopic, Topic
from app.modules.products.policies import ProductNotFoundError
from app.modules.products.repository import (
    ProductRepository,
    PublicCatalogRow,
    PublicLaunchLogoRow,
    PublicLaunchRow,
    TopicChoice,
)
from app.modules.products.service import ProductService, ProductValidationError
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec


class RecordingPublicLaunchRepository:
    """Small repository double for service date and validation rules."""

    query: dict[str, object]

    def __init__(self) -> None:
        self.products: list[PublicLaunchRow] = []
        self.logos: dict[UUID, PublicLaunchLogoRow] = {}
        self.topics: dict[UUID, tuple[str, ...]] = {}
        self.logo_calls: list[tuple[UUID, ...]] = []
        self.topic_calls: list[tuple[UUID, ...]] = []

    async def list_public_launches(
        self,
        session: AsyncSession,
        *,
        day_start: datetime,
        next_day_start: datetime,
        limit: int,
        after: tuple[str, UUID] | None,
    ) -> list[PublicLaunchRow]:
        self.query = {
            "day_start": day_start,
            "next_day_start": next_day_start,
            "limit": limit,
            "after": after,
        }
        return self.products

    async def list_public_launch_logos(
        self, session: AsyncSession, *, product_ids: tuple[UUID, ...]
    ) -> dict[UUID, PublicLaunchLogoRow]:
        self.logo_calls.append(product_ids)
        return self.logos

    async def list_public_launch_topics(
        self, session: AsyncSession, *, product_ids: tuple[UUID, ...]
    ) -> dict[UUID, tuple[str, ...]]:
        self.topic_calls.append(product_ids)
        return self.topics


class RecordingCatalogRepository(RecordingPublicLaunchRepository):
    """Catalog double records normalized filters and returns bounded page rows."""

    def __init__(self) -> None:
        super().__init__()
        self.catalog_products: list[PublicCatalogRow] = []
        self.catalog_query: dict[str, object] = {}
        self.catalog_topic_choices: list[TopicChoice] = []
        self.catalog_selected_topics: list[TopicChoice] = []
        self.topic_query: dict[str, object] = {}

    async def list_public_catalog(
        self,
        session: AsyncSession,
        *,
        terms: tuple[str, ...],
        topic_ids: tuple[UUID, ...],
        limit: int,
        after: tuple[datetime, str, UUID] | None,
    ) -> list[PublicCatalogRow]:
        self.catalog_query = {
            "terms": terms,
            "topic_ids": topic_ids,
            "limit": limit,
            "after": after,
        }
        return self.catalog_products

    async def list_public_catalog_topic_choices(
        self,
        session: AsyncSession,
        *,
        query: str | None,
        limit: int,
    ) -> list[TopicChoice]:
        self.topic_query = {"query": query, "limit": limit}
        return self.catalog_topic_choices

    async def list_public_catalog_selected_topics(
        self, session: AsyncSession, *, topic_ids: tuple[UUID, ...]
    ) -> list[TopicChoice]:
        self.topic_query["selected_ids"] = topic_ids
        return self.catalog_selected_topics


def test_catalog_search_indexes_are_partial_and_cover_order_and_topic_joins() -> None:
    product_indexes = {
        cast(str, index.name): index for index in cast(Table, Product.__table__).indexes
    }
    topic_indexes = {
        cast(str, index.name): index for index in cast(Table, ProductTopic.__table__).indexes
    }

    expected = {
        "ix_products_launched_name_trgm",
        "ix_products_launched_pitch_trgm",
        "ix_products_launched_description_trgm",
        "ix_products_launched_catalog_order",
    }
    assert expected <= product_indexes.keys()
    for name in expected - {"ix_products_launched_catalog_order"}:
        index = product_indexes[name]
        assert str(index.dialect_options["postgresql"]["where"]) == "status = 'launched'"
        assert index.dialect_options["postgresql"]["using"] == "gin"
        assert index.dialect_options["postgresql"]["ops"]
    assert "ix_product_topics_topic_product" in topic_indexes


def test_public_launches_uses_api_clock_when_date_is_omitted() -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 22, 18, 30, tzinfo=UTC)
        repository = RecordingPublicLaunchRepository()
        service = ProductService(
            member_access=AuthAccessService(),
            payload_codec=EmailPayloadCodec({"reads-test": b"r" * 32}, "reads-test"),
            repository=cast(ProductRepository, repository),
            clock=lambda: now,
        )
        page = await service.public_launches(cast(AsyncSession, None), requested_date=None)
        assert page.today_date.isoformat() == "2026-10-22"
        assert page.selected_date == page.today_date
        assert repository.query["day_start"] == now.replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    asyncio.run(verify())


def test_public_catalog_rejects_overlong_search_too_many_topics_and_invalid_pages() -> None:
    async def verify() -> None:
        repository = RecordingCatalogRepository()
        service = ProductService(
            member_access=AuthAccessService(),
            payload_codec=EmailPayloadCodec({"reads-test": b"r" * 32}, "reads-test"),
            repository=cast(ProductRepository, repository),
        )
        session = cast(AsyncSession, None)
        with pytest.raises(ProductValidationError, match="search text is too long"):
            await service.public_product_catalog(session, search="x" * 201)
        await service.public_product_catalog(session, search="x" * 200)
        assert repository.catalog_query["terms"] == ("x" * 200,)
        with pytest.raises(ProductValidationError, match="too many topics"):
            await service.public_product_catalog(
                session, topic_ids=tuple(uuid4() for _ in range(21))
            )
        for page_size in (0, -1, 51):
            with pytest.raises(ProductValidationError, match="invalid page size"):
                await service.public_product_catalog(session, first=page_size)
        with pytest.raises(ProductValidationError, match="invalid cursor"):
            await service.public_product_catalog(session, after="not-a-cursor")

    asyncio.run(verify())


def test_public_catalog_topics_normalizes_filters_and_enforces_bounds() -> None:
    async def verify() -> None:
        repository = RecordingCatalogRepository()
        topic_ids = (uuid4(), uuid4())
        repository.catalog_topic_choices = [
            TopicChoice(topic_id=topic_ids[0], display_name="Cloud")
        ]
        repository.catalog_selected_topics = repository.catalog_topic_choices
        service = ProductService(
            member_access=AuthAccessService(),
            payload_codec=EmailPayloadCodec({"reads-test": b"r" * 32}, "reads-test"),
            repository=cast(ProductRepository, repository),
        )
        session = cast(AsyncSession, None)

        options = await service.public_catalog_topics(
            session, query="  CLOuD ", selected_ids=(topic_ids[0], topic_ids[0]), first=5
        )
        assert repository.topic_query == {
            "query": "CLOuD",
            "limit": 5,
            "selected_ids": (topic_ids[0],),
        }
        assert options.choices == (repository.catalog_topic_choices[0],)
        assert options.selected == (repository.catalog_topic_choices[0],)
        with pytest.raises(ProductValidationError, match="too many topics"):
            await service.public_catalog_topics(
                session, selected_ids=tuple(uuid4() for _ in range(21))
            )
        for page_size in (0, 51):
            with pytest.raises(ProductValidationError, match="invalid page size"):
                await service.public_catalog_topics(session, first=page_size)

    asyncio.run(verify())


def test_public_catalog_normalizes_filters_and_batches_visible_card_data() -> None:
    async def verify() -> None:
        repository = RecordingCatalogRepository()
        topic_ids = (uuid4(), uuid4())
        product_ids = (uuid4(), uuid4(), uuid4())
        launched_at = datetime(2026, 10, 1, tzinfo=UTC)
        repository.catalog_products = [
            PublicCatalogRow(
                id=product_ids[0],
                name="Alpha",
                pitch="First pitch",
                launched_at=launched_at,
                sort_key="alpha",
            ),
            PublicCatalogRow(
                id=product_ids[1],
                name="Beta",
                pitch="Second pitch",
                launched_at=launched_at,
                sort_key="beta",
            ),
            PublicCatalogRow(
                id=product_ids[2],
                name="Charlie",
                pitch="Lookahead pitch",
                launched_at=launched_at,
                sort_key="charlie",
            ),
        ]
        repository.logos = {
            product_ids[0]: PublicLaunchLogoRow(
                id=uuid4(),
                product_id=product_ids[0],
                kind="logo",
                state="clean",
                media_type="image/png",
                byte_count=256,
            )
        }
        repository.topics = {product_ids[0]: ("AI",), product_ids[1]: ("Cloud",)}
        service = ProductService(
            member_access=AuthAccessService(),
            payload_codec=EmailPayloadCodec({"reads-test": b"r" * 32}, "reads-test"),
            repository=cast(ProductRepository, repository),
        )

        page = await service.public_product_catalog(
            cast(AsyncSession, None),
            search="  CAt   search  ",
            topic_ids=(topic_ids[1], topic_ids[0], topic_ids[1]),
            first=2,
        )

        assert repository.catalog_query == {
            "terms": ("CAt", "search"),
            "topic_ids": tuple(sorted(set(topic_ids), key=str)),
            "limit": 3,
            "after": None,
        }
        assert [item.id for item in page.items] == list(product_ids[:2])
        assert page.items[0].logo is not None and page.items[0].logo.byte_count == 256
        assert page.items[0].topics == ("AI",)
        assert repository.logo_calls == [product_ids[:2]]
        assert repository.topic_calls == [product_ids[:2]]
        assert page.next_cursor is not None

    asyncio.run(verify())


def test_public_catalog_cursor_is_stable_and_bound_to_normalized_filters() -> None:
    async def verify() -> None:
        repository = RecordingCatalogRepository()
        product_ids = (uuid4(), uuid4(), uuid4())
        topic_id = uuid4()
        launched_at = datetime(2026, 10, 1, tzinfo=UTC)
        repository.catalog_products = [
            PublicCatalogRow(
                id=product_id,
                name=name,
                pitch=f"{name} pitch",
                launched_at=launched_at,
                sort_key=name.casefold(),
            )
            for product_id, name in zip(product_ids, ("Alpha", "Beta", "Charlie"), strict=True)
        ]
        service = ProductService(
            member_access=AuthAccessService(),
            payload_codec=EmailPayloadCodec({"reads-test": b"r" * 32}, "reads-test"),
            repository=cast(ProductRepository, repository),
        )
        session = cast(AsyncSession, None)
        first_page = await service.public_product_catalog(
            session, search="cloud tools", topic_ids=(topic_id,), first=2
        )
        assert first_page.next_cursor is not None

        await service.public_product_catalog(
            session,
            search="  CLOUD   tools ",
            topic_ids=(topic_id,),
            first=2,
            after=first_page.next_cursor,
        )
        assert repository.catalog_query["after"] == (
            launched_at,
            "beta",
            product_ids[1],
        )
        with pytest.raises(ProductValidationError, match="invalid cursor"):
            await service.public_product_catalog(
                session,
                search="different filters",
                topic_ids=(topic_id,),
                after=first_page.next_cursor,
            )

    asyncio.run(verify())


def test_public_launches_validates_page_bounds_cursor_and_future_date() -> None:
    async def verify() -> None:
        repository = RecordingPublicLaunchRepository()
        today = datetime(2026, 10, 22, tzinfo=UTC)
        service = ProductService(
            member_access=AuthAccessService(),
            payload_codec=EmailPayloadCodec({"reads-test": b"r" * 32}, "reads-test"),
            repository=cast(ProductRepository, repository),
            clock=lambda: today,
        )
        session = cast(AsyncSession, None)
        await service.public_launches(session, requested_date=None)
        assert repository.query["limit"] == 21
        for page_size in (1, 50):
            await service.public_launches(session, requested_date=None, first=page_size)
            assert repository.query["limit"] == page_size + 1
        for page_size in (0, -1, 51):
            with pytest.raises(ProductValidationError, match="invalid page size"):
                await service.public_launches(session, requested_date=None, first=page_size)
        with pytest.raises(ProductValidationError, match="invalid cursor"):
            await service.public_launches(session, requested_date=None, after="not-a-cursor")
        with pytest.raises(ProductValidationError, match="future launch dates"):
            await service.public_launches(session, requested_date=today.date() + timedelta(days=1))

    asyncio.run(verify())


def test_public_launches_batch_loads_only_visible_page_associations() -> None:
    async def verify() -> None:
        now = datetime(2026, 10, 22, 18, 30, tzinfo=UTC)
        repository = RecordingPublicLaunchRepository()
        visible_ids = (uuid4(), uuid4())
        lookahead_id = uuid4()
        repository.products = [
            PublicLaunchRow(id=visible_ids[0], name="Alpha", pitch="Pitch A", sort_key="alpha"),
            PublicLaunchRow(id=visible_ids[1], name="Beta", pitch="Pitch B", sort_key="beta"),
            PublicLaunchRow(id=lookahead_id, name="Charlie", pitch="Pitch C", sort_key="charlie"),
        ]
        repository.logos = {
            visible_ids[0]: PublicLaunchLogoRow(
                id=uuid4(),
                product_id=visible_ids[0],
                kind="logo",
                state="clean",
                media_type="image/png",
                byte_count=128,
            )
        }
        repository.topics = {visible_ids[0]: ("Development",)}
        service = ProductService(
            member_access=AuthAccessService(),
            payload_codec=EmailPayloadCodec({"reads-test": b"r" * 32}, "reads-test"),
            repository=cast(ProductRepository, repository),
            clock=lambda: now,
        )

        page = await service.public_launches(cast(AsyncSession, None), requested_date=None, first=2)

        assert [item.id for item in page.items] == list(visible_ids)
        assert repository.logo_calls == [visible_ids]
        assert repository.topic_calls == [visible_ids]

    asyncio.run(verify())


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_public_catalog_matches_case_insensitive_partial_terms_across_fields() -> None:
    async def verify() -> None:
        database = Database.connect(os.environ["DATABASE_URL"])
        founder_id = uuid4()
        product_ids = (uuid4(), uuid4(), uuid4())
        now = datetime.now(UTC)
        launch_date = datetime(2026, 10, 1, tzinfo=UTC)
        try:
            await database.prepare()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
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
                await session.flush()
                await session.execute(
                    insert(Product).values(
                        [
                            {
                                "id": product_ids[0],
                                "founder_id": founder_id,
                                "status": "launched",
                                "version": 1,
                                "name": "Alpha Systems",
                                "pitch": "Automation for teams",
                                "description": "An automatic public catalog for founders",
                                "website_url": "https://alpha.example.test",
                                "website_key": "https://alpha.example.test",
                                "launched_at": launch_date,
                                "created_at": now,
                                "updated_at": now,
                            },
                            {
                                "id": product_ids[1],
                                "founder_id": founder_id,
                                "status": "launched",
                                "version": 1,
                                "name": "Alphabet Tools",
                                "pitch": "An ordinary product",
                                "description": "No second query term here",
                                "website_url": "https://alphabet.example.test",
                                "website_key": "https://alphabet.example.test",
                                "launched_at": launch_date,
                                "created_at": now,
                                "updated_at": now,
                            },
                            {
                                "id": product_ids[2],
                                "founder_id": founder_id,
                                "status": "approved",
                                "version": 1,
                                "name": "Alpha Private",
                                "pitch": "Automation for private teams",
                                "description": "A private catalog",
                                "website_url": "https://private.example.test",
                                "website_key": "https://private.example.test",
                                "launched_at": None,
                                "created_at": now,
                                "updated_at": now,
                            },
                        ]
                    )
                )
            async with sessions() as session:
                rows = await ProductRepository().list_public_catalog(
                    session,
                    terms=("ALP", "matic"),
                    topic_ids=(),
                    limit=20,
                    after=None,
                )
                assert [row.id for row in rows] == [product_ids[0]]
                pitch_only_rows = await ProductRepository().list_public_catalog(
                    session,
                    terms=("MATION",),
                    topic_ids=(),
                    limit=20,
                    after=None,
                )
                assert [row.id for row in pitch_only_rows] == [product_ids[0]]
                literal_wildcard = await ProductRepository().list_public_catalog(
                    session,
                    terms=("%",),
                    topic_ids=(),
                    limit=20,
                    after=None,
                )
                assert literal_wildcard == []
                first_page = await ProductRepository().list_public_catalog(
                    session,
                    terms=(),
                    topic_ids=(),
                    limit=1,
                    after=None,
                )
                second_page = await ProductRepository().list_public_catalog(
                    session,
                    terms=(),
                    topic_ids=(),
                    limit=1,
                    after=(
                        first_page[0].launched_at,
                        first_page[0].sort_key,
                        first_page[0].id,
                    ),
                )
                assert [row.id for row in first_page + second_page] == list(product_ids[:2])
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(delete(Product).where(Product.id.in_(product_ids)))
                await connection.execute(delete(Account).where(Account.id == founder_id))
            await database.close()

    asyncio.run(verify())


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_public_catalog_orders_by_launch_date_name_and_id_across_cursors() -> None:
    async def verify() -> None:
        database = Database.connect(os.environ["DATABASE_URL"])
        founder_id = uuid4()
        product_ids = tuple(UUID(int=value) for value in (10_100, 10_101, 10_102, 10_103))
        now = datetime.now(UTC)
        older = datetime(2026, 10, 1, tzinfo=UTC)
        newer = datetime(2026, 10, 2, tzinfo=UTC)
        products = (
            (product_ids[0], "Same Name", older),
            (product_ids[1], "Beta", newer),
            (product_ids[2], "Same Name", older),
            (product_ids[3], "Alpha", older),
        )
        try:
            await database.prepare()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
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
                await session.flush()
                await session.execute(
                    insert(Product).values(
                        [
                            {
                                "id": product_id,
                                "founder_id": founder_id,
                                "status": "launched",
                                "version": 1,
                                "name": name,
                                "pitch": "Ordering fixture",
                                "description": "Ordering fixture description",
                                "website_url": f"https://{product_id}.example.test",
                                "website_key": f"{product_id}.example.test",
                                "launched_at": launched_at,
                                "created_at": now,
                                "updated_at": now,
                            }
                            for product_id, name, launched_at in products
                        ]
                    )
                )
            async with sessions() as session:
                repository = ProductRepository()
                first_page = await repository.list_public_catalog(
                    session,
                    terms=(),
                    topic_ids=(),
                    limit=2,
                    after=None,
                )
                second_page = await repository.list_public_catalog(
                    session,
                    terms=(),
                    topic_ids=(),
                    limit=2,
                    after=(
                        first_page[-1].launched_at,
                        first_page[-1].sort_key,
                        first_page[-1].id,
                    ),
                )
                assert [row.id for row in first_page] == [product_ids[1], product_ids[3]]
                assert [row.id for row in second_page] == [product_ids[0], product_ids[2]]
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(delete(Product).where(Product.id.in_(product_ids)))
                await connection.execute(delete(Account).where(Account.id == founder_id))
            await database.close()

    asyncio.run(verify())


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_public_catalog_topic_filters_match_any_selected_topic_without_duplicates() -> None:
    async def verify() -> None:
        database = Database.connect(os.environ["DATABASE_URL"])
        founder_id = uuid4()
        product_ids = (uuid4(), uuid4(), uuid4(), uuid4())
        topic_ids = (uuid4(), uuid4())
        now = datetime.now(UTC)
        launch_date = datetime(2026, 10, 1, tzinfo=UTC)
        try:
            await database.prepare()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
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
                await session.flush()
                await session.execute(
                    insert(Product).values(
                        [
                            {
                                "id": product_id,
                                "founder_id": founder_id,
                                "status": status,
                                "version": 1,
                                "name": name,
                                "pitch": "Cloud tools",
                                "description": "Public cloud description",
                                "website_url": f"https://{product_id}.example.test",
                                "website_key": f"{product_id}.example.test",
                                "launched_at": launch_date if status == "launched" else None,
                                "created_at": now,
                                "updated_at": now,
                            }
                            for product_id, status, name in zip(
                                product_ids,
                                ("launched", "launched", "approved", "launched"),
                                ("Alpha", "Beta", "Private", "No selected topic"),
                                strict=True,
                            )
                        ]
                    )
                )
                await session.execute(
                    insert(Topic).values(
                        [
                            {
                                "id": topic_ids[0],
                                "display_name": "AI",
                                "name_key": "ai",
                                "first_launched_at": launch_date,
                            },
                            {
                                "id": topic_ids[1],
                                "display_name": "Cloud",
                                "name_key": "cloud",
                                "first_launched_at": launch_date,
                            },
                        ]
                    )
                )
                await session.execute(
                    insert(ProductTopic).values(
                        [
                            {
                                "product_id": product_ids[0],
                                "topic_id": topic_ids[0],
                                "position": 1,
                                "selected_label": "AI",
                            },
                            {
                                "product_id": product_ids[0],
                                "topic_id": topic_ids[1],
                                "position": 2,
                                "selected_label": "Cloud",
                            },
                            {
                                "product_id": product_ids[1],
                                "topic_id": topic_ids[1],
                                "position": 1,
                                "selected_label": "Cloud",
                            },
                            {
                                "product_id": product_ids[2],
                                "topic_id": topic_ids[0],
                                "position": 1,
                                "selected_label": "AI",
                            },
                        ]
                    )
                )
            async with sessions() as session:
                rows = await ProductRepository().list_public_catalog(
                    session,
                    terms=("CLOUD",),
                    topic_ids=topic_ids,
                    limit=20,
                    after=None,
                )
                assert {row.id for row in rows} == set(product_ids[:2])
                assert len(rows) == 2
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(delete(Product).where(Product.id.in_(product_ids)))
                await connection.execute(delete(Topic).where(Topic.id.in_(topic_ids)))
                await connection.execute(delete(Account).where(Account.id == founder_id))
            await database.close()

    asyncio.run(verify())


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_public_catalog_topic_options_require_a_current_launched_association() -> None:
    async def verify() -> None:
        database = Database.connect(os.environ["DATABASE_URL"])
        founder_id = uuid4()
        product_ids = tuple(uuid4() for _ in range(7))
        topic_ids = tuple(uuid4() for _ in range(7))
        statuses = (
            "launched",
            "draft",
            "submitted",
            "changes_requested",
            "rejected",
            "approved",
            "scheduled",
        )
        now = datetime.now(UTC)
        launch_date = datetime(2026, 10, 1, tzinfo=UTC)
        try:
            await database.prepare()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
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
                await session.flush()
                await session.execute(
                    insert(Product).values(
                        [
                            {
                                "id": product_id,
                                "founder_id": founder_id,
                                "status": status,
                                "version": 1,
                                "name": f"Catalog product {index}",
                                "pitch": "Catalog pitch",
                                "description": "Catalog description",
                                "website_url": f"https://catalog-{index}.example.test",
                                "website_key": f"catalog-{index}.example.test",
                                "launched_at": (launch_date if status == "launched" else None),
                                "created_at": now,
                                "updated_at": now,
                            }
                            for index, (product_id, status) in enumerate(
                                zip(product_ids, statuses, strict=True)
                            )
                        ]
                    )
                )
                await session.execute(
                    insert(Topic).values(
                        [
                            {
                                "id": topic_id,
                                "display_name": f"Topic {index}",
                                "name_key": f"topic {index}",
                                "first_launched_at": launch_date,
                            }
                            for index, topic_id in enumerate(topic_ids)
                        ]
                    )
                )
                await session.execute(
                    insert(ProductTopic).values(
                        [
                            {
                                "product_id": product_id,
                                "topic_id": topic_id,
                                "position": 1,
                                "selected_label": f"Topic {index}",
                            }
                            for index, (product_id, topic_id) in enumerate(
                                zip(product_ids, topic_ids, strict=True)
                            )
                        ]
                    )
                )
            async with sessions() as session:
                repository = ProductRepository()
                choices = await repository.list_public_catalog_topic_choices(
                    session, query=None, limit=50
                )
                selected = await repository.list_public_catalog_selected_topics(
                    session, topic_ids=topic_ids
                )
                catalog = await repository.list_public_catalog(
                    session, terms=(), topic_ids=(), limit=20, after=None
                )
                assert [(choice.topic_id, choice.display_name) for choice in choices] == [
                    (topic_ids[0], "Topic 0")
                ]
                assert [(choice.topic_id, choice.display_name) for choice in selected] == [
                    (topic_ids[0], "Topic 0")
                ]
                assert [row.id for row in catalog] == [product_ids[0]]
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(delete(Product).where(Product.id.in_(product_ids)))
                await connection.execute(delete(Topic).where(Topic.id.in_(topic_ids)))
                await connection.execute(delete(Account).where(Account.id == founder_id))
            await database.close()

    asyncio.run(verify())


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_public_launches_filter_utc_day_and_page_only_published_cards() -> None:
    async def verify() -> None:
        database = Database.connect(os.environ["DATABASE_URL"])
        founder_id = uuid4()
        topic_id = uuid4()
        today = datetime(2026, 10, 22, tzinfo=UTC)
        selected = today.date()
        statuses = ("draft", "submitted", "changes_requested", "rejected", "approved", "scheduled")
        launched_ids = [UUID(int=index) for index in range(10, 17)]
        boundary_ids = (UUID(int=20), UUID(int=21), UUID(int=22))
        now = datetime.now(UTC)
        service = ProductService(
            member_access=AuthAccessService(),
            payload_codec=EmailPayloadCodec({"reads-test": b"r" * 32}, "reads-test"),
            clock=lambda: datetime(2026, 10, 22, 12, tzinfo=UTC),
        )
        try:
            await database.prepare()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
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
                await session.flush()
                await session.flush()
                products = []
                names = ("beta", "Alpha", "ALPHA", "delta", "Charlie", "İstanbul", "Éclair")
                for product_id, name in zip(launched_ids, names, strict=True):
                    products.append(
                        Product(
                            id=product_id,
                            founder_id=founder_id,
                            status="launched",
                            version=1,
                            name=name,
                            pitch=f"Pitch for {name}",
                            description="Public detail not part of card",
                            website_url="https://example.test",
                            website_key=f"https://example.test/{product_id}",
                            launched_at=today + timedelta(hours=1),
                            created_at=now,
                            updated_at=now,
                        )
                    )
                products.extend(
                    [
                        Product(
                            id=boundary_ids[0],
                            founder_id=founder_id,
                            status="launched",
                            version=1,
                            name="before",
                            pitch="Before",
                            description="d",
                            website_url="https://example.test",
                            website_key="before",
                            launched_at=today - timedelta(microseconds=1),
                            created_at=now,
                            updated_at=now,
                        ),
                        Product(
                            id=boundary_ids[1],
                            founder_id=founder_id,
                            status="launched",
                            version=1,
                            name="after",
                            pitch="After",
                            description="d",
                            website_url="https://example.test",
                            website_key="after",
                            launched_at=today + timedelta(days=1),
                            created_at=now,
                            updated_at=now,
                        ),
                    ]
                )
                for status in statuses:
                    is_draft = status == "draft"
                    products.append(
                        Product(
                            id=uuid4(),
                            founder_id=founder_id,
                            status=status,
                            version=1,
                            name=None if is_draft else f"private-{status}",
                            pitch=None if is_draft else "Private",
                            description=None if is_draft else "d",
                            website_url=None if is_draft else "https://example.test",
                            website_key=None if is_draft else f"private-{status}",
                            launched_at=None,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                await session.execute(
                    insert(Product).values(
                        [
                            {
                                column.key: getattr(product, column.key)
                                for column in Product.__table__.columns
                            }
                            for product in products
                        ]
                    )
                )
                session.add(Topic(id=topic_id, display_name="AI Tools", name_key="ai tools"))
                await session.flush()
                session.add_all(
                    [
                        ProductTopic(
                            product_id=launched_ids[0],
                            topic_id=topic_id,
                            position=1,
                            selected_label="AI tools",
                        ),
                        ProductAsset(
                            id=UUID(int=30),
                            product_id=launched_ids[0],
                            kind="logo",
                            state="clean",
                            staging_key="reads/logo-stage",
                            clean_key="reads/logo-clean",
                            media_type="image/png",
                            byte_count=100,
                            position=None,
                            expires_at=None,
                            attached_at=now,
                        ),
                    ]
                )
            async with sessions() as session:
                first = await service.public_launches(session, requested_date=selected, first=2)
                second = await service.public_launches(
                    session, requested_date=selected, first=2, after=first.next_cursor
                )
                third = await service.public_launches(
                    session, requested_date=selected, first=2, after=second.next_cursor
                )
                pages = [first, second, third]
                while pages[-1].next_cursor is not None:
                    pages.append(
                        await service.public_launches(
                            session,
                            requested_date=selected,
                            first=2,
                            after=pages[-1].next_cursor,
                        )
                    )
                expected_names = (
                    await session.scalars(
                        select(Product.name)
                        .where(
                            Product.status == "launched",
                            Product.launched_at >= today,
                            Product.launched_at < today + timedelta(days=1),
                            Product.founder_id == founder_id,
                        )
                        .order_by(func.lower(Product.name), Product.id)
                    )
                ).all()
                cards = [card for page in pages for card in page.items]
                assert [card.name for card in cards] == list(expected_names)
                assert first.items[0].id == min(launched_ids[1], launched_ids[2])
                beta_card = next(card for card in cards if card.name == "beta")
                assert beta_card.logo is not None and beta_card.logo.id == UUID(int=30)
                assert beta_card.topics == ("AI tools",)
                assert all(page.next_cursor for page in pages[:-1])
                assert pages[-1].next_cursor is None
                empty = await service.public_launches(
                    session, requested_date=selected - timedelta(days=2)
                )
                assert empty.items == () and empty.next_cursor is None
                with pytest.raises(ProductValidationError, match="invalid cursor"):
                    await service.public_launches(
                        session,
                        requested_date=selected - timedelta(days=2),
                        after=first.next_cursor,
                    )
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(delete(Product).where(Product.founder_id == founder_id))
                await connection.execute(delete(Topic).where(Topic.id == topic_id))
                await connection.execute(delete(Account).where(Account.id == founder_id))
            await database.close()

    asyncio.run(verify())


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_owner_reads_keep_private_topic_labels_scoped() -> None:
    async def verify() -> None:
        database = Database.connect(os.environ["DATABASE_URL"])
        founder_ids = (uuid4(), uuid4())
        product_ids = (uuid4(), uuid4())
        newest_id = uuid4()
        topic_id = uuid4()
        asset_ids = (UUID(int=1), UUID(int=2))
        topic_name = f"AI Tools {topic_id.hex[:8]}"
        now = datetime.now(UTC)
        service = ProductService(
            member_access=AuthAccessService(),
            payload_codec=EmailPayloadCodec({"reads-test": b"r" * 32}, "reads-test"),
        )
        try:
            await database.prepare()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                for founder_id in founder_ids:
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
                await session.execute(
                    insert(Product).values(
                        [
                            {
                                "id": product_id,
                                "founder_id": founder_id,
                                "status": "draft",
                                "version": 1,
                                "name": "Private draft",
                                "created_at": now,
                                "updated_at": now,
                            }
                            for founder_id, product_id in zip(founder_ids, product_ids, strict=True)
                        ]
                    ),
                )
                await session.execute(
                    insert(Product).values(
                        id=newest_id,
                        founder_id=founder_ids[0],
                        status="draft",
                        version=0,
                        created_at=now,
                        updated_at=now + timedelta(minutes=1),
                    )
                )
                session.add(
                    Topic(id=topic_id, display_name=topic_name, name_key=topic_name.casefold())
                )
                await session.flush()
                session.add_all(
                    [
                        ProductTopic(
                            product_id=product_ids[0],
                            topic_id=topic_id,
                            position=1,
                            selected_label=topic_name,
                        ),
                        ProductTopic(
                            product_id=product_ids[1],
                            topic_id=topic_id,
                            position=1,
                            selected_label=topic_name.upper(),
                        ),
                    ]
                )
                session.add_all(
                    ProductAsset(
                        id=asset_id,
                        product_id=product_ids[0],
                        kind="screenshot",
                        state="clean",
                        staging_key=f"products/{founder_ids[0]}/{product_ids[0]}/{asset_id}-stage",
                        clean_key=f"products/{founder_ids[0]}/{product_ids[0]}/{asset_id}-clean",
                        media_type="image/png",
                        byte_count=100,
                        position=position,
                        expires_at=None,
                        attached_at=now,
                    )
                    for asset_id, position in zip(asset_ids, (2, 1), strict=True)
                )
            async with sessions() as session:
                first = await service.owner_detail(
                    session, actor_id=founder_ids[0], product_id=product_ids[0]
                )
                second = await service.owner_detail(
                    session, actor_id=founder_ids[1], product_id=product_ids[1]
                )
                own_page = await service.owner_list(session, actor_id=founder_ids[0], first=1)
                assert [topic.display_name for topic in first.topics] == [topic_name]
                assert [asset.id for asset in first.assets] == [asset_ids[1], asset_ids[0]]
                assert [topic.display_name for topic in second.topics] == [topic_name.upper()]
                assert [item.id for item in own_page.items] == [newest_id]
                assert own_page.next_cursor is not None
                next_page = await service.owner_list(
                    session, actor_id=founder_ids[0], first=1, after=own_page.next_cursor
                )
                assert [item.id for item in next_page.items] == [product_ids[0]]
                assert next_page.next_cursor is None
                choices = await service.topic_choices(session, actor_id=founder_ids[0])
                assert [(choice.topic_id, choice.display_name) for choice in choices] == [
                    (topic_id, topic_name)
                ]
                other_choices = await service.topic_choices(session, actor_id=founder_ids[1])
                assert [choice.display_name for choice in other_choices] == [topic_name.upper()]
                with pytest.raises(ProductNotFoundError):
                    await service.owner_detail(
                        session, actor_id=founder_ids[0], product_id=product_ids[1]
                    )
            async with sessions() as session, session.begin():
                topic = await session.get(Topic, topic_id)
                assert topic is not None
                topic.first_launched_at = now
            async with sessions() as session:
                launched = await service.topic_choices(session, actor_id=founder_ids[1])
                assert [(choice.topic_id, choice.display_name) for choice in launched] == [
                    (topic_id, topic_name)
                ]
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(
                    delete(Product).where(Product.id.in_((*product_ids, newest_id)))
                )
                await connection.execute(delete(Topic).where(Topic.id == topic_id))
                await connection.execute(delete(Account).where(Account.id.in_(founder_ids)))
            await database.close()

    asyncio.run(verify())
