"""Topic and exact website-key persistence owned by the products feature."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.modules.products.models import Topic
from app.modules.products.service import canonical_topic_key, validate_topic_names
from sqlalchemy import select
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
