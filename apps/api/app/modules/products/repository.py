"""Topic and exact website-key persistence owned by the products feature."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from app.modules.products.models import Product, Topic
from app.modules.products.policies import ProductConflictError
from app.modules.products.schemas import ProductContentInput
from app.modules.products.service import canonical_topic_key, validate_topic_names
from sqlalchemy import func, select, update
from sqlalchemy import insert as sa_insert
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7


@dataclass(frozen=True, slots=True)
class TopicResolution:
    """A topic identity paired with the current founder's own display label."""

    topic_id: UUID
    display_name: str


@dataclass(frozen=True, slots=True)
class TopicChoice:
    """A launched topic that is safe to offer as a general choice."""

    topic_id: UUID
    display_name: str


class TopicRepository:
    """Persist canonical topic identities without exposing private proposals."""

    async def get_or_create_topic(
        self, session: AsyncSession, display_name: str
    ) -> TopicResolution:
        """Reuse an equivalent key atomically while returning only the caller's label."""

        label = validate_topic_names([display_name])[0]
        topic_id = uuid7()
        statement = (
            insert(Topic)
            .values(id=topic_id, display_name=label.display_name, name_key=label.name_key)
            .on_conflict_do_nothing(index_elements=[Topic.name_key])
            .returning(Topic.id)
        )
        result = await session.execute(statement)
        resolved_id = result.scalar_one_or_none()
        if resolved_id is None:
            resolved_id = await session.scalar(
                select(Topic.id).where(Topic.name_key == label.name_key)
            )
        if resolved_id is None:
            raise RuntimeError("topic key was not available after conflict resolution")
        return TopicResolution(topic_id=resolved_id, display_name=label.display_name)

    async def list_topic_choices(
        self, session: AsyncSession, *, query: str | None = None, limit: int = 20
    ) -> list[TopicChoice]:
        """Return only launched topics; private proposals are never general suggestions."""

        statement = select(Topic).where(Topic.first_launched_at.is_not(None))
        if query is not None and query.strip():
            statement = statement.where(
                Topic.name_key.startswith(canonical_topic_key(query), autoescape=True)
            )
        topics = (
            await session.scalars(statement.order_by(Topic.name_key).limit(min(max(limit, 1), 50)))
        ).all()
        return [TopicChoice(topic_id=topic.id, display_name=topic.display_name) for topic in topics]


class ProductRepository:
    """Persist owner-scoped draft rows and their optimistic version."""

    async def count_drafts(self, session: AsyncSession, *, founder_id: UUID) -> int:
        count = await session.scalar(
            select(func.count())
            .select_from(Product)
            .where(Product.founder_id == founder_id, Product.status == "draft")
        )
        return int(count or 0)

    async def create_draft(
        self, session: AsyncSession, *, founder_id: UUID, now: datetime
    ) -> Product:
        statement = (
            sa_insert(Product)
            .values(
                id=uuid7(),
                founder_id=founder_id,
                status="draft",
                version=0,
                created_at=now,
                updated_at=now,
            )
            .returning(Product)
        )
        result = await session.execute(statement)
        return result.scalar_one()

    async def get_draft(
        self,
        session: AsyncSession,
        *,
        product_id: UUID,
        founder_id: UUID,
        lock: bool = False,
    ) -> Product | None:
        statement = (
            select(Product)
            .where(
                Product.id == product_id,
                Product.founder_id == founder_id,
                Product.status == "draft",
            )
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        return cast(Product | None, await session.scalar(statement))

    async def save_draft(
        self,
        session: AsyncSession,
        *,
        product: Product,
        content: ProductContentInput,
        website_key: str | None,
        now: datetime,
    ) -> Product:
        statement = (
            update(Product)
            .where(
                Product.id == product.id,
                Product.founder_id == product.founder_id,
                Product.status == "draft",
                Product.version == product.version,
            )
            .values(
                name=content.name,
                pitch=content.pitch,
                description=content.description,
                website_url=content.website_url,
                website_key=website_key,
                version=Product.version + 1,
                updated_at=now,
            )
            .returning(Product)
            .execution_options(populate_existing=True)
        )
        result = await session.execute(statement)
        saved = result.scalar_one_or_none()
        if saved is None:
            raise ProductConflictError("product changed; reload and retry")
        return saved
